"""Guards on patrol vs camera alerts. Uses the DEMO cold-room camera (seeds the
demo if missing), restores everything it changes, removes what it creates.

	cd ~/frappe-bench/sites && ../env/bin/python ../apps/upande_security/upande_security/cctv/tests/guard_check.py
"""

import atexit

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

frappe.init(site="mysite.local", sites_path=".")
frappe.connect()
frappe.set_user("Administrator")

from upande_security.cctv import guard_match, settings, simulator  # noqa: E402

FARM = "Kapkolia"
ok = fail = 0
made = {"gps": [], "scans": [], "checkpoints": []}
state = {}


def check(label, cond, extra=""):
	global ok, fail
	ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
	print("  PASS" if cond else "  FAIL", label, "" if cond else extra)


ops_before = frappe.db.get_single_value("Security Ops Settings", "feature_cctv")
sw_before = {k: frappe.db.get_single_value("CCTV Settings", k) for k in ("enabled", "alerts_enabled")}
demo_existed = bool(frappe.db.get_value("CCTV Camera", {"camera_name": "DEMO Cold Room Door"}))
frappe.db.set_single_value("Security Ops Settings", "feature_cctv", 1)
for k in ("enabled", "alerts_enabled"):
	frappe.db.set_single_value("CCTV Settings", k, 1)
settings.clear()
demo = simulator.seed_demo(FARM)
cam = demo["cameras"]["Cold Room Door"]
zone = demo["zone"]
state["cam"] = frappe.db.get_value("CCTV Camera", cam, ["latitude", "longitude", "checkpoint"], as_dict=True)
zone_doc = frappe.get_doc("Security Zone", zone)
state["rules"] = [r.as_dict() for r in zone_doc.access_rules]
start = now_datetime()


@atexit.register
def cleanup():
	frappe.db.rollback()
	for n in made["gps"]:
		frappe.db.delete("Patrol GPS Log", {"name": n})
	for n in made["scans"]:
		frappe.db.delete("Checkpoint Scan Log", {"name": n})
	frappe.db.set_value("CCTV Camera", cam, {"latitude": state["cam"].latitude, "longitude": state["cam"].longitude, "checkpoint": state["cam"].checkpoint})
	for n in made["checkpoints"]:
		frappe.db.delete("Security Checkpoint", {"name": n})
	z = frappe.get_doc("Security Zone", zone)
	z.set("access_rules", [{k: v for k, v in r.items() if k not in ("name", "parent", "parentfield", "parenttype", "idx")} for r in state["rules"]])
	z.flags.ignore_permissions = True
	z.save()
	for dt in ("CCTV Alert", "CCTV Person Sighting", "CCTV Event"):
		field = "event_time" if dt != "CCTV Person Sighting" else "sighting_time"
		if dt == "CCTV Event":
			field = "received_at"
		for n in frappe.get_all(dt, filters={"camera": cam, field if dt != "CCTV Event" else "received_at": [">=", start]}, pluck="name"):
			frappe.delete_doc(dt, n, ignore_permissions=True, force=True, delete_permanently=True)
	for n in frappe.get_all("CCTV Track", filters={"creation": [">=", start]}, pluck="name"):
		frappe.delete_doc("CCTV Track", n, ignore_permissions=True, force=True)
	for n in state.get("parked", []):
		key = frappe.db.get_value("CCTV Alert", n, ["alert_type", "farm", "zone", "camera"], as_dict=True)
		if key:
			frappe.db.set_value("CCTV Alert", n, "debounce_key", "|".join(str(x or "") for x in (key.alert_type, key.farm, key.zone or key.camera, "unknown")))
	if not demo_existed:
		simulator.clear_demo()
	frappe.db.set_single_value("Security Ops Settings", "feature_cctv", ops_before or 0)
	for k, v in sw_before.items():
		frappe.db.set_single_value("CCTV Settings", k, v or 0)
	frappe.db.commit()
	print(f"\n{ok} passed, {fail} failed. Restored and cleaned up.")


guards = frappe.get_all("Security Guard", filters={"status": "Active"}, fields=["name", "full_name"], limit=2)
G1, G2 = guards[0], guards[1]
LAT, LNG = -0.5000, 35.2000
frappe.db.set_value("CCTV Camera", cam, {"latitude": LAT, "longitude": LNG})
zone_doc.append("access_rules", {"effect": "Allow", "applies_to": "Security Guard", "security_guard": G1.name, "days": "All Days", "note": "test"})
zone_doc.flags.ignore_permissions = True
zone_doc.save()
frappe.db.commit()
night = lambda m: add_to_date(start.replace(hour=22, minute=0, second=0, microsecond=0), minutes=m)  # noqa: E731


