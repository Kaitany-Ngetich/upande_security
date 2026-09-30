# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Per-instance feature flags, sourced from Security Ops Settings.

This app now deploys to more than one Frappe instance, and not every
instance wants every feature (e.g. one site may not want the visitor
approval workflow, another may not use Gate Dispatch Verification at
all). Security Ops Settings is the single control point: each flag is a
plain Check field there, defaulting to 1 (enabled) so a site that
predates a given flag - or simply hasn't touched Security Ops Settings
since it was added - keeps behaving exactly as it always has.

Enforcement is always both-sided: require_feature() blocks the
server-side endpoint outright (so disabling a feature is a real
guarantee, not just a hidden button), and get_session_info surfaces the
same flags to the mobile app so it can hide the entry point entirely
rather than showing a guard a button that then throws.
"""

import frappe

FEATURE_FIELDS = [
	"feature_visitor_approval_workflow",
	"feature_contractor_checkin",
	"feature_sos_alert",
	"feature_patrol_geofence_alerts",
	"feature_security_alerts",
	"feature_watchlist",
	"feature_asset_scanning",
	"feature_gate_dispatch",
	"feature_gate_receiving",
	"feature_vehicle_stickers",
	"feature_visitor_badges",
	"feature_supplier_badges",
	"feature_command_center",
	"feature_visitor_sms_otp",
]


def get_enabled_features():
	"""All feature flags as {fieldname: bool}. Request-local cache only
	(not frappe.cache) - Security Ops Settings can be edited at any time
	from Desk, and a feature toggle should take effect on the very next
	request, not linger behind a cross-request cache."""
	if not hasattr(frappe.local, "security_feature_flags"):
		values = (
			frappe.db.get_value(
				"Security Ops Settings",
				"Security Ops Settings",
				FEATURE_FIELDS,
				as_dict=True,
			)
			or {}
		)
		frappe.local.security_feature_flags = {
			field: bool(values.get(field) if values.get(field) is not None else 1)
			for field in FEATURE_FIELDS
		}
	return frappe.local.security_feature_flags


def is_feature_enabled(name):
	"""True unless a Security Ops Settings row explicitly turned it off."""
	return get_enabled_features().get(name, True)


def require_feature(name, message=None):
	"""Call at the top of any whitelisted function or Server Script gated by
	a feature flag. Throws the same PermissionError shape every other
	access check in this app already uses, so callers (including the
	mobile client's soft-fail wrapper) see one consistent failure path."""
	if not is_feature_enabled(name):
		frappe.throw(
			message or frappe._("This feature is not enabled on this instance."),
			frappe.PermissionError,
		)
