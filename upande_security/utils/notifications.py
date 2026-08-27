# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Shared recipient-role resolution for Security Ops notifications, driven by
Security Ops Settings' Notification Rules table. One place both tasks.py
(patrol alerts) and api/gate_receiving.py (receiving alerts) pull from, so
"which roles hear about X" is never hardcoded or copy-pasted per call site.

Empty table -> the original hardcoded defaults, so an unconfigured site
behaves exactly as before this became configurable. A non-empty table means
the admin is taking explicit control: only roles with the matching checkbox
ticked hear about that alert type, and if nobody has it ticked, that alert
type is deliberately silenced - it does not fall back to the default.
"""

import frappe

_ALERT_TYPES = {
	"missed_checkin": "receives_missed_checkin",
	"geofence": "receives_geofence_alerts",
	"escalation": "receives_escalation",
	"receiving": "receives_receiving_alerts",
}

_DEFAULT_ROLES = {
	"missed_checkin": ("Security Head", "System Manager"),
	"geofence": ("Security Head", "System Manager"),
	"escalation": ("Security Head", "System Manager"),
	"receiving": ("Stock User",),
}


def resolve_notification_roles(alert_type):
	"""Which roles should hear about a given alert type right now."""
	check_field = _ALERT_TYPES[alert_type]
	settings = frappe.get_single("Security Ops Settings")

	if not settings.notification_rules:
		return _DEFAULT_ROLES[alert_type]

	return tuple(
		row.role for row in settings.notification_rules if row.role and row.get(check_field)
	)


def resolve_notification_users(alert_type):
	"""Enabled, non-Administrator Users holding any role configured to
	receive this alert type. Shared by any call site that needs actual user
	names (as opposed to just the role list) - e.g. to build a Notification
	Log or an email recipient list."""
	roles = resolve_notification_roles(alert_type)
	if not roles:
		return []
	users = frappe.get_all(
		"Has Role",
		filters={"role": ["in", roles], "parenttype": "User"},
		fields=["parent"],
		distinct=True,
		pluck="parent",
	)
	return [
		u for u in users
		if u not in ("Administrator", "Guest") and frappe.db.get_value("User", u, "enabled")
	]
