# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Pipeline Trace: guards walk a water pipeline and scan the QR at each point.

The points are Security Checkpoints with checkpoint_type "Pipeline", grouped
by their `pipeline` name and ordered by `pipeline_sequence`. They reuse the
checkpoint QR labels and the checkpoint position fence (set on site from the
app, radius plus a capped GPS allowance, fake GPS refused), but they are never
part of a patrol: patrol plans, the unscanned-checkpoint alerts, the patrol
map and the checkpoint board all leave them out.

An accepted scan is one Asset Scan Log row with scan_type "Pipeline", carrying
the point, the pipeline, the condition the guard saw, remarks and an optional
photo. A refused scan (too far, poor or fake GPS) is not logged as an asset
scan; too far and fake GPS are raised as Unauthorized Access Attempts, as
they are for patrol checkpoints.

Gated by Security Ops Settings > feature_pipeline_trace (off by default).
"""

import frappe

from upande_security.api.checkpoints import CHECKPOINT, _checkpoint_name_from_scan, _guard_farm, _raise, _scanner, _settings
from upande_security.api.feature_flags import is_feature_enabled
from upande_security.api.sos_alert import _haversine_m

FEATURE = "feature_pipeline_trace"
PIPELINE = "Pipeline"
SCAN_LOG = "Asset Scan Log"
CONDITIONS = ("OK", "Leak", "Damaged", "Valve Issue", "Blocked", "Other")
_ALL_FARMS_ROLES = ("System Manager", "Security Head")


def _off():
	return {"error": "Pipeline Trace is not enabled on this instance."}


def _farms_for_user():
	"""None = every farm (System Manager / Security Head), else [farm] for a
	guard - their Active shift's farm, else the farm on their record."""
	personel, internal_guard, external_guard = _scanner()
	farm = _guard_farm(personel, internal_guard, external_guard)
	if farm:
		return [farm]
	if set(_ALL_FARMS_ROLES) & set(frappe.get_roles()):
		return None
	return []


def _points(farms, pipeline=None):
	filters = {"checkpoint_type": PIPELINE, "active": 1}
	if farms is not None:
		filters["farm"] = ["in", farms or ["__none__"]]
	if pipeline:
		filters["pipeline"] = pipeline
	return frappe.get_all(
		CHECKPOINT,
		filters=filters,
		fields=["name", "checkpoint_name", "pipeline", "pipeline_sequence", "farm", "location_hint", "latitude", "longitude"],
		order_by="pipeline asc, pipeline_sequence asc, checkpoint_name asc",
		limit_page_length=5000,
	)


def _last_scans(names):
	"""{checkpoint: {scanned_at, condition, guard}} - the latest pipeline scan of each point."""
	if not names:
		return {}
	out = {}
	for r in frappe.db.sql(
		"""
		SELECT l.checkpoint, l.scanned_at, l.`condition`, l.scanned_by
		FROM `tabAsset Scan Log` l
		JOIN (
			SELECT checkpoint, MAX(scanned_at) AS last
			FROM `tabAsset Scan Log`
			WHERE scan_type = 'Pipeline' AND checkpoint IN %(names)s
			GROUP BY checkpoint
		) m ON m.checkpoint = l.checkpoint AND m.last = l.scanned_at
		WHERE l.scan_type = 'Pipeline'
		""",
		{"names": tuple(names)},
		as_dict=True,
	):
		out[r.checkpoint] = r
	return out


def _pipelines_response(points):
	last = _last_scans([p.name for p in points])
	today = frappe.utils.getdate(frappe.utils.nowdate())
	lines = {}
	for p in points:
		line = lines.setdefault(
			p.pipeline or "(no pipeline)", {"pipeline": p.pipeline or "(no pipeline)", "farms": set(), "points": []}
		)
		if p.farm:
			line["farms"].add(p.farm)
		ls = last.get(p.name)
		scanned_today = bool(ls and frappe.utils.getdate(ls.scanned_at) == today)
		line["points"].append(
			{
				"checkpoint": p.name,
				"checkpoint_name": p.checkpoint_name,
				"sequence": p.pipeline_sequence,
				"farm": p.farm,
				"location_hint": p.location_hint,
				"has_position": bool(p.latitude and p.longitude),
				"last_scanned_at": str(ls.scanned_at) if ls else None,
				"last_condition": ls.condition if ls else None,
				"scanned_today": scanned_today,
			}
		)
	out = []
	for line in lines.values():
		pts = line["points"]
		out.append(
			{
				"pipeline": line["pipeline"],
				"farms": sorted(line["farms"]),
				"points": pts,
				"total": len(pts),
				"done_today": sum(1 for x in pts if x["scanned_today"]),
				"issues": sum(1 for x in pts if x["last_condition"] not in (None, "", "OK")),
			}
		)
	return out


@frappe.whitelist()
def get_pipeline_points(pipeline=None):
	"""The pipelines this user traces, each with its points in order, the
	latest scan of each point and how many were scanned today."""
	try:
		if not is_feature_enabled(FEATURE):
			return _off()
		return {"pipelines": _pipelines_response(_points(_farms_for_user(), (pipeline or "").strip() or None))}
	except Exception as e:
		frappe.log_error("get_pipeline_points", frappe.get_traceback())
		return {"error": str(e)}


