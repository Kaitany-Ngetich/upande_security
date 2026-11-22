# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Guards on patrol, seen by cameras.

A camera that sees a person cannot tell a patrolling guard from an intruder.
The Security app can: on-duty guards report GPS (Patrol GPS Log) and scan
checkpoints (Checkpoint Scan Log). So before a camera event becomes an alert:

	1. find the on-duty guard who was at that camera at that moment
	   - a GPS point within CCTV Settings > Guard Match Distance of the
	     camera's position (latitude/longitude), inside the time window, or
	   - a valid scan of the checkpoint linked to the camera (CCTV Camera >
	     Patrol Checkpoint), inside the time window;
	2. if found, the person IS that guard: the zone's own Access Rules decide
	   (a rule "Allow - Security Guard X" or "Allow - Role Security Guard"),
	   so a cleared guard raises no alert, and an uncleared one raises
	   "Unauthorized Person" naming the guard;
	3. the pass is kept as a CCTV Person Sighting (identified by Guard GPS /
	   Checkpoint Scan) - proof of the patrol, with footage to match.

LATE GPS
Phones batch and resend GPS when the signal returns. An alert for an
unidentified person is therefore HELD (Hold Unidentified-Person Alerts) before
anyone is told. A guard GPS point or checkpoint scan arriving meanwhile (the
after_insert hooks below) clears it on the spot as "Guard on patrol"; if none
comes, the scheduler releases it and the normal notifications go out.
"""

import math

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from upande_security.cctv.settings import get_settings, is_on


def enabled():
	return is_on("enabled") and bool(get_settings().patrol_link_enabled)


def _distance_m(lat1, lon1, lat2, lon2):
	r = 6371000.0
	p1, p2 = math.radians(lat1), math.radians(lat2)
	dp, dl = p2 - p1, math.radians(lon2 - lon1)
	a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
	return 2 * r * math.asin(math.sqrt(a))


def _camera(name):
	return frappe.db.get_value("CCTV Camera", name, ["name", "camera_name", "farm", "zone", "latitude", "longitude", "checkpoint"], as_dict=True)


def _guard_label(internal, external):
	if external:
		return frappe.db.get_value("Security Guard", external, "full_name") or external
	if internal:
		return frappe.db.get_value("Employee", internal, "employee_name") or internal
	return None


def find_guard(camera, when):
	"""The on-duty guard at this camera around `when`, or None.
	{employee, security_guard, name, source, distance_m, seconds_off, patrol}"""
	s = get_settings()
	cam = _camera(camera) if isinstance(camera, str) else camera
	if not cam:
		return None
	when = get_datetime(when)
	lo, hi = add_to_date(when, seconds=-s.guard_match_window_seconds), add_to_date(when, seconds=s.guard_match_window_seconds)
	best = None

	if cam.checkpoint:
		for r in frappe.get_all("Checkpoint Scan Log", filters={"checkpoint": cam.checkpoint, "result": "Valid",
				"scanned_at": ["between", [lo, hi]]}, fields=["internal_guard", "external_guard", "scanned_at", "patrol", "distance_m"]):
			off = abs((get_datetime(r.scanned_at) - when).total_seconds())
			if not best or off < best["seconds_off"]:
				best = {"employee": r.internal_guard, "security_guard": r.external_guard, "source": "Checkpoint Scan",
					"distance_m": r.distance_m, "seconds_off": off, "patrol": r.patrol}

	if cam.latitude and cam.longitude:
		radius = s.guard_match_radius_m
		for r in frappe.get_all("Patrol GPS Log", filters={"farm": cam.farm, "captured_at": ["between", [lo, hi]]},
				fields=["internal_guard", "external_guard", "captured_at", "latitude", "longitude", "gps_accuracy", "patrol"], limit=2000):
			try:
				d = _distance_m(float(cam.latitude), float(cam.longitude), float(r.latitude), float(r.longitude))
				acc = min(float(r.gps_accuracy or 0), 50.0)  # a vague fix may still count, within reason
			except (TypeError, ValueError):
				continue
			if d > radius + acc:
				continue
			off = abs((get_datetime(r.captured_at) - when).total_seconds())
			score = d + off  # metres and seconds weigh about the same at walking pace
			if not best or (best["source"] != "Checkpoint Scan" and score < best["distance_m"] + best["seconds_off"]):
				best = {"employee": r.internal_guard, "security_guard": r.external_guard, "source": "Guard GPS",
					"distance_m": round(d, 1), "seconds_off": off, "patrol": r.patrol}
	if best:
		best["name"] = _guard_label(best["employee"], best["security_guard"])
	return best


def person_for(guard):
	"""Shape api.zones.is_allowed expects, so the zone's rules decide."""
	user = None
	if guard.get("security_guard"):
		user = frappe.db.get_value("Security Guard", guard["security_guard"], "user")
	elif guard.get("employee"):
		user = frappe.db.get_value("Employee", guard["employee"], "user_id")
	return {"employee": guard.get("employee"), "security_guard": guard.get("security_guard"), "user": user}