def gps(guard, when, d_lat=0.0001):  # ~11 m north of the camera
	doc = frappe.get_doc({"doctype": "Patrol GPS Log", "farm": FARM, "captured_at": when, "latitude": str(LAT + d_lat), "longitude": str(LNG),
		"gps_accuracy": "8", "tracking_mode": "On Duty", "personel": "External Guard", "external_guard": guard, "patrol": "TEST-PATROL"})
	doc.insert(ignore_permissions=True)
	made["gps"].append(doc.name)
	return doc


def person(at):
	return simulator.simulate(cam, "person_detected", at=str(at), confidence=0.9)


def alert_for(r):
	"""The alert an event produced - or the open one it was merged into (debounce)."""
	return frappe.db.get_value("CCTV Alert", {"source_event": r.get("event")}) or frappe.get_all("CCTV Alert",
		filters={"camera": cam, "alert_type": r.get("result")}, order_by="modified desc", pluck="name", limit=1)[0]


print("guard on patrol")
gps(G1.name, night(0))
r = person(add_to_date(night(0), seconds=20))
check("cleared guard near the camera -> no alert", r.get("result") == "guard on patrol", r)
s = frappe.db.get_value("CCTV Person Sighting", {"event": r.get("event")}, ["identified_by", "security_guard", "distance_m"], as_dict=True)
check("pass kept as patrol proof (GPS, distance)", s and s.identified_by == "Guard GPS" and s.security_guard == G1.name and s.distance_m < 15, s)

gps(G2.name, night(10))
r = person(add_to_date(night(10), seconds=15))
a = frappe.db.get_value("CCTV Alert", {"source_event": r.get("event")}, ["alert_type", "guard_name", "hold_until"], as_dict=True)
check("guard not cleared for the zone -> Unauthorized Person naming them", r.get("result") == "Unauthorized Person" and a and a.guard_name == G2.full_name, (r, a))
check("a named guard's alert is not held", a and not a.hold_until)

gps(G1.name, night(20), d_lat=0.01)  # ~1.1 km away: not at the camera
# start from a clean slate for this camera's unidentified alerts (no merging into older ones)
for n in frappe.get_all("CCTV Alert", filters={"camera": cam, "status": "Open", "alert_type": "Entry in Forbidden Hours", "creation": ["<", start]}, pluck="name"):
	frappe.db.set_value("CCTV Alert", n, "debounce_key", f"parked:{n}")
	state.setdefault("parked", []).append(n)
r = person(night(20))
held = frappe.get_doc("CCTV Alert", alert_for(r))
check("nobody near -> alert held, no one told yet", held.hold_until and not held.notifications, (held.hold_until, len(held.notifications)))
gps(G1.name, add_to_date(night(20), seconds=40))  # the late GPS point arrives
held.reload()
check("late guard GPS clears the held alert", held.status == "False Alarm" and held.guard_name == G1.full_name and not held.notifications,
	(held.status, held.guard_name, held.resolution_notes))

r = person(night(40))
a = alert_for(r)
frappe.db.set_value("CCTV Alert", a, "hold_until", add_to_date(now_datetime(), seconds=-1))
guard_match.release_held()
d = frappe.get_doc("CCTV Alert", a)
check("no guard by the end of the hold -> released and notified", d.status == "Open" and not d.hold_until and len(d.notifications) > 0,
	(d.status, d.hold_until, len(d.notifications)))

print("checkpoint scan")
cp = frappe.get_doc("Security Checkpoint", frappe.get_all("Security Checkpoint", pluck="name", limit=1)[0])  # an existing one, linked temporarily
frappe.db.set_value("CCTV Camera", cam, {"latitude": 0, "longitude": 0, "checkpoint": cp.name})
scan = frappe.get_doc({"doctype": "Checkpoint Scan Log", "checkpoint": cp.name, "result": "Valid", "scanned_at": night(60), "personel": "External Guard",
	"external_guard": G1.name, "farm": FARM, "patrol": "TEST-PATROL"})
scan.flags.ignore_mandatory = True
scan.insert(ignore_permissions=True)
made["scans"].append(scan.name)
r = person(add_to_date(night(60), seconds=30))
s = frappe.db.get_value("CCTV Person Sighting", {"event": r.get("event")}, "identified_by")
check("checkpoint scan at the camera identifies the guard", r.get("result") == "guard on patrol" and s == "Checkpoint Scan", (r, s))

print("patrol side")
rows = guard_match.patrol_sightings(patrol="TEST-PATROL")
check("patrol lists its camera passes", len(rows) >= 2 and all(x.guard_name for x in rows), [(x.camera_name, x.identified_by) for x in rows])
from frappe.desk.query_report import run  # noqa: E402
out = run("CCTV Guard Patrol Verification", filters={"from_date": str(start.date()), "to_date": str(start.date()), "farm": FARM})
summ = {s["label"]: s["value"] for s in out["report_summary"]}
check("verification report counts passes and false alarms avoided", summ.get("Guard passes", 0) >= 2 and summ.get("False alarms avoided", 0) >= 1, summ)
frappe.db.commit()
