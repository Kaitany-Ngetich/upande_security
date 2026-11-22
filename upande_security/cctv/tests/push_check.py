"""Direct Push end to end, over HTTP against the RUNNING bench (port 8000).
Creates a Hikvision and a Dahua recorder in Direct Push mode with one camera
each, posts real-shaped alarms, checks what was stored, then removes it all
and restores the switches.

	cd ~/frappe-bench/sites && ../env/bin/python ../apps/upande_security/upande_security/cctv/tests/push_check.py
"""

import atexit
import time

import frappe
import requests
from frappe.utils import now_datetime

frappe.init(site="mysite.local", sites_path=".")
frappe.connect()
frappe.set_user("Administrator")

from upande_security.cctv import push, settings  # noqa: E402

BASE, HOST = "http://127.0.0.1:8000", "mysite.local"
FARM = "Kapkolia"
ok = fail = 0
made = {"servers": [], "cameras": []}
start = now_datetime()
before = {k: frappe.db.get_single_value("CCTV Settings", k) for k in ("enabled", "push_enabled")}
ops_before = frappe.db.get_single_value("Security Ops Settings", "feature_cctv")


def check(label, cond, extra=""):
	global ok, fail
	ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
	print("  PASS" if cond else "  FAIL", label, "" if cond else extra)


@atexit.register
def cleanup():
	frappe.db.rollback()
	time.sleep(3)  # let the worker finish what it was given
	cams = made["cameras"] or ["-"]
	events = frappe.get_all("CCTV Event", filters={"camera": ["in", cams]}, pluck="name")
	sightings = frappe.get_all("CCTV Vehicle Sighting", filters={"camera": ["in", cams]}, pluck="name")
	meta = frappe.get_meta("CCTV Review Item")
	for f in ("event", "sighting", "vehicle_sighting"):
		if meta.has_field(f):
			for n in frappe.get_all("CCTV Review Item", filters={f: ["in", (events + sightings) or ["-"]]}, pluck="name"):
				frappe.delete_doc("CCTV Review Item", n, force=True, ignore_permissions=True)
	for n in frappe.get_all("CCTV Vehicle Visit", or_filters={"entry_camera": ["in", cams], "exit_camera": ["in", cams],
			"last_seen_camera": ["in", cams]}, pluck="name"):
		frappe.delete_doc("CCTV Vehicle Visit", n, force=True, ignore_permissions=True)
	for dt in ("CCTV Alert", "CCTV Person Sighting", "CCTV Vehicle Sighting", "CCTV Event"):
		for n in frappe.get_all(dt, filters={"camera": ["in", cams]}, pluck="name"):
			frappe.delete_doc(dt, n, force=True, ignore_permissions=True, delete_permanently=True)
	for n in frappe.get_all("File", filters={"creation": [">=", start], "folder": "Home/Attachments", "is_private": 1,
			"attached_to_doctype": ["is", "not set"], "file_name": ["like", "%Picture%"]}, pluck="name"):
		frappe.delete_doc("File", n, force=True, ignore_permissions=True)
	for n in made["cameras"]:
		frappe.delete_doc("CCTV Camera", n, force=True, ignore_permissions=True)
	for n in made["servers"]:
		frappe.delete_doc("CCTV Server", n, force=True, ignore_permissions=True)
	for k, v in before.items():
		frappe.db.set_single_value("CCTV Settings", k, v or 0)
	frappe.db.set_single_value("Security Ops Settings", "feature_cctv", ops_before or 0)
	frappe.db.commit()
	frappe.clear_cache()
	print(f"\n{ok} passed, {fail} failed. Removed test recorders/cameras/events, switches restored.")


frappe.db.set_single_value("Security Ops Settings", "feature_cctv", 1)
frappe.db.set_single_value("CCTV Settings", "enabled", 1)
frappe.db.set_single_value("CCTV Settings", "push_enabled", 1)