def record_pass(ev, cam, guard, when):
	"""The guard's pass, kept as patrol proof (and on the guard's track)."""
	doc = frappe.get_doc({"doctype": "CCTV Person Sighting", "sighting_time": when, "camera": cam.name, "farm": cam.farm,
		"zone": cam.zone, "source": "Camera Native" if ev is None or ev.provider != "own_engine" else "Own Engine",
		"confidence": ev.confidence if ev is not None else None, "snapshot": ev.snapshot if ev is not None else None,
		"event": ev.name if ev is not None else None, "identified_by": guard["source"], "security_guard": guard.get("security_guard"),
		"employee": guard.get("employee"), "guard_name": guard.get("name"), "distance_m": guard.get("distance_m"),
		"patrol": guard.get("patrol"), "track_id": f"guard:{guard.get('security_guard') or guard.get('employee')}"})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.insert()
	return doc.name


# ------------------------------------------------------------------ held alerts

def _clear_held(alert, guard, why):
	doc = frappe.get_doc("CCTV Alert", alert)
	doc.update({"status": "False Alarm", "false_alarm_reason": "Authorised Person", "hold_until": None, "next_escalation_at": None,
		"security_guard": guard.get("security_guard"), "guard_employee": guard.get("employee"), "guard_name": guard.get("name"),
		"resolved_at": now_datetime(), "resolution_notes": why})
	doc.flags.ignore_permissions = True
	doc.save()


def recheck_held(alert):
	"""Look again for a guard behind a held alert. True if it was cleared."""
	a = frappe.db.get_value("CCTV Alert", alert, ["name", "camera", "zone", "event_time", "status", "hold_until"], as_dict=True)
	if not a or not a.hold_until or a.status != "Open":
		return False
	guard = find_guard(a.camera, a.event_time)
	if not guard:
		return False
	from upande_security.api.zones import is_allowed

	if a.zone and not is_allowed(a.zone, person_for(guard), get_datetime(a.event_time)):
		# A guard, but not cleared for this zone: name them on the alert and let it go out.
		frappe.db.set_value("CCTV Alert", a.name, {"alert_type": "Unauthorized Person", "security_guard": guard.get("security_guard"),
			"guard_employee": guard.get("employee"), "guard_name": guard.get("name"), "person_name": guard.get("name"),
			"summary": f"Guard {guard.get('name')} seen in {a.zone}, not cleared for it at this time."})
		return False
	cam = _camera(a.camera)
	record_pass(None, cam, guard, a.event_time)
	_clear_held(a.name, guard, f"Guard {guard.get('name')} on patrol ({guard['source']}, {guard.get('distance_m') or '-'} m, "
		f"{int(guard['seconds_off'])} s) - cleared before anyone was notified.")
	return True


def release_held():
	"""Scheduler: held alerts past their hold time - a last look for a guard, then notify."""
	if not is_on("enabled"):
		return
	from upande_security.cctv.alerts import notify

	for name in frappe.get_all("CCTV Alert", filters={"status": "Open", "hold_until": ["<=", now_datetime()]}, pluck="name", limit=200):
		if recheck_held(name):
			continue
		doc = frappe.get_doc("CCTV Alert", name)
		doc.hold_until = None
		rule = frappe.get_cached_doc("CCTV Alert Rule", doc.rule) if doc.rule else None
		notify(doc, rule)


def on_guard_position(doc, method=None):
	"""Patrol GPS Log / Checkpoint Scan Log after_insert: clear held alerts this guard explains."""
	try:
		if not enabled():
			return
		farm = doc.get("farm")
		held = frappe.get_all("CCTV Alert", filters={"status": "Open", "hold_until": ["is", "set"], **({"farm": farm} if farm else {})},
			pluck="name", limit=50)
		for name in held:
			recheck_held(name)
	except Exception:
		frappe.log_error(title="CCTV guard match on position failed")


# ------------------------------------------------------------------ patrol side

@frappe.whitelist()
def patrol_sightings(patrol=None, guard=None, from_time=None, to_time=None):
	"""Camera passes for a patrol (or a guard over a time range) - proof of patrol."""
	if not set(frappe.get_roles()) & {"System Manager", "Security Head", "Security Manager", "Security Supervisor", "CCTV Operator"}:
		frappe.throw("Not permitted.", frappe.PermissionError)
	filters = {"identified_by": ["in", ["Guard GPS", "Checkpoint Scan"]]}
	if patrol:
		filters["patrol"] = patrol
	if guard:
		filters["security_guard" if frappe.db.exists("Security Guard", guard) else "employee"] = guard
	if from_time and to_time:
		filters["sighting_time"] = ["between", [from_time, to_time]]
	rows = frappe.get_all("CCTV Person Sighting", filters=filters,
		fields=["name", "sighting_time", "camera", "zone", "farm", "guard_name", "identified_by", "distance_m", "patrol"],
		order_by="sighting_time asc", limit=1000)
	names = dict(frappe.get_all("CCTV Camera", filters={"name": ["in", [r.camera for r in rows] or ["-"]]}, fields=["name", "camera_name"], as_list=True))
	for r in rows:
		r.camera_name = names.get(r.camera)
	return rows
