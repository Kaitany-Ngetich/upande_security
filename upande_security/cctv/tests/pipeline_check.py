"""End-to-end CCTV check with simulated events. Cleans up after itself.
Run: cd ~/frappe-bench/sites && ../env/bin/python ../apps/upande_security/upande_security/cctv/tests/pipeline_check.py"""
import frappe

frappe.init(site="mysite.local", sites_path=".")
frappe.connect()
frappe.set_user("Administrator")

from upande_security.cctv import plates, simulator, settings, tokens, alerts  # noqa: E402

FARM = "Kapkolia"
ok = fail = 0


def check(label, cond, extra=""):
	global ok, fail
	if cond:
		ok += 1
		print("  PASS", label)
	else:
		fail += 1
		print("  FAIL", label, extra)


# ---- plates (pure)
print("plates")
check("normalize", plates.normalize(" kda-123 a ") == "KDA123A")
check("display", plates.display("KMHC329U") == "KMHC 329U")
check("classify motorcycle", plates.classify("KMHC 329U")["vehicle_class"] == "Motorcycle")
check("repair O->0", plates.repair("KDA 12OA")[0] == "KDA120A", plates.repair("KDA 12OA"))
check("similarity lookalike", plates.similarity("KDB O76A", "KDB 076A") >= 0.9)
check("similarity different", plates.similarity("KDA 123A", "KCC 789C") == 0)

# ---- switch on locally for the test
orig = {k: frappe.db.get_single_value("CCTV Settings", k) for k in settings.SWITCHES}
frappe.db.set_single_value("Security Ops Settings", "feature_cctv", 1)
for k in ("enabled", "live_view_enabled", "alerts_enabled", "anpr_enabled"):
	frappe.db.set_single_value("CCTV Settings", k, 1)
doc = frappe.get_single("CCTV Settings")
doc.gateway_jwt_secret = "test-secret-123"
doc.flags.ignore_permissions = True
doc.save()
settings.clear()

wl = frappe.get_doc({"doctype": "Security Watchlist", "full_name": "TEST Vehicle", "person_type": "External",
	"vehicle_plate": "KXX 999Z", "status": "Active", "reason": "cctv test"}).insert(ignore_permissions=True)
from upande_security.api import watchlist
watchlist.clear_cache()