def recorder(brand):
	sv = frappe.get_doc({"doctype": "CCTV Server", "server_name": f"TEST PUSH {brand}", "farm": FARM, "brand": brand,
		"connection": "Direct Push"}).insert(ignore_permissions=True)
	made["servers"].append(sv.name)
	cam = frappe.get_doc({"doctype": "CCTV Camera", "camera_code": f"TPUSH-{brand[:3].upper()}-01", "camera_name": f"TEST push {brand} gate",
		"server": sv.name, "farm": FARM, "channel_no": 1, "role": "Gate", "enabled": 1}).insert(ignore_permissions=True)
	made["cameras"].append(cam.name)
	return sv.name, cam.name


hik, hik_cam = recorder("Hikvision")
dah, dah_cam = recorder("Dahua")
link_h = push.generate_push_link(hik)
link_d = push.generate_push_link(dah)
frappe.db.commit()
frappe.clear_cache()


def post(link, **kw):
	path = link["url"].split("://", 1)[1].split("/", 1)[1]
	return requests.post(f"{BASE}/{path}", headers={"Host": HOST, **kw.pop("headers", {})}, timeout=20, **kw)


def events(cam):
	frappe.db.rollback()
	return frappe.get_all("CCTV Event", filters={"camera": cam}, fields=["name", "event_type", "plate_normalized", "direction", "snapshot", "provider", "confidence"],
		order_by="creation asc")


ANPR = b"""<?xml version="1.0" encoding="UTF-8"?>
<EventNotificationAlert version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<ipAddress>192.168.1.64</ipAddress><channelID>1</channelID><dateTime>2026-11-22T10:15:02+03:00</dateTime>
<activePostCount>1</activePostCount><eventType>ANPR</eventType><eventState>active</eventState>
<ANPR><country>3</country><licensePlate>KDE220M</licensePlate><confidenceLevel>93</confidenceLevel><direction>forward</direction>
<vehicleType>vehicle</vehicleType></ANPR></EventNotificationAlert>"""
def _jpeg():
	import io

	from PIL import Image

	buf = io.BytesIO()
	Image.new("RGB", (64, 48), (90, 120, 160)).save(buf, "JPEG")
	return buf.getvalue()


JPEG = _jpeg()
BAD_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64

print("hikvision")
r = post(link_h, files=[("anpr.xml", ("anpr.xml", ANPR, "application/xml")),
	("licensePlatePicture.jpg", ("licensePlatePicture.jpg", JPEG, "image/jpeg")),
	("detectionPicture.jpg", ("detectionPicture.jpg", JPEG, "image/jpeg"))])
ev = events(hik_cam)
check("ANPR multipart -> 1 plate read", r.status_code == 200 and r.json()["message"]["accepted"] == 1 and len(ev) == 1
	and ev[0].event_type == "plate_read" and ev[0].plate_normalized == "KDE220M" and ev[0].direction == "in", (r.status_code, r.text[:200], ev))
check("scene picture kept as the snapshot", ev and ev[0].snapshot and "detectionPicture" in ev[0].snapshot, ev and ev[0].snapshot)
r = post(link_h, files=[("anpr.xml", ("anpr.xml", ANPR, "application/xml")), ("detectionPicture.jpg", ("detectionPicture.jpg", JPEG, "image/jpeg"))])
check("recorder retry -> stored once", r.status_code == 200 and r.json()["message"]["accepted"] == 0 and len(events(hik_cam)) == 1, r.text[:200])

r = post(link_h, files=[("anpr.xml", ("anpr.xml", ANPR.replace(b"10:15:02", b"10:15:30"), "application/xml")),
	("detectionPicture.jpg", ("detectionPicture.jpg", BAD_JPEG, "image/jpeg"))])
check("broken picture -> alarm still stored, without picture", r.status_code == 200 and r.json()["message"]["accepted"] == 1
	and not events(hik_cam)[-1].snapshot, r.text[:200])

