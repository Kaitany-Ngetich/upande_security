"""Second-round CCTV checks: Ops flag, licences, agent commands (through Frappe's
WSGI app with real signed requests), faces behind the legal gate, presence and
cross-camera tracks, delivery fallback, parking/dock reports, site map.
Needs Redis. Leaves CCTV switched off and removes everything it made.

	cd ~/frappe-bench/sites && ../env/bin/python ../apps/upande_security/upande_security/cctv/tests/round2_check.py
"""

import atexit
import base64
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "cctv_agent"))

import frappe  # noqa: E402
import frappe.app  # noqa: E402
from werkzeug.test import Client  # noqa: E402

SITE, FARM, AGENT_USER = "mysite.local", "Kapkolia", "cctv-agent-r2@example.com"
ok = fail = 0
made = {"profiles": [], "links": [], "rules": [], "files": []}


def check(label, cond, extra=""):
	global ok, fail
	ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
	print("  PASS" if cond else "  FAIL", label, "" if cond else extra)


def connect():
	frappe.init(site=SITE, sites_path=".")
	frappe.connect()
	frappe.set_user("Administrator")


connect()
from upande_security.cctv import alerts, commands, dashboard, presence, settings, simulator, tracking  # noqa: E402

SWITCHES = ("enabled", "live_view_enabled", "alerts_enabled", "anpr_enabled", "presence_enabled", "face_recognition_enabled")


@atexit.register
def cleanup():
	try:
		if not getattr(frappe.local, "db", None):
			connect()
		frappe.db.rollback()
		for dt, key in (("CCTV Camera Link", "links"), ("CCTV Alert Rule", "rules"), ("CCTV Person Profile", "profiles")):
			for n in made[key]:
				frappe.delete_doc(dt, n, ignore_permissions=True, force=True)
		for dt in ("CCTV Track", "CCTV Person Sighting", "CCTV Agent Command"):
			for n in frappe.get_all(dt, pluck="name"):
				frappe.delete_doc(dt, n, ignore_permissions=True, force=True, delete_permanently=True)
		for f in made["files"]:
			if frappe.db.exists("File", f):
				frappe.delete_doc("File", f, ignore_permissions=True, force=True)
		simulator.clear_demo()
		for n in frappe.get_all("CCTV Camera", filters={"camera_name": ["like", "WIZ %"]}, pluck="name"):
			frappe.delete_doc("CCTV Camera", n, ignore_permissions=True, force=True)
		if frappe.db.exists("User", AGENT_USER):
			frappe.delete_doc("User", AGENT_USER, ignore_permissions=True, force=True)
		s = frappe.get_single("CCTV Settings")
		s.set("entitlements", [])
		s.enforce_entitlements = 0
		s.legal_approval_reference = None
		s.flags.ignore_permissions = True
		s.save()
		frappe.db.sql("update `tabSingles` set value='0' where doctype='CCTV Settings' and field in %s", (SWITCHES,))
		frappe.db.set_single_value("Security Ops Settings", "feature_cctv", 0)
		frappe.db.commit()
		print(f"\n{ok} passed, {fail} failed. Cleaned up, CCTV switched off.")
	except Exception as e:
		print("cleanup failed:", e)


def switch(**kw):
	for k, v in kw.items():
		frappe.db.set_single_value("CCTV Settings", k, v)
	settings.clear()


# ---------------------------------------------------------------- Ops flag
print("ops flag")
frappe.db.set_single_value("Security Ops Settings", "feature_cctv", 0)
switch(enabled=1, alerts_enabled=1, anpr_enabled=1, live_view_enabled=1)
check("CCTV Settings on but Ops flag off -> CCTV off", not settings.is_on("enabled"))
from upande_security.api.feature_flags import get_enabled_features
if hasattr(frappe.local, "security_feature_flags"):
	del frappe.local.security_feature_flags
check("feature_cctv reads OFF while unset/0", get_enabled_features()["feature_cctv"] is False)
frappe.db.set_single_value("Security Ops Settings", "feature_cctv", 1)
settings.clear()
check("Ops flag on -> CCTV on", settings.is_on("enabled"))

demo = simulator.seed_demo(FARM)
cam = demo["cameras"]
frappe.db.commit()

