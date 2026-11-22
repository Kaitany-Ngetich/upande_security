# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""CCTV Settings, read once per request.

Every switch defaults to OFF. A Single that has never been saved returns
None for its fields, and the rest of the app treats a missing feature flag
as ON (api/feature_flags.py) - the opposite of what this module needs: it
must not do anything until it has been legally cleared and switched on.
"""

import frappe

SWITCHES = ("enabled", "live_view_enabled", "alerts_enabled", "anpr_enabled", "presence_enabled", "face_recognition_enabled", "push_enabled")

DEFAULTS = {
	"pre_roll_seconds": 15,
	"post_roll_seconds": 60,
	"live_token_ttl_seconds": 300,
	"playback_token_ttl_seconds": 900,
	"require_agent_signature": 1,
	"max_clock_skew_seconds": 300,
	"match_tolerance_minutes": 120,
	"auto_match_confidence": 85,
	"min_read_confidence": 50,
	"fuzzy_matching": 1,
	"duplicate_window_seconds": 60,
	"default_visit_minutes": 240,
	"overstay_grace_minutes": 30,
	"review_sla_minutes": 5,
	"retention_events_days": 30,
	"retention_sightings_days": 60,
	"retention_snapshots_days": 60,
	"retention_audit_days": 365,
	"command_ttl_minutes": 30,
	"evidence_max_minutes": 10,
	"presence_stale_hours": 12,
	"face_match_threshold": 60,
	"enforce_entitlements": 0,
	"patrol_link_enabled": 1,
	"guard_match_radius_m": 40,
	"guard_match_window_seconds": 90,
	"guard_match_hold_seconds": 60,
	"push_rate_limit_per_minute": 600,
	"push_max_body_mb": 8,
}


def get_settings():
	cached = getattr(frappe.local, "cctv_settings", None)
	if cached is not None:
		return cached
	values = frappe._dict()
	rows = frappe.db.sql(
		"select field, value from `tabSingles` where doctype='CCTV Settings'", as_dict=True
	)
	raw = {r.field: r.value for r in rows}
	for key in SWITCHES:
		values[key] = bool(int(raw.get(key) or 0))
	# The feature flag in Security Ops Settings; unset counts as OFF.
	values.ops_flag = bool(int(frappe.db.get_single_value("Security Ops Settings", "feature_cctv") or 0))
	for key, default in DEFAULTS.items():
		value = raw.get(key)
		values[key] = default if value in (None, "") else type(default)(float(value))
	# Face recognition never runs without a recorded legal sign-off.
	if values.face_recognition_enabled and not raw.get("legal_approval_reference"):
		values.face_recognition_enabled = False
	values.plate_formats = frappe.get_all(
		"CCTV Plate Format",
		filters={"parent": "CCTV Settings", "parenttype": "CCTV Settings"},
		fields=["label", "pattern", "vehicle_class", "example"],
		order_by="idx asc",
	)
	frappe.local.cctv_settings = values
	return values


def is_on(switch="enabled"):
	"""True only when Security Ops Settings > CCTV Integration, the module switch
	(CCTV Settings) AND the given capability are all on."""
	s = get_settings()
	if not (s.ops_flag and s.enabled):
		return False
	return switch == "enabled" or bool(s.get(switch))


def require(switch="enabled"):
	if not is_on(switch):
		frappe.throw(frappe._("CCTV {0} is switched off in CCTV Settings.").format(switch.replace("_", " ")), frappe.PermissionError)


def clear():
	for key in ("cctv_settings", "cctv_entitlements"):
		if hasattr(frappe.local, key):
			delattr(frappe.local, key)


def site_allows(farm, feature="core"):
	"""Per-site licence (CCTV Settings > Site Entitlements), when enforced.
	feature: core | vehicles | presence | ai_engine."""
	s = get_settings()
	if not s.enforce_entitlements:
		return True
	if not farm:
		return False
	key = f"cctv_ent:{farm}"
	cache = getattr(frappe.local, "cctv_entitlements", None)
	if cache is None:
		cache = {}
		frappe.local.cctv_entitlements = cache
	row = cache.get(key)
	if row is None:
		row = frappe.db.get_value("CCTV Site Entitlement", {"parent": "CCTV Settings", "farm": farm},
			["core", "vehicles", "presence", "ai_engine", "max_cameras", "valid_to"], as_dict=True) or False
		cache[key] = row
	if not row:
		return False
	if row.valid_to and frappe.utils.getdate(row.valid_to) < frappe.utils.getdate():
		return False
	return bool(row.get(feature)) and bool(row.core)


def max_cameras(farm):
	s = get_settings()
	if not s.enforce_entitlements:
		return None
	return frappe.db.get_value("CCTV Site Entitlement", {"parent": "CCTV Settings", "farm": farm}, "max_cameras") or None
