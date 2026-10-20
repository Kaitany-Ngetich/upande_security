# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Gate Carried Item becomes Registered Personal Item.

Runs before the model sync so the renamed doctype - table, records, versions,
comments, files and Links - is in place when registered_personal_item.json is
synced onto it. Does nothing on a site that never had Gate Carried Item, or
once the rename is done.
"""

import frappe

OLD = "Gate Carried Item"
NEW = "Registered Personal Item"


def execute():
	if frappe.db.exists("DocType", OLD) and not frappe.db.exists("DocType", NEW):
		frappe.rename_doc("DocType", OLD, NEW, force=True)
