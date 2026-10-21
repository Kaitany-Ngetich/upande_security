# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Add the (farm, captured_at) index Patrol Playback needs.

on_doctype_update only runs when the doctype is next synced, and this index
is the difference between a playback request answering and timing out, so
it is applied directly here too. frappe.db.add_index is a no-op when the
index already exists, which also makes this safe to re-run.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Patrol GPS Log"):
		return
	frappe.db.add_index("Patrol GPS Log", ["farm", "captured_at"], "farm_captured_at")
