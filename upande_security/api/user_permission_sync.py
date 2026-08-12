# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Automatic Company/Farm User Permission provisioning.

The hierarchical guard/Security-Head/System-Manager access scoping across
this app's doctypes (Patrol Report, Near Miss Report, Patrol GPS Log,
Incident Report, ...) is implemented with plain Frappe DocPerm + User
Permission — a Security Head's "read=1, if_owner=0" on a doctype with a
Farm/Company Link field is only actually scoped to their own farm/company
if a matching User Permission row exists for them. Nothing ever created
those rows automatically, so in practice almost nobody had one and the
scoping was unprovisioned rather than broken.

This module is the fix: whenever an Employee's (internal guard) or
Security Guard's (external guard) own company/farm gets set or changed —
and that record's linked User actually holds a guard-tier or Security Head
role — the matching User Permission row(s) are created/updated to match.
Idempotent and safe to call on every save; a change to the farm/company
value drops the now-stale permission and adds the new one.

Wired via hooks.py doc_events on Employee.validate and Security Guard.validate.
"""

import frappe

from upande_security.api.identity import user_has_guard_or_head_role


def _sync_user_permission(user, allow, new_value, old_value=None):
	"""Ensure exactly one (user, allow) User Permission points at
	new_value, dropping a stale one pointing at old_value first if it's
	different. A no-op if new_value is falsy (nothing to grant) other than
	clearing out the old one."""
	if old_value and old_value != new_value:
		stale = frappe.db.get_value(
			"User Permission",
			{"user": user, "allow": allow, "for_value": old_value},
			"name",
		)
		if stale:
			frappe.delete_doc("User Permission", stale, ignore_permissions=True)

	if not new_value:
		return

	already = frappe.db.exists(
		"User Permission", {"user": user, "allow": allow, "for_value": new_value}
	)
	if already:
		return

	perm = frappe.new_doc("User Permission")
	perm.user = user
	perm.allow = allow
	perm.for_value = new_value
	perm.apply_to_all_doctypes = 1
	perm.insert(ignore_permissions=True)


def sync_from_employee(doc, method=None):
	"""Employee.validate — keep Company/Farm User Permission in step with
	an Employee's own company/custom_farm, for any Employee whose linked
	User is guard-tier or Security Head. Employees who aren't security
	staff (the rest of the HR roster) are left alone — no User is touched
	if it doesn't hold one of those roles."""
	user = doc.user_id
	if not user or not user_has_guard_or_head_role(user):
		return

	previous = doc.get_doc_before_save()
	old_company = previous.company if previous else None
	old_farm = previous.get("custom_farm") if previous else None

	_sync_user_permission(user, "Company", doc.company, old_company)
	_sync_user_permission(user, "Farm", doc.get("custom_farm"), old_farm)


def sync_from_security_guard(doc, method=None):
	"""Security Guard.validate — same idea for external guards, who carry
	company/farm directly on their own record (no Employee backs them)."""
	user = doc.user
	if not user or not user_has_guard_or_head_role(user):
		return

	previous = doc.get_doc_before_save()
	old_company = previous.company if previous else None
	old_farm = previous.farm if previous else None

	_sync_user_permission(user, "Company", doc.company, old_company)
	_sync_user_permission(user, "Farm", doc.farm, old_farm)