# ---------------------------------------------------------------- licences
print("licences")
s = frappe.get_single("CCTV Settings")
s.enforce_entitlements = 1
s.set("entitlements", [{"farm": FARM, "core": 1, "vehicles": 0, "presence": 1, "ai_engine": 0, "max_cameras": 5}])
s.flags.ignore_permissions = True
s.save()
settings.clear()
r = simulator.simulate(cam["Gate In"], "plate_read", confidence=0.95, plate="KDB 076A", direction="in")
check("vehicles not licensed -> plate read not processed", "not licensed" in str(r.get("result")), r)
from upande_security.cctv.ingest import store_event
st = store_event({"event_id": "LIC-1", "camera": cam["Gate In"], "event_type": "motion", "event_time": "2026-11-21T08:00:00Z",
	"source": {"provider": "own_engine"}})
check("own-engine event refused without AI licence", st == ("rejected", "site not licensed for the AI engine"), st)
try:
	frappe.get_doc({"doctype": "CCTV Camera", "camera_name": "WIZ extra", "server": demo["server"], "channel_no": 9}).insert()
	frappe.get_doc({"doctype": "CCTV Camera", "camera_name": "WIZ extra2", "server": demo["server"], "channel_no": 10}).insert()
	check("camera limit enforced (5 per licence)", False)
except frappe.ValidationError as e:
	check("camera limit enforced (5 per licence)", "allows 5 cameras" in str(e), e)
frappe.db.rollback()
s = frappe.get_single("CCTV Settings")
s.set("entitlements", [{"farm": FARM, "core": 1, "vehicles": 1, "presence": 1, "ai_engine": 1, "max_cameras": 0}])
s.flags.ignore_permissions = True
s.save()
settings.clear()

# ---------------------------------------------------------------- agent commands via WSGI
print("agent commands (signed, through Frappe)")
from cctv_agent.erp import ERP  # noqa: E402

hmac_secret = frappe.get_doc("CCTV Site Agent", demo["agent"]).get_password("hmac_secret")
if not frappe.db.exists("User", AGENT_USER):
	frappe.get_doc({"doctype": "User", "email": AGENT_USER, "first_name": "Agent R2", "send_welcome_email": 0, "user_type": "System User",
		"roles": [{"role": "CCTV Agent"}]}).insert(ignore_permissions=True)
u = frappe.get_doc("User", AGENT_USER)
key, secret = frappe.generate_hash(length=15), frappe.generate_hash(length=15)
u.api_key, u.api_secret = key, secret
u.save(ignore_permissions=True)
disc = commands.discover(demo["server"])["command"]
a_name = alerts.raise_alert("Unknown Person", camera=cam["Cold Room Door"], summary="r2 test", force=True)
ev_cmd = commands.request_evidence(a_name)["command"]
frappe.db.commit()
frappe.destroy()

erp = ERP(f"http://{SITE}", key, secret, demo["agent"], hmac_secret)
wsgi = Client(frappe.app.application)


def send(path, method="GET", **kw):
	req = erp._sign(erp.client.build_request(method, erp.url + path, **kw))
	headers = {k: v for k, v in req.headers.items() if k.lower() not in ("host", "content-length")}
	r = wsgi.open(req.url.raw_path.decode(), method=method, data=req.content if method != "GET" else None, headers={**headers, "Host": SITE})
	return r.status_code, json.loads(r.data) if r.data[:1] == b"{" else r.data


C = "/api/method/upande_security.cctv.commands."
code, body = send(C + "poll_commands")
cmds = {c["command"]: c for c in body["message"]["commands"]} if code == 200 else {}
check("agent polls its queued commands", {"discover_channels", "export_clip"} <= set(cmds), (code, str(body)[:300]))
check("export_clip carries the UTC range", cmds.get("export_clip", {}).get("payload", {}).get("start_utc", "").endswith("Z"))
code, body = send(C + "command_result", "POST", json={"command": cmds["discover_channels"]["id"], "status": "done",
	"result": {"channels": [{"channel_no": 7, "name": "WIZ Gate 7", "main_stream": "701", "sub_stream": "702"},
		{"channel_no": 8, "name": "WIZ Dock 8"}]}})