LINE = ANPR.replace(b"<eventType>ANPR</eventType>", b"<eventType>linedetection</eventType>").replace(b"10:15:02", b"10:16:40").split(b"<ANPR>")[0] + \
	b"<DetectionRegionList><DetectionRegionEntry><regionID>1</regionID><detectionTarget>human</detectionTarget></DetectionRegionEntry></DetectionRegionList></EventNotificationAlert>"
r = post(link_h, data=LINE, headers={"Content-Type": "application/xml"})
check("plain XML line crossing", r.status_code == 200 and [e.event_type for e in events(hik_cam)][-1:] == ["line_crossing"], r.text[:200])

HB = b"<EventNotificationAlert><channelID>1</channelID><dateTime>2026-11-22T10:17:00+03:00</dateTime><eventType>videoloss</eventType><eventState>inactive</eventState></EventNotificationAlert>"
n = len(events(hik_cam))
r = post(link_h, data=HB, headers={"Content-Type": "application/xml"})
note = frappe.db.get_value("CCTV Server", hik, ["status", "last_push_at", "last_push_note"], as_dict=True)
check("heartbeat: nothing stored, recorder marked Online", r.status_code == 200 and len(events(hik_cam)) == n and note.status == "Online" and note.last_push_at, note)
r = post(link_h, data=ANPR.replace(b"<channelID>1</channelID>", b"<channelID>9</channelID>"), headers={"Content-Type": "application/xml"})
check("channel with no camera set up -> ignored", r.status_code == 200 and len(events(hik_cam)) == n, r.text[:200])

print("dahua")
TEXT = "Code=CrossLineDetection;action=Start;index=0;data={\"UTC\": 1795850000, \"Direction\": \"LeftToRight\", \"Name\": \"Gate line\", \"Object\": {\"ObjectType\": \"Human\"}}"
r = post(link_d, data=TEXT, headers={"Content-Type": "text/plain"})
check("eventManager text -> line crossing", r.status_code == 200 and [e.event_type for e in events(dah_cam)] == ["line_crossing"], r.text[:200])
JS = {"Events": [{"Code": "TrafficJunction", "Action": "Pulse", "Index": 0, "Data": {"UTC": 1795850100,
	"TrafficCar": {"PlateNumber": "KDA 123A", "Confidence": 88, "Direction": "Approach"}}}]}
r = post(link_d, json=JS)
ev = events(dah_cam)
check("JSON ANPR -> plate read", r.status_code == 200 and ev[-1].event_type == "plate_read" and ev[-1].plate_normalized == "KDA123A", (r.text[:200], ev[-1:]))

print("refusals")
r = requests.post(f"{BASE}{push.ENDPOINT}?t=" + "x" * 43, data=ANPR, headers={"Host": HOST, "Content-Type": "application/xml"}, timeout=20)
check("wrong secret -> 401, nothing stored", r.status_code == 401, r.status_code)
old = dict(link_h)
link_h2 = push.generate_push_link(hik)
frappe.db.commit()
r = post(old, data=LINE, headers={"Content-Type": "application/xml"})
check("old link stops working after a new one", r.status_code == 401, r.status_code)
frappe.db.set_single_value("CCTV Settings", "push_enabled", 0)
frappe.db.commit()
frappe.clear_cache()
r = post(link_h2, data=LINE, headers={"Content-Type": "application/xml"})
check("Direct Push switched off -> 403", r.status_code == 403, r.status_code)
frappe.db.set_single_value("CCTV Settings", "push_enabled", 1)
frappe.db.set_value("CCTV Server", hik, "connection", "Site Agent")
frappe.db.commit()
r = post(link_h2, data=LINE, headers={"Content-Type": "application/xml"})
check("recorder moved to Site Agent -> its link is dead", r.status_code == 401, r.status_code)

print("site agent")
names = [s.name for s in frappe.get_all("CCTV Server", filters={"farm": FARM, "connection": ["!=", "Direct Push"]})]
check("agent config leaves Direct Push recorders out", dah not in names and hik in names, names)