@frappe.whitelist(methods=["POST"])
def scan_pipeline_point(code=None, latitude=None, longitude=None, accuracy=None, mocked=0, condition=None, remarks=None, photo=None):
	"""Record a pipeline point scan as an Asset Scan Log row - only at the point
	itself (same fence as patrol checkpoints). Always answers with `accepted`
	and a `message` for the guard; only a missing feature, GPS or condition is
	an error."""
	try:
		if not is_feature_enabled(FEATURE):
			return _off()
		if latitude in (None, "") or longitude in (None, ""):
			return {"error": "Your location is needed to record a pipeline scan."}
		condition = (condition or "").strip()
		if condition not in CONDITIONS:
			return {"error": "Choose the condition of the pipeline at this point."}
		photo = (photo or "").strip() or None
		if photo and not photo.startswith(("/files/", "/private/files/")):
			return {"error": "The photo was not uploaded - try again."}

		code = (code or "").strip()
		lat, lng = frappe.utils.flt(latitude), frappe.utils.flt(longitude)
		acc = frappe.utils.flt(accuracy) if accuracy not in (None, "") else None
		mocked = frappe.utils.cint(mocked) or (str(mocked).lower() == "true")

		name = _checkpoint_name_from_scan(code)
		point = frappe.db.get_value(
			CHECKPOINT,
			name,
			["name", "checkpoint_name", "checkpoint_type", "pipeline", "pipeline_sequence", "farm", "company",
				"latitude", "longitude", "radius_m", "active"],
			as_dict=True,
		) if name else None

		def refuse(result, message, **extra):
			return {"accepted": False, "result": result, "message": message,
					"checkpoint_name": point.checkpoint_name if point else None, **extra}

		if not point:
			_raise("Invalid Pipeline Scan", None, code, "Scanned code '" + code + "' is not a Security Checkpoint.")
			return refuse("Unknown Code", "This QR code is not a pipeline point.")
		if point.checkpoint_type != PIPELINE:
			return refuse("Patrol Checkpoint", point.checkpoint_name + " is a patrol checkpoint, not a pipeline point.")
		if not point.active:
			return refuse("Inactive", point.checkpoint_name + " is no longer in use - tell your supervisor.")
		if mocked:
			_raise("Invalid Pipeline Scan", point, code,
				"Pipeline point " + point.checkpoint_name + " scanned with a fake (mock) GPS location.")
			return refuse("Fake GPS", "Your phone is using a fake location. Turn off any location-changing app and scan again.")
		if not (point.latitude and point.longitude):
			return refuse("Position Not Set", point.checkpoint_name + " has no position yet - ask your supervisor to set it.")

		settings = _settings()
		distance = _haversine_m(lat, lng, point.latitude, point.longitude)
		if acc is None or acc > settings["max_accuracy"]:
			return refuse(
				"Poor GPS",
				"GPS is too weak here ({0}). Step into the open, wait a few seconds and scan again.".format(
					"unknown accuracy" if acc is None else "±{0:.0f} m".format(acc)
				),
				distance_m=round(distance, 1),
			)
		allowed = (point.radius_m or 3) + min(acc, settings["allowance"])
		if distance > allowed:
			_raise("Invalid Pipeline Scan", point, code,
				"Pipeline point {0} scanned {1:.0f} m away (allowed {2:.0f} m) - possibly a photo of the QR.".format(
					point.checkpoint_name, distance, allowed))
			return refuse(
				"Too Far",
				"You are {0:.0f} m from {1}. Scan the QR at the point itself.".format(distance, point.checkpoint_name),
				distance_m=round(distance, 1), allowed_m=round(allowed, 1),
			)

		from upande_security.api.security_api import _asset_scanner

		personel, internal_guard, external_guard, _farm, _company = _asset_scanner()
		log = frappe.new_doc(SCAN_LOG)
		log.update(
			{
				"scan_type": PIPELINE,
				"status": "Found",
				"asset_name": point.checkpoint_name,
				"checkpoint": point.name,
				"checkpoint_name": point.checkpoint_name,
				"pipeline": point.pipeline,
				"pipeline_sequence": point.pipeline_sequence,
				"condition": condition,
				"distance_m": round(distance, 1),
				"scanned_at": frappe.utils.now_datetime(),
				"scanned_by": frappe.session.user,
				"personel": personel,
				"internal_guard": internal_guard,
				"external_guard": external_guard,
				"farm": point.farm,
				"company": point.company,
				"latitude": lat,
				"longitude": lng,
				"gps_accuracy": acc,
				"remarks": (remarks or "").strip() or None,
				"photo": photo,
			}
		)
		log.flags.ignore_links = True
		log.insert(ignore_permissions=True)
		frappe.db.commit()

		line = _pipelines_response(_points(None, point.pipeline))
		return {
			"accepted": True,
			"result": "Valid",
			"message": "{0} recorded - {1} ({2:.0f} m).".format(point.checkpoint_name, condition, distance),
			"checkpoint_name": point.checkpoint_name,
			"log": log.name,
			"distance_m": round(distance, 1),
			"allowed_m": round(allowed, 1),
			"pipeline": line[0] if line else None,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("scan_pipeline_point", frappe.get_traceback())
		return {"error": str(e)}
