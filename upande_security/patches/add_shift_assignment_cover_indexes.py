# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Indexes on Security Guard Shift Assignment that suggest_relievers and
toggle_guard_day read through (see its on_doctype_update). on_doctype_update
only runs when the doctype is next synced, so it is applied here too;
add_index is a no-op when the index exists."""

import frappe

from upande_security.upande_security.doctype.security_guard_shift_assignment.security_guard_shift_assignment import (
	on_doctype_update,
)


def execute():
	if frappe.db.table_exists("Security Guard Shift Assignment"):
		on_doctype_update()