check("discovery result accepted", code == 200, (code, str(body)[:200]))
clip = b"\x00\x00\x00\x18ftypmp42" + os.urandom(4096)
code, body = send(C + "upload_command_file", "POST", params={"command": cmds["export_clip"]["id"], "filename": "evidence.mp4"},
	content=clip, headers={"Content-Type": "application/octet-stream"})
check("evidence clip uploaded as signed raw body", code == 200 and body["message"]["file_url"].startswith("/private/files/"), (code, str(body)[:300]))
code, body = send(C + "command_result", "POST", json={"command": cmds["export_clip"]["id"], "status": "done", "result": {"seconds": 75}})
connect()
a = frappe.get_doc("CCTV Alert", a_name)
check("alert now holds the evidence clip", a.evidence_exported and a.evidence_file and a.evidence_file.startswith("/private/"), (a.evidence_exported, a.evidence_file))
made["files"] += frappe.get_all("File", filters={"attached_to_name": a_name}, pluck="name")
res = commands.create_cameras(demo["server"], frappe.get_value("CCTV Agent Command", cmds["discover_channels"]["id"], "result") and
	json.loads(frappe.db.get_value("CCTV Agent Command", cmds["discover_channels"]["id"], "result"))["channels"])
check("wizard creates the discovered cameras", len(res["created"]) == 2, res)

# ---------------------------------------------------------------- faces (legal gate)
print("faces and presence")
switch(presence_enabled=1, face_recognition_enabled=1)
check("face switch alone does nothing without a legal reference", not settings.is_on("face_recognition_enabled"))
s = frappe.get_single("CCTV Settings")
s.legal_approval_reference = "DPIA-2026-TEST"
s.flags.ignore_permissions = True
s.save()
settings.clear()
check("with the legal reference faces are on", settings.is_on("face_recognition_enabled"))
img = frappe.get_doc({"doctype": "File", "file_name": "face1.jpg", "content": base64.b64decode(
	"/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="), "is_private": 1}).insert(ignore_permissions=True)
consent = frappe.get_doc({"doctype": "File", "file_name": "consent.txt", "content": b"signed consent (test)", "is_private": 1}).insert(ignore_permissions=True)
made["files"] += [img.name, consent.name]
emp = frappe.get_all("Employee", filters={"company": frappe.db.get_value("Farm", FARM, "company")}, pluck="name", limit=1)
p = frappe.get_doc({"doctype": "CCTV Person Profile", "person_type": "Employee", "full_name": "R2 Test Person", "employee": emp[0] if emp else None,
	"status": "Active", "consent_status": "Pending", "face_images": [{"image": img.file_url}]}).insert(ignore_permissions=True)
made["profiles"].append(p.name)
try:
	presence.enroll(p.name, [FARM])
	check("enrolment refused without consent", False)
except frappe.ValidationError:
	check("enrolment refused without consent", True)
p.consent_status, p.consent_document, p.consent_date = "Given", consent.file_url, frappe.utils.today()
p.save(ignore_permissions=True)
q = presence.enroll(p.name, [FARM])
cmd = frappe.get_doc("CCTV Agent Command", q["commands"][0])
check("enrolment queued for the site agent", cmd.command == "enroll_face" and cmd.status == "Queued")
cmd.db_set("status", "Sent")
from upande_security.cctv import ingest as ingest_mod  # noqa: E402
ingest_mod._agent = lambda: frappe.get_doc("CCTV Site Agent", demo["agent"])
got = commands.fetch_face_image(cmd.name, 0)
check("agent can fetch the private enrolment image only through its command", base64.b64decode(got["content"])[:2] == b"\xff\xd8")
commands.command_result(cmd.name, "done", {"embedding_ref": "agent:" + p.name, "quality": [0.93]})
p.reload()
check("profile marked enrolled at the site", p.face_enrolled and FARM in (p.enrolled_sites or ""), (p.face_enrolled, p.enrolled_sites))
r = simulator.simulate(cam["Cold Room Door"], "face_match", at=f"{frappe.utils.today()} 21:10:00", confidence=0.91, person_ref=p.name, similarity=0.91)
check("enrolled face at the cold room after hours -> Unauthorized Person", r.get("result") == "Unauthorized Person", r)
pres = presence.get_presence(farm=FARM)
check("presence lists the person with zone", any(x["person_profile"] == p.name for x in pres["people"]), pres)
check("named person has a track", frappe.db.exists("CCTV Track", {"person_profile": p.name, "status": "Active"}))
low = simulator.simulate(cam["Cold Room Door"], "face_match", at=f"{frappe.utils.today()} 21:12:00", confidence=0.4, person_ref=p.name, similarity=0.4)
check("face match below threshold treated as unknown", low.get("result") == "Entry in Forbidden Hours", low)

