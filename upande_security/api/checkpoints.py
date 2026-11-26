# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Patrol checkpoints: printed QR codes guards scan on patrol, accepted only
at the checkpoint itself.

A QR alone proves nothing - anyone can photograph one and scan the photo
from the guard hut. So every scan carries the phone's GPS fix, and counts
only within the checkpoint's fence: radius_m (3 m by default) plus an
allowance for the accuracy the phone itself reports, capped so a vague fix
cannot stretch the fence across a farm. A fix too vague to judge is refused
outright, and so is a position Android reports as coming from a mock
location app.

The positions themselves are set on site, from the app, by a System Manager
or Security Head standing at each checkpoint (set_checkpoint_position): a
typed or map-picked position is routinely 5-20 m off, which a 3 m fence
cannot tolerate.

Every attempt - accepted or not - is one Checkpoint Scan Log row. Too Far,
Fake GPS and unknown codes are also raised as Unauthorized Access Attempts.

WHICH CHECKPOINTS A PATROL GETS (patrol_plan)
A route assigned to the guard, else one of their farm's active routes, else
every active checkpoint on the farm - only those with a position set. The
order is shuffled per patrol when
the route says so, seeded by the patrol tag: the same patrol always sees the
same order (the app can reload), the next patrol a different one. Any scan
order counts; the plan's order is recorded beside the actual one so a
supervisor can see who walked the same loop every night.
"""

import hashlib
import random
import urllib.parse

import frappe
from frappe import _

from upande_security.api.feature_flags import is_feature_enabled
from upande_security.api.security_alerts import log_unauthorized_access
from upande_security.api.sos_alert import _haversine_m

LOG = "Checkpoint Scan Log"
CHECKPOINT = "Security Checkpoint"
VALID = "Valid"

#: Readings worse than this are not used when setting a position.
SETUP_MAX_ACCURACY_M = 20
#: Fewest usable readings that make a position.
SETUP_MIN_READINGS = 3

_SETUP_ROLES = ("System Manager", "Security Head")


def _settings():
	s = frappe.db.get_value(
		"Security Ops Settings",
		"Security Ops Settings",
		["checkpoint_accuracy_allowance_m", "checkpoint_max_accuracy_m"],
		as_dict=True,
	) or {}
	allowance = s.get("checkpoint_accuracy_allowance_m")
	max_acc = s.get("checkpoint_max_accuracy_m")
	return {
		"allowance": 7 if allowance is None else max(0, frappe.utils.cint(allowance)),
		"max_accuracy": 15 if max_acc is None else max(1, frappe.utils.cint(max_acc)),
	}


def _checkpoint_name_from_scan(raw):
	"""CP-00012 from whatever the camera read: the label's URL (any host,
	/app/ or /desk/) or a bare name typed in by hand."""
	raw = (raw or "").strip()
	for marker in ("/app/security-checkpoint/", "/desk/security-checkpoint/"):
		if marker in raw:
			raw = raw.split(marker, 1)[1]
			for sep in ("?", "#", "/"):
				raw = raw.split(sep, 1)[0]
			return urllib.parse.unquote(raw).strip()
	return raw


def _scanner():
	"""(personel, internal_guard, external_guard) - the same identity the
	asset scans use."""
	from upande_security.api.security_api import _asset_scanner

	personel, internal_guard, external_guard, _farm, _company = _asset_scanner()
	return personel, internal_guard, external_guard


def _guard_farm(personel, internal_guard, external_guard):
	"""The guard's Active shift's farm, else the farm on their own record -
	the rule submit_patrol_points uses for their GPS points."""
	if personel == "Internal Guard" and internal_guard:
		return frappe.db.get_value(
			"Security Guard Shift Assignment", {"internal_guard": internal_guard, "status": "Active"}, "farm"
		) or frappe.db.get_value("Employee", internal_guard, "custom_farm")
	if personel == "External Guard" and external_guard:
		return frappe.db.get_value(
			"Security Guard Shift Assignment", {"external_guard": external_guard, "status": "Active"}, "farm"
		) or frappe.db.get_value("Security Guard", external_guard, "farm")
	return None


def _seeded(patrol):
	"""A random source fixed by the patrol tag."""
	return random.Random(int(hashlib.sha1((patrol or "").encode()).hexdigest()[:12], 16))


def patrol_plan(patrol, personel, internal_guard, external_guard):
	"""(route name or None, farm, [checkpoint names in this patrol's order])."""
	farm = _guard_farm(personel, internal_guard, external_guard)
	rng = _seeded(patrol)

	route = None
	guard_route = None
	if personel == "Internal Guard" and internal_guard:
		guard_route = {"internal_guard": internal_guard}
	elif personel == "External Guard" and external_guard:
		guard_route = {"external_guard": external_guard}
	if guard_route:
		route = frappe.db.get_value("Patrol Route", dict(guard_route, active=1), "name", order_by="modified desc")
	if not route and farm:
		farm_routes = frappe.get_all(
			"Patrol Route",
			filters={"farm": farm, "active": 1, "internal_guard": ["is", "not set"], "external_guard": ["is", "not set"]},
			pluck="name",
			order_by="name asc",
		)
		if farm_routes:
			route = rng.choice(farm_routes)

	# Only checkpoints a guard can actually scan: active, with a position set.
	# One still waiting for its position would otherwise show as missed on
	# every patrol until someone stood at it with the app.
	scannable = {"active": 1, "latitude": ["!=", 0], "longitude": ["!=", 0]}

	if route:
		doc = frappe.get_doc("Patrol Route", route)
		farm = doc.farm
		active = set(
			frappe.get_all(CHECKPOINT, filters=dict(scannable, name=["in", [r.checkpoint for r in doc.checkpoints] or [""]]), pluck="name")
		)
		order = [r.checkpoint for r in doc.checkpoints if r.checkpoint in active]
		if doc.shuffle:
			rng.shuffle(order)
		return route, farm, order

	if not farm:
		return None, None, []
	order = frappe.get_all(CHECKPOINT, filters=dict(scannable, farm=farm), pluck="name", order_by="name asc")
	rng.shuffle(order)
	return None, farm, order


def _progress(patrol, order):
	"""{checkpoint: first valid scan time} for this patrol."""
	if not patrol:
		return {}
	done = {}
	for r in frappe.get_all(
		LOG,
		filters={"patrol": patrol, "result": VALID},
		fields=["checkpoint", "scanned_at"],
		order_by="scanned_at asc",
	):
		done.setdefault(r.checkpoint, r.scanned_at)
	return done


def _plan_response(patrol, route, farm, order, done):
	info = {
		c.name: c
		for c in frappe.get_all(
			CHECKPOINT,
			filters={"name": ["in", order or [""]]},
			fields=["name", "checkpoint_name", "location_hint", "latitude", "longitude"],
		)
	}
	checkpoints = []
	for i, name in enumerate(order, start=1):
		c = info.get(name) or {}
		checkpoints.append(
			{
				"checkpoint": name,
				"checkpoint_name": c.get("checkpoint_name") or name,
				"location_hint": c.get("location_hint"),
				"position": i,
				"has_position": bool(c.get("latitude") and c.get("longitude")),
				"scanned": name in done,
				"scanned_at": str(done[name]) if name in done else None,
			}
		)
	return {
		"patrol": patrol,
		"route": route,
		"farm": farm,
		"checkpoints": checkpoints,
		"done": sum(1 for c in checkpoints if c["scanned"]),
		"total": len(checkpoints),
	}


@frappe.whitelist()
def get_patrol_checkpoints(patrol=None):
	"""This patrol's checkpoints in its own order, each marked scanned or not."""
	try:
		if not is_feature_enabled("feature_checkpoint_scanning"):
			return {"error": "Checkpoint scanning is not enabled on this instance."}
		patrol = (patrol or "").strip()
		personel, internal_guard, external_guard = _scanner()
		route, farm, order = patrol_plan(patrol, personel, internal_guard, external_guard)
		return _plan_response(patrol, route, farm, order, _progress(patrol, order))
	except Exception as e:
		frappe.log_error("get_patrol_checkpoints", frappe.get_traceback())
		return {"error": str(e)}


def _guard_name(internal_guard, external_guard):
	if internal_guard:
		return frappe.db.get_value("Employee", internal_guard, "employee_name") or internal_guard
	if external_guard:
		return frappe.db.get_value("Security Guard", external_guard, "full_name") or external_guard
	return None


def _log(result, checkpoint, code, latitude, longitude, accuracy, mocked, patrol, **extra):
	personel, internal_guard, external_guard = _scanner()
	log = frappe.new_doc(LOG)
	log.update(
		{
			"checkpoint": checkpoint.name if checkpoint else None,
			"checkpoint_name": checkpoint.checkpoint_name if checkpoint else None,
			"result": result,
			"scanned_at": frappe.utils.now_datetime(),
			"scanned_by": frappe.session.user,
			"personel": personel,
			"internal_guard": internal_guard,
			"external_guard": external_guard,
			# Shown in the list - a guard code alone means nothing to a reader.
			"guard_name": _guard_name(internal_guard, external_guard) or frappe.session.user,
			"farm": checkpoint.farm if checkpoint else None,
			"company": checkpoint.company if checkpoint else None,
			"patrol": patrol or None,
			"latitude": latitude,
			"longitude": longitude,
			"gps_accuracy": accuracy,
			"mocked": 1 if mocked else 0,
			"scanned_code": (code or "")[:140],
		}
	)
	log.update(extra)
	log.flags.ignore_links = True
	log.insert(ignore_permissions=True)
	return log


def _raise(kind, checkpoint, code, detail):
	"""Best-effort; log_unauthorized_access never raises."""
	log_unauthorized_access(
		kind,
		checkpoint.name if checkpoint else code,
		detail,
		checkpoint.company if checkpoint else None,
		checkpoint.farm if checkpoint else None,
	)


@frappe.whitelist()
def scan_checkpoint(code=None, latitude=None, longitude=None, accuracy=None, mocked=0, patrol=None):
	"""Guard scans a checkpoint's QR on patrol, with the phone's GPS fix.

	Always answers with `accepted` and a `message` for the guard rather than
	an error, so the app can say why a scan did not count; only a missing
	feature or missing GPS is an error. A refused scan is still logged.
	"""
	try:
		if not is_feature_enabled("feature_checkpoint_scanning"):
			return {"error": "Checkpoint scanning is not enabled on this instance."}
		if latitude in (None, "") or longitude in (None, ""):
			return {"error": "Your location is needed to record a checkpoint scan."}

		code = (code or "").strip()
		patrol = (patrol or "").strip()
		lat, lng = frappe.utils.flt(latitude), frappe.utils.flt(longitude)
		acc = frappe.utils.flt(accuracy) if accuracy not in (None, "") else None
		mocked = frappe.utils.cint(mocked) or (str(mocked).lower() == "true")
		gps = (code, lat, lng, acc, mocked, patrol)

		name = _checkpoint_name_from_scan(code)
		checkpoint = frappe.db.get_value(
			CHECKPOINT,
			name,
			["name", "checkpoint_name", "farm", "company", "latitude", "longitude", "radius_m", "active"],
			as_dict=True,
		) if name else None

		def refuse(result, message, **extra):
			_log(result, checkpoint, *gps, **extra)
			frappe.db.commit()
			return {"accepted": False, "result": result, "message": message,
					"checkpoint_name": checkpoint.checkpoint_name if checkpoint else None, **extra}

		if not checkpoint:
			_raise("Invalid Checkpoint Scan", None, code, "Scanned code '" + code + "' is not a Security Checkpoint.")
			return refuse("Unknown Code", "This QR code is not a patrol checkpoint.")
		if not checkpoint.active:
			return refuse("Inactive Checkpoint", checkpoint.checkpoint_name + " is no longer in use - tell your supervisor.")
		if mocked:
			_raise("Invalid Checkpoint Scan", checkpoint, code,
				"Checkpoint " + checkpoint.checkpoint_name + " scanned with a fake (mock) GPS location.")
			return refuse("Fake GPS", "Your phone is using a fake location. Turn off any location-changing app and scan again.")
		if not (checkpoint.latitude and checkpoint.longitude):
			return refuse("Position Not Set", checkpoint.checkpoint_name + " has no position yet - ask your supervisor to set it.")

		settings = _settings()
		distance = _haversine_m(lat, lng, checkpoint.latitude, checkpoint.longitude)
		if acc is None or acc > settings["max_accuracy"]:
			return refuse(
				"Poor GPS",
				"GPS is too weak here ({0}). Step into the open, wait a few seconds and scan again.".format(
					"unknown accuracy" if acc is None else "±{0:.0f} m".format(acc)
				),
				distance_m=round(distance, 1),
			)
		allowed = (checkpoint.radius_m or 3) + min(acc, settings["allowance"])
		if distance > allowed:
			_raise("Invalid Checkpoint Scan", checkpoint, code,
				"Checkpoint {0} scanned {1:.0f} m away (allowed {2:.0f} m) - possibly a photo of the QR.".format(
					checkpoint.checkpoint_name, distance, allowed))
			return refuse(
				"Too Far",
				"You are {0:.0f} m from {1}. Scan the QR at the checkpoint itself.".format(distance, checkpoint.checkpoint_name),
				distance_m=round(distance, 1), allowed_m=round(allowed, 1),
			)

		personel, internal_guard, external_guard = _scanner()
		route, farm, order = patrol_plan(patrol, personel, internal_guard, external_guard)
		done = _progress(patrol, order)
		planned = order.index(checkpoint.name) + 1 if checkpoint.name in order else None
		scan_position = len(done) + (0 if checkpoint.name in done else 1)
		_log(
			VALID, checkpoint, *gps,
			distance_m=round(distance, 1), allowed_m=round(allowed, 1), patrol_route=route,
			planned_position=planned, scan_position=scan_position,
		)
		frappe.db.commit()
		done.setdefault(checkpoint.name, frappe.utils.now_datetime())
		plan = _plan_response(patrol, route, farm, order, done)
		return {
			"accepted": True,
			"result": VALID,
			"message": "{0} recorded ({1:.0f} m).".format(checkpoint.checkpoint_name, distance),
			"checkpoint_name": checkpoint.checkpoint_name,
			"distance_m": round(distance, 1),
			"allowed_m": round(allowed, 1),
			"on_plan": planned is not None,
			"plan": plan,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("scan_checkpoint", frappe.get_traceback())
		return {"error": str(e)}


@frappe.whitelist()
def list_checkpoints_for_setup(farm=None):
	"""Active checkpoints and whether each has a position yet - for the
	app's Set position screen."""
	try:
		_require_setup_role()
		filters = {"active": 1}
		if farm:
			filters["farm"] = farm
		rows = frappe.get_all(
			CHECKPOINT,
			filters=filters,
			fields=["name", "checkpoint_name", "farm", "location_hint", "latitude", "longitude",
					"position_accuracy_m", "position_set_at", "radius_m"],
			order_by="farm asc, checkpoint_name asc",
			limit_page_length=1000,
		)
		return {
			"checkpoints": [
				{
					"checkpoint": r.name,
					"checkpoint_name": r.checkpoint_name,
					"farm": r.farm,
					"location_hint": r.location_hint,
					"has_position": bool(r.latitude and r.longitude),
					"position_accuracy_m": r.position_accuracy_m,
					"position_set_at": str(r.position_set_at) if r.position_set_at else None,
					"radius_m": r.radius_m,
				}
				for r in rows
			]
		}
	except Exception as e:
		return {"error": str(e)}


def _require_setup_role():
	if not any(r in frappe.get_roles() for r in _SETUP_ROLES):
		frappe.throw(_("Only a System Manager or Security Head can set checkpoint positions."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def set_checkpoint_position(code=None, readings=None, mocked=0):
	"""Set a checkpoint's position from GPS readings taken standing at it.

	readings: [{latitude, longitude, accuracy}, ...] collected by the app over
	several seconds. Readings worse than SETUP_MAX_ACCURACY_M are dropped; the
	rest are averaged weighted by 1/accuracy^2, so one sharp fix counts for
	more than several vague ones.
	"""
	try:
		_require_setup_role()
		if frappe.utils.cint(mocked) or str(mocked).lower() == "true":
			return {"error": "Your phone is using a fake location - a position cannot be set from it."}
		name = _checkpoint_name_from_scan(code)
		if not name or not frappe.db.exists(CHECKPOINT, name):
			return {"error": "This QR code is not a patrol checkpoint."}

		parsed = frappe.parse_json(readings) if isinstance(readings, str) else (readings or [])
		usable = []
		for r in parsed or []:
			try:
				lat, lng, acc = float(r.get("latitude")), float(r.get("longitude")), float(r.get("accuracy"))
			except (TypeError, ValueError, AttributeError):
				continue
			if 0 < acc <= SETUP_MAX_ACCURACY_M:
				usable.append((lat, lng, acc))
		if len(usable) < SETUP_MIN_READINGS:
			return {
				"error": "Only {0} usable GPS reading(s) (need {1}, each within {2} m). Stand in the open and try again.".format(
					len(usable), SETUP_MIN_READINGS, SETUP_MAX_ACCURACY_M
				)
			}

		weights = [1 / (a * a) for _, _, a in usable]
		total = sum(weights)
		lat = sum(w * p[0] for w, p in zip(weights, usable)) / total
		lng = sum(w * p[1] for w, p in zip(weights, usable)) / total
		# The combined fix is sharper than any one reading, but the readings
		# also disagree with each other - report the larger of the two.
		spread = max(_haversine_m(lat, lng, p[0], p[1]) for p in usable)
		accuracy = max((1 / total) ** 0.5, min(spread, min(a for _, _, a in usable)))

		doc = frappe.get_doc(CHECKPOINT, name)
		doc.latitude = round(lat, 8)
		doc.longitude = round(lng, 8)
		doc.position_accuracy_m = round(accuracy, 1)
		doc.position_samples = len(usable)
		doc.position_set_by = frappe.session.user
		doc.position_set_at = frappe.utils.now_datetime()
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return {
			"checkpoint": doc.name,
			"checkpoint_name": doc.checkpoint_name,
			"latitude": doc.latitude,
			"longitude": doc.longitude,
			"accuracy_m": doc.position_accuracy_m,
			"readings_used": len(usable),
			"readings_dropped": len(parsed or []) - len(usable),
		}
	except frappe.PermissionError as e:
		return {"error": str(e)}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("set_checkpoint_position", frappe.get_traceback())
		return {"error": str(e)}
