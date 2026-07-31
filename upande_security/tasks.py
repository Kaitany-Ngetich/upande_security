# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Scheduled maintenance for Upande Security."""

import frappe

from upande_security.upande_security.doctype.security_guard_shift_assignment.security_guard_shift_assignment import (
	derive_status,
)


def refresh_shift_statuses():
	"""Roll Security Guard Shift Assignment statuses forward with the clock.

	Saving a shift derives its status, but a shift that simply *elapses* is never
	saved again — so without this an Active shift would read Active forever.
	Runs hourly.

	Writes go through frappe.db.set_value rather than doc.save() on purpose: the
	document's validate() runs an overlap check that can legitimately throw on
	historical data, and one bad row must not stop the whole sweep.
	"""
	rows = frappe.get_all(
		"Security Guard Shift Assignment",
		filters={"status": ["!=", "Cancelled"]},
		fields=["name", "start_date", "end_date", "status"],
		limit_page_length=0,
	)

	changed = 0
	for row in rows:
		derived = derive_status(row.start_date, row.end_date, row.status)
		if not derived or derived == row.status:
			continue
		frappe.db.set_value(
			"Security Guard Shift Assignment",
			row.name,
			"status",
			derived,
			update_modified=False,
		)
		changed += 1

	if changed:
		frappe.db.commit()

	return {"checked": len(rows), "updated": changed}
