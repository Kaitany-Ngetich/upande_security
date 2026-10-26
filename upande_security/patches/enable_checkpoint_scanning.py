# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Store the Patrol Checkpoints defaults when the fields first arrive. A field
added to an existing Single gets no stored value, so its default would never
apply - and the Desk form would show the switch off, turning the feature off
the first time anyone saved the settings. Leaves any value already set alone."""

import frappe

SETTINGS = "Security Ops Settings"


def execute():
	for field, value in (
		("feature_checkpoint_scanning", 1),
		("checkpoint_accuracy_allowance_m", 7),
		("checkpoint_max_accuracy_m", 15),
	):
		if not frappe.db.exists("Singles", {"doctype": SETTINGS, "field": field}):
			frappe.db.set_single_value(SETTINGS, field, value)