# ---------------------------------------------------------------- anonymous tracks
print("cross-camera tracks")
lk = frappe.get_doc({"doctype": "CCTV Camera Link", "from_camera": cam["Gate In"], "to_camera": cam["Dock"], "min_seconds": 5, "max_seconds": 120}).insert(ignore_permissions=True)
made["links"].append(lk.name)
day = frappe.utils.today()
simulator.simulate(cam["Gate In"], "person_detected", at=f"{day} 10:00:00", confidence=0.9, track_id="t1")
simulator.simulate(cam["Dock"], "person_detected", at=f"{day} 10:00:40", confidence=0.9, track_id="t9")
s1 = frappe.get_all("CCTV Person Sighting", filters={"person_profile": ["is", "not set"], "sighting_time": ["between", [f"{day} 10:00:00", f"{day} 10:00:59"]]},
	fields=["camera", "track"], order_by="sighting_time asc")
check("walk gate -> dock in 40 s joins one track", len(s1) == 2 and s1[0].track == s1[1].track, s1)
simulator.simulate(cam["Dock"], "person_detected", at=f"{day} 10:30:00", confidence=0.9, track_id="t10")
late = frappe.db.get_value("CCTV Person Sighting", {"sighting_time": f"{day} 10:30:00"}, "track")
check("same camera pair 30 min later starts a new track", late and late != s1[0].track)
trail = tracking.track_trail(s1[0].track)
check("track trail lists both cameras in order", [t.camera for t in trail] == [cam["Gate In"], cam["Dock"]])

# ---------------------------------------------------------------- delivery fallback
print("delivery")
user = frappe.get_all("User", filters={"enabled": 1, "user_type": "System User", "name": ["not in", ["Administrator", "Guest"]]}, pluck="name", limit=1)
rule = frappe.get_doc({"doctype": "CCTV Alert Rule", "rule_name": "R2 SMS test", "trigger_type": "Camera Tamper", "severity": "Medium",
	"recipients": [{"recipient_type": "User", "user": (user or ["Administrator"])[0], "channel": "Telegram"}]}).insert(ignore_permissions=True)
made["rules"].append(rule.name)
an = alerts.raise_alert("Camera Tamper", camera=cam["Dock"], summary="r2 delivery", force=True, subject_key="r2")
rows = frappe.get_doc("CCTV Alert", an).notifications
check("unconfigured Telegram falls back to on-screen and says why", rows and rows[0].channel == "Telegram -> On Screen" and "not configured" in (rows[0].error or ""),
	[(r.channel, r.delivery_status, r.error) for r in rows])

# ---------------------------------------------------------------- reports, map
print("reports and map")
from frappe.desk.query_report import run  # noqa: E402
for rep in ("CCTV Parking Activity", "CCTV Dock Turnaround"):
	try:
		run(rep, filters={"from_date": frappe.utils.add_days(day, -1), "to_date": day})
		check(f"{rep} runs", True)
	except Exception as e:
		check(f"{rep} runs", False, e)
m = dashboard.map_data(farm=FARM)
check("site map data returns cameras and placement count", len(m["cameras"]) >= 4 and m["unplaced"] >= 4, {k: (len(v) if isinstance(v, list) else v) for k, v in m.items()})
tl = presence.person_timeline(profile=p.name)
check("person timeline returns today's sightings", len(tl) >= 1)

print("withdrawal and erase")
w = presence.withdraw_consent(p.name, "test")
check("withdrawal queues face removal at the site", len(w["commands"]) == 1)
e = presence.erase_person(p.name)
p.reload()
check("erase anonymises the profile and deletes sightings", p.full_name == "(erased)" and e["sightings_deleted"] >= 1, (p.full_name, e))
frappe.db.commit()
