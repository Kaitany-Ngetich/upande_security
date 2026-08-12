# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Shared "who is this guard and what farm/company are they on" resolution.

Guards live in one of two doctypes: internal guards are Employee records
(linked to a User via user_id), external guards are Security Guard records
(linked via their own `user` field). This mirrors the Employee-then-
Security-Guard fallback used elsewhere in this app (submit_patrol_points,
get_security_head_contact) — kept in one place here so the access-scoping
User Permission sync (user_permission_sync.py) and the farm-stamping
doc_events (scoping.py) don't each reinvent it.
"""

import frappe

GUARD_LEVEL_ROLES = ("Security Guard", "Gate Guard", "Security Head")


def resolve_company_farm(user):
	"""Return (company, farm) for a user, or (None, None) if neither an
	Employee nor a Security Guard record links back to them."""
	if not user or user in ("Administrator", "Guest"):
		return None, None

	emp = frappe.db.get_value(
		"Employee", {"user_id": user}, ["company", "custom_farm"], as_dict=True
	)
	if emp:
		return emp.company, emp.custom_farm

	guard = frappe.db.get_value(
		"Security Guard", {"user": user}, ["company", "farm"], as_dict=True
	)
	if guard:
		return guard.company, guard.farm

	return None, None


def user_has_guard_or_head_role(user):
	"""True if this user holds any guard-tier or Security Head role — the
	population the automatic Company/Farm User Permission provisioning
	applies to. Deliberately excludes System Manager: they already bypass
	all scoping, and provisioning them would be meaningless (and wrong if
	they happen to also be a spot-check Employee record)."""
	if not user or user in ("Administrator", "Guest"):
		return False
	roles = frappe.get_roles(user)
	return any(role in roles for role in GUARD_LEVEL_ROLES)
