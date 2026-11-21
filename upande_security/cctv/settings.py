# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""CCTV Settings, read once per request.

Every switch defaults to OFF. A Single that has never been saved returns
None for its fields, and the rest of the app treats a missing feature flag
as ON (api/feature_flags.py) - the opposite of what this module needs: it
must not do anything until it has been legally cleared and switched on.
"""

import frappe

SWITCHES = ("enabled", "live_view_enabled", "alerts_enabled", "anpr_enabled", "presence_enabled", "face_recognition_enabled")

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
	"""True only when the module AND the given capability are both switched on."""
	s = get_settings()
	if not s.enabled:
		return False
	return switch == "enabled" or bool(s.get(switch))


def require(switch="enabled"):
	if not is_on(switch):
		frappe.throw(frappe._("CCTV {0} is switched off in CCTV Settings.").format(switch.replace("_", " ")), frappe.PermissionError)


def clear():
	if hasattr(frappe.local, "cctv_settings"):
		del frappe.local.cctv_settings
