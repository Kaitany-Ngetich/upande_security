# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Zone, people and device events -> alerts.

WHO MAY BE IN A ZONE
The Security Zone and its Access Rules (api/zones.py) already answer "may
this person be here now?" for guards' GPS. Camera events ask the same
question, so they use the same answer: a cold room set to Deny with an
"Allow Anyone, Mon-Sat 06:00-18:00" rule raises an alert for a person seen
there at 21:00, with no CCTV-specific schedule to keep in step.

DETECTION IS NOT ENTRY
A camera seeing someone near a door is not proof the door opened. The alert
summary says "seen", and a door sensor or access event, when there is one,
is what turns it into an entry.
"""

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from upande_security.cctv.alerts import find_rule, raise_alert
from upande_security.cctv.settings import get_settings, is_on, site_allows

ENTRY_EVENTS = {"person_detected", "line_crossing", "zone_intrusion", "face_match", "face_unknown", "access_event", "door_state"}


def _camera(name):
	return frappe.db.get_value("CCTV Camera", name, ["name", "camera_name", "farm", "zone", "role"], as_dict=True) or frappe._dict()


def _identity(ev, data):
	"""(employee, person_profile, display name) when the event names someone."""
	profile = None
	employee = data.get("employee")
	name = data.get("person_name")
	if ev.event_type == "face_match" and data.get("person_ref") and is_on("face_recognition_enabled"):
		# Below the face match threshold the person counts as unknown.
		similarity = float(data.get("similarity") or (ev.confidence or 0) / 100)
		ok = similarity * 100 >= get_settings().face_match_threshold
		profile = data.get("person_ref") if ok and frappe.db.get_value("CCTV Person Profile", data.get("person_ref"), "status") == "Active" else None
		if profile:
			employee, name = frappe.db.get_value("CCTV Person Profile", profile, ["employee", "full_name"]) or (None, None)
	if employee and not name:
		name = frappe.db.get_value("Employee", employee, "employee_name")
	return employee, profile, name


def handle_zone_event(ev):
	data = frappe._dict(ev.get("payload_dict") or {})
	cam = _camera(ev.camera)
	when = get_datetime(ev.event_time)
	et = ev.event_type

	if et == "line_crossing" and (data.get("direction") or ev.direction) == "out":
		return "exit crossing"
	if et == "door_state" and (data.get("state") or "").lower() != "open":
		return "door closed"
	if et == "access_event" and (data.get("result") or "").lower() == "denied":
		raise_alert("Unauthorized Person", camera=ev.camera, zone=cam.zone, farm=cam.farm, event_time=when, source_event=ev.name,
			summary=f"Access denied at reader {data.get('reader_id') or ''}.", snapshot=ev.snapshot, subject_key=data.get("credential_ref"))
		return "access denied"

	employee, profile, name = _identity(ev, data)
	if et in ("person_detected", "face_match", "face_unknown") and is_on("presence_enabled") and site_allows(cam.farm, "presence"):
		_person_sighting(ev, cam, profile, data, when)

	if et == "zone_intrusion" and data.get("dwell_seconds"):
		rule = find_rule("Dwell Exceeded", cam.farm, cam.zone, ev.camera)
		if rule and rule.threshold_minutes and float(data.dwell_seconds) > rule.threshold_minutes * 60:
			raise_alert("Dwell Exceeded", camera=ev.camera, zone=cam.zone, farm=cam.farm, event_time=when, source_event=ev.name,
				person_name=name, person_profile=profile, snapshot=ev.snapshot,
				summary=f"{name or 'A person'} has been in {cam.zone} for {int(float(data.dwell_seconds) // 60)} minutes.")

	if not cam.zone:
		return "no zone"
	from upande_security.api.zones import is_allowed

	if is_allowed(cam.zone, {"employee": employee} if employee else {}, when):
		return "allowed"
	if employee or profile:
		trigger = "Unauthorized Person"
		summary = f"{name or employee} seen in {cam.zone}, not allowed there at this time."
	elif et == "face_unknown":
		trigger = "Unknown Person"
		summary = f"Unrecognised person seen in {cam.zone}."
	else:
		trigger = "Entry in Forbidden Hours"
		summary = ("Door opened" if et == "door_state" else "Person seen") + f" in {cam.zone} outside its allowed hours."
	raise_alert(trigger, camera=ev.camera, zone=cam.zone, farm=cam.farm, event_time=when, source_event=ev.name,
		person_name=name, person_profile=profile, confidence=ev.confidence, snapshot=ev.snapshot, summary=summary,
		subject_key=employee or profile or "unknown")
	return trigger


def _person_sighting(ev, cam, profile, data, when):
	doc = frappe.get_doc({"doctype": "CCTV Person Sighting", "person_profile": profile, "track_id": data.get("track_id"),
		"sighting_time": when, "direction": data.get("direction") or ev.direction or "", "camera": ev.camera, "farm": cam.farm,
		"zone": cam.zone, "source": "Own Engine" if ev.provider == "own_engine" else "Camera Native",
		"confidence": ev.confidence, "snapshot": ev.snapshot, "event": ev.name})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.insert()
	try:
		from upande_security.cctv.tracking import attach

		attach(doc)
	except Exception:
		frappe.log_error(title="CCTV tracking failed")


def handle_device_event(ev):
	data = frappe._dict(ev.get("payload_dict") or {})
	cam = _camera(ev.camera)
	when = get_datetime(ev.event_time)
	if ev.event_type == "camera_status":
		state = (data.get("state") or "").lower()
		frappe.db.set_value("CCTV Camera", ev.camera, {"status": "Online" if state == "online" else "Offline",
			**({"last_frame_time": when} if state == "online" else {})})
		return state
	trigger = {"tamper": "Camera Tamper", "video_loss": "Video Loss", "recording_gap": "Recording Gap"}[ev.event_type]
	raise_alert(trigger, camera=ev.camera, zone=cam.zone, farm=cam.farm, event_time=when, source_event=ev.name,
		snapshot=ev.snapshot, summary=f"{cam.camera_name}: {trigger.lower()}" + (f" ({data.get('kind')})" if data.get("kind") else ""))
	return trigger


# ------------------------------------------------------------------ scheduled state checks

def check_states():
	"""Every minute: conditions no single event raises - a door left open, a
	camera or a site agent gone quiet."""
	if not is_on("enabled"):
		return
	_doors_left_open()
	_offline_devices()


def _doors_left_open():
	now = now_datetime()
	for rule in frappe.get_all("CCTV Alert Rule", filters={"enabled": 1, "trigger_type": "Door Open Too Long"},
			fields=["name", "camera", "zone", "farm", "threshold_minutes"]):
		limit = rule.threshold_minutes or 5
		filters = {"event_type": "door_state", "event_time": [">=", add_to_date(now, hours=-12)]}
		if rule.camera:
			filters["camera"] = rule.camera
		elif rule.zone:
			filters["camera"] = ["in", frappe.get_all("CCTV Camera", filters={"zone": rule.zone}, pluck="name") or ["-"]]
		latest = {}
		for e in frappe.get_all("CCTV Event", filters=filters, fields=["name", "camera", "event_time", "payload"], order_by="event_time asc"):
			payload = frappe.parse_json(e.payload or "{}") or {}
			door = (payload.get("data") or {}).get("door_id") or e.camera
			latest[door] = (e, ((payload.get("data") or {}).get("state") or "").lower())
		for door, (e, state) in latest.items():
			if state == "open" and get_datetime(e.event_time) < add_to_date(now, minutes=-limit):
				raise_alert("Door Open Too Long", camera=e.camera, event_time=e.event_time, source_event=e.name, subject_key=door,
					summary=f"Door {door} open for more than {limit} minutes.")


def _offline_devices():
	now = now_datetime()
	cam_limit = 5
	for c in frappe.get_all("CCTV Camera", filters={"enabled": 1, "status": "Online", "last_frame_time": ["<", add_to_date(now, minutes=-cam_limit)]},
			fields=["name", "camera_name", "farm", "zone"]):
		frappe.db.set_value("CCTV Camera", c.name, "status", "Offline")
		raise_alert("Camera Offline", camera=c.name, farm=c.farm, zone=c.zone, subject_key=c.name,
			summary=f"{c.camera_name}: no frames for {cam_limit}+ minutes.")
	for a in frappe.get_all("CCTV Site Agent", filters={"status": "Online", "last_heartbeat": ["<", add_to_date(now, minutes=-2)]},
			fields=["name", "farm"]):
		frappe.db.set_value("CCTV Site Agent", a.name, "status", "Offline")
		raise_alert("Agent Offline", farm=a.farm, subject_key=a.name,
			summary=f"Site agent {a.name} stopped reporting. Events are buffered on site until it reconnects.")
