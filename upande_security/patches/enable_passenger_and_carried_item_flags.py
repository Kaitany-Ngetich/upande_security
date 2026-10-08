# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Switch on the two new gate flags - feature_passenger_names and
feature_carried_items - on sites that already have a Security Ops Settings
record.

Same reason as backfill_feature_flag_defaults: a new Check field's "1"
default never reaches the already-saved Single, so without this both flags
would land as 0 (off) on every existing site. That patch has already run
everywhere, so it won't pick these up - hence this one, for just the two
new fields.
"""

import frappe

NEW_FLAGS = ("feature_passenger_names", "feature_carried_items")


def execute():
	if not frappe.db.exists("DocType", "Security Ops Settings"):
		return

	frappe.reload_doc("upande_security", "doctype", "security_ops_settings")
	for field in NEW_FLAGS:
		# Only a flag that was never stored - an admin who already switched
		# one off keeps it off.
		stored = frappe.db.sql(
			"SELECT 1 FROM `tabSingles` WHERE doctype = 'Security Ops Settings' AND field = %s",
			(field,),
		)
		if not stored:
			frappe.db.set_single_value("Security Ops Settings", field, 1)

	frappe.db.commit()