try:
	simulator.clear_demo()  # start clean: any demo already loaded would mix its alerts into these checks
	demo = simulator.seed_demo(FARM)
	cam = demo["cameras"]
	print("demo", demo)

	print("vehicles")
	r = simulator.simulate(cam["Gate In"], "plate_read", at="2026-11-12 08:22:00", confidence=0.95, plate="KDB 076A", direction="in")
	print("   ", r)
	visit = frappe.db.get_value("CCTV Vehicle Sighting", {"event": r["event"]}, "vehicle_visit")
	v = frappe.get_doc("CCTV Vehicle Visit", visit)
	check("booked visitor matched to appointment", v.appointment == "APMT-Hillary maiyo-1293348", v.as_dict().get("appointment"))
	check("party named", "Hillary" in (v.party_name or ""), v.party_name)
	check("no review for a confident match", not frappe.db.exists("CCTV Review Item", {"vehicle_visit": visit}))

	r2 = simulator.simulate(cam["Gate In"], "plate_read", at="2026-11-12 08:22:20", confidence=0.95, plate="KDB 076A", direction="in")
	check("duplicate read suppressed", "duplicate" in str(r2.get("result")), r2)

	r3 = simulator.simulate(cam["Dock"], "plate_read", at="2026-11-12 09:05:00", confidence=0.9, plate="KDB O76A")
	check("look-alike read at dock = same visit", "seen again" in str(r3.get("result")), r3)
	check("last seen moved to dock", frappe.db.get_value("CCTV Vehicle Visit", visit, "last_seen_camera") == cam["Dock"])

	r4 = simulator.simulate(cam["Gate Out"], "plate_read", at="2026-11-12 10:47:00", confidence=0.93, plate="KDB076A", direction="out")
	v.reload()
	check("exit closes visit", v.status == "Departed", v.status)
	check("time inside = 145 min", v.total_minutes == 145, v.total_minutes)

	r5 = simulator.simulate(cam["Gate In"], "plate_read", at="2026-11-12 08:40:00", confidence=0.91, plate="KDN 050F", direction="in")
	item = frappe.db.get_value("CCTV Review Item", {"plate": "KDN 050F"}, ["reason", "name"], as_dict=True)
	check("pending appointment -> Arrived Before Approval review", item and item.reason == "Arrived Before Approval", item)

	r6 = simulator.simulate(cam["Gate In"], "plate_read", at="2026-11-12 11:00:00", confidence=0.97, plate="KZZ 111Q", direction="in")
	check("unknown plate -> review Unmatched", frappe.db.get_value("CCTV Review Item", {"plate": "KZZ 111Q"}, "reason") == "Unmatched")
	al = frappe.db.get_value("CCTV Alert", {"plate": "KZZ 111Q", "alert_type": "Unregistered Vehicle"}, ["name", "clip_start", "clip_end", "event_time"], as_dict=True)
	check("unknown plate -> Unregistered Vehicle alert", bool(al))
	if al:
		check("clip window = -15s/+60s", (al.event_time - al.clip_start).seconds == 15 and (al.clip_end - al.event_time).seconds == 60, al)

	r7 = simulator.simulate(cam["Gate In"], "plate_read", at="2026-11-12 12:00:00", confidence=0.95, plate="KXX 999Z", direction="in")
	check("watchlisted plate -> Critical alert", frappe.db.get_value("CCTV Alert", {"plate": "KXX 999Z", "alert_type": "Watchlisted Vehicle"}, "severity") == "Critical")
	check("watchlist activity recorded", frappe.db.exists("Watchlist Activity", {"watchlist": wl.name}))

	r8 = simulator.simulate(cam["Gate In"], "plate_read", at="2026-11-12 12:10:00", confidence=0.3, plate="KAB 222C", direction="in")
	check("low-confidence read ignored", frappe.db.get_value("CCTV Vehicle Sighting", {"event": r8["event"]}, "match_status") == "Ignored", r8)

	print("zones")
	z1 = simulator.simulate(cam["Cold Room Door"], "person_detected", at="2026-11-12 21:15:32", confidence=0.9)
	check("person in cold room at 21:15 -> forbidden-hours alert", z1.get("result") == "Entry in Forbidden Hours", z1)
	z2 = simulator.simulate(cam["Cold Room Door"], "person_detected", at="2026-11-12 10:00:00", confidence=0.9)
	check("person in cold room at 10:00 -> allowed", z2.get("result") == "allowed", z2)
	z3 = simulator.simulate(cam["Cold Room Door"], "person_detected", at="2026-11-12 21:16:00", confidence=0.9)
	n = frappe.db.count("CCTV Alert", {"camera": cam["Cold Room Door"], "alert_type": "Entry in Forbidden Hours"})
	check("repeat within debounce -> same alert", n == 1, n)

	print("ingest")
	from upande_security.cctv.ingest import store_event
	env = {"event_id": "DUP-TEST-1", "camera": cam["Gate In"], "event_type": "motion", "event_time": "2026-11-12T08:00:00Z"}
	s1 = store_event(env)
	s2 = store_event(env)
	check("event_id idempotent", s1[0] == "accepted" and s2[0] == "duplicate", (s1, s2))
	check("UTC -> site time (+3h)", str(frappe.db.get_value("CCTV Event", {"event_id": "DUP-TEST-1"}, "event_time")) == "2026-11-12 11:00:00")
	check("other site's camera refused", store_event({**env, "event_id": "X2"}, farm="Karen")[0] == "rejected")
	check("unknown type stored as other", frappe.db.get_value("CCTV Event", store_event({**env, "event_id": "X3", "event_type": "new_thing"})[1], "event_type") == "other")

	print("tokens")
	t = tokens.get_live_token(cam["Gate In"])
	claims = tokens.verify(t["token"], "test-secret-123")
	check("live token signed and scoped", claims["cam"] == cam["Gate In"] and claims["scope"] == "live")
	check("live view logged", frappe.db.exists("CCTV Live View Log", {"token_id": claims["jti"]}))
	alert_name = frappe.db.get_value("CCTV Alert", {"camera": cam["Cold Room Door"]})
	p = tokens.get_playback_session(alert=alert_name)
	check("playback cued 15s in", p["event_offset_seconds"] == 15, p)
	check("playback path carries the UTC range", "/20261112T181517Z_20261112T181632Z" in p["path"], p["path"])
	check("playback logged", frappe.db.exists("CCTV Playback Log", {"alert": alert_name}))

	print("escalation")
	frappe.db.set_value("CCTV Alert", alert_name, "next_escalation_at", "2026-01-01 00:00:00")
	alerts.escalate_due()
	a = frappe.get_doc("CCTV Alert", alert_name)
	check("unacknowledged alert escalates", a.status == "Escalated" and a.escalation_level == 1, (a.status, a.escalation_level))
	alerts.acknowledge(alert_name)
	check("acknowledge stops escalation", frappe.db.get_value("CCTV Alert", alert_name, "next_escalation_at") is None)
	inc = alerts.create_incident(alert_name)["incident"]
	check("incident created from alert", frappe.db.exists("Incident Report", inc))
	frappe.delete_doc("Incident Report", inc, ignore_permissions=True, force=True)

	print("review")
	from upande_security.cctv import vehicles
	ri = frappe.db.get_value("CCTV Review Item", {"plate": "KDN 050F"})
	vehicles.resolve_review_item(ri, "Linked", "Appointment", "APMT-Marius-1293355")
	check("review resolved and visit confirmed", frappe.db.get_value("CCTV Vehicle Visit", frappe.db.get_value("CCTV Review Item", ri, "vehicle_visit"), "guard_confirmed") == 1)
	check("live vehicles board lists on-site", any(x.plate == "KDN 050F" for x in vehicles.get_live_vehicles(FARM)))

finally:
	frappe.db.rollback()
	simulator.clear_demo()
	for n in frappe.get_all("CCTV Event", filters={"event_id": ["in", ["DUP-TEST-1", "X3"]]}, pluck="name"):
		frappe.delete_doc("CCTV Event", n, force=True, ignore_permissions=True)
	for n in frappe.get_all("Watchlist Activity", filters={"watchlist": wl.name}, pluck="name"):
		frappe.delete_doc("Watchlist Activity", n, force=True, ignore_permissions=True)
	frappe.delete_doc("Security Watchlist", wl.name, force=True, ignore_permissions=True)
	for n in frappe.get_all("Notification Log", filters={"document_type": ["in", ["CCTV Alert", "CCTV Review Item"]]}, pluck="name"):
		frappe.delete_doc("Notification Log", n, force=True, ignore_permissions=True)
	for k, v in orig.items():
		frappe.db.set_single_value("CCTV Settings", k, 0)  # tests always leave the module OFF
	frappe.db.set_single_value("CCTV Settings", "gateway_jwt_secret", None)
	frappe.db.set_single_value("Security Ops Settings", "feature_cctv", 0)
	frappe.db.commit()
	print(f"\n{ok} passed, {fail} failed. Demo data removed, switches restored.")
