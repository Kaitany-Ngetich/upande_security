# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time backfill of Company/Farm User Permission rows for Employees and
Security Guards that already existed (and already qualified) before the
Employee.validate / Security Guard.validate doc_events in
upande_security.api.user_permission_sync started auto-provisioning them
going forward (see that module's docstring, and commit 3e6fc81 "Fix
hierarchical guard/Security-Head access scoping gaps").

Those doc_events only fire on save, so any Employee/Security Guard record
that already had a linked user and a company/farm set *before* the hook
existed was never granted its User Permission. This patch finds that
population and re-triggers the same sync_from_employee / sync_from_
security_guard logic directly against each qualifying record, rather than
duplicating the User Permission creation rules here.

Idempotent and safe on any environment:
  - sync_from_employee / sync_from_security_guard themselves no-op when a
    matching User Permission already exists (see _sync_user_permission),
    so running this patch twice creates nothing new the second time.
  - Records whose linked user doesn't hold a guard-tier or Security Head
    role are skipped by those same functions (user_has_guard_or_head_role)
    — nothing is created for ordinary HR/staff Employees.
  - This patch only ever reads Employee / Security Guard documents; it
    never modifies or saves them, only the User Permission rows they
    imply.
  - A single record that fails to even load (this app has hit dangling-
    Custom-Field ImportErrors on Employee before) is logged and skipped,
    not left to abort the whole patch - and everything queued after it
    in patches.txt on the same migrate.
"""

import frappe

from upande_security.api.user_permission_sync import (
	sync_from_employee,
	sync_from_security_guard,
)


def execute():
	logger = frappe.logger("upande_security", allow_site=True)

	permissions_before = frappe.db.count("User Permission")

	employee_names = frappe.get_all(
		"Employee",
		filters={"user_id": ["is", "set"]},
		pluck="name",
	)

	employees_examined = len(employee_names)
	employees_qualified = 0
	employees_errored = 0

	for employee_name in employee_names:
		try:
			emp = frappe.get_doc("Employee", employee_name)
		except Exception:
			# A single record failing to load (this app has hit dangling-
			# Custom-Field ImportErrors on Employee before) must not abort
			# the whole patch - and with it, everything after it in
			# patches.txt on the same migrate.
			employees_errored += 1
			frappe.log_error(
				title="upande_security backfill_guard_user_permissions (Employee load)",
				message=frappe.get_traceback(),
			)
			continue

		if not emp.user_id or not emp.company:
			continue
		employees_qualified += 1
		try:
			sync_from_employee(emp)
		except Exception:
			employees_errored += 1
			frappe.log_error(
				title="upande_security backfill_guard_user_permissions (Employee sync)",
				message=frappe.get_traceback(),
			)

	guard_names = frappe.get_all(
		"Security Guard",
		filters={"user": ["is", "set"]},
		pluck="name",
	)

	guards_examined = len(guard_names)
	guards_qualified = 0
	guards_errored = 0

	for guard_name in guard_names:
		try:
			guard = frappe.get_doc("Security Guard", guard_name)
		except Exception:
			guards_errored += 1
			frappe.log_error(
				title="upande_security backfill_guard_user_permissions (Security Guard load)",
				message=frappe.get_traceback(),
			)
			continue

		if not guard.user or not (guard.company or guard.farm):
			continue
		guards_qualified += 1
		try:
			sync_from_security_guard(guard)
		except Exception:
			guards_errored += 1
			frappe.log_error(
				title="upande_security backfill_guard_user_permissions (Security Guard sync)",
				message=frappe.get_traceback(),
			)

	frappe.db.commit()

	permissions_after = frappe.db.count("User Permission")
	created = permissions_after - permissions_before

	summary = (
		"upande_security backfill_guard_user_permissions: "
		"employees_examined={0} employees_qualified={1} employees_errored={2} "
		"guards_examined={3} guards_qualified={4} guards_errored={5} "
		"user_permissions_before={6} user_permissions_after={7} "
		"user_permissions_created={8}"
	).format(
		employees_examined,
		employees_qualified,
		employees_errored,
		guards_examined,
		guards_qualified,
		guards_errored,
		permissions_before,
		permissions_after,
		created,
	)

	logger.info(summary)
	print(summary)
