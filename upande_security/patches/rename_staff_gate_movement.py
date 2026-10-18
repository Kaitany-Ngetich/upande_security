# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Staff Gate Movement becomes Gate Movement: it now records contractors on
a badge as well as staff.

Runs before the model sync (pre_model_sync) so the renamed doctype - its
table, records (names unchanged, SGM-...), versions, comments, files and
every Link pointing at it - is in place when the app's gate_movement.json
is synced onto it. Gate Carried Item's reference_doctype is a Select, which
the rename does not touch, so it is re-pointed here.

Idempotent: does nothing once Gate Movement exists.
"""

import frappe

OLD = "Staff Gate Movement"
NEW = "Gate Movement"


def execute():
	if frappe.db.exists("DocType", OLD) and not frappe.db.exists("DocType", NEW):
		frappe.rename_doc("DocType", OLD, NEW, force=True)
	if frappe.db.table_exists("Gate Carried Item"):
		frappe.db.sql(
			"UPDATE `tabGate Carried Item` SET reference_doctype = %s WHERE reference_doctype = %s", (NEW, OLD)
		)
