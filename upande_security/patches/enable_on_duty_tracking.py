# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Switch On-Duty Location Tracking on (interval 5 minutes) when the fields
first arrive. A field added to an existing Single gets no stored value, so
its default would never apply. Leaves any value already set alone."""

import frappe

SETTINGS = "Security Ops Settings"


def execute():
	for field, value in (("feature_on_duty_tracking", 1), ("on_duty_interval_minutes", 5)):
		if not frappe.db.exists("Singles", {"doctype": SETTINGS, "field": field}):
			frappe.db.set_single_value(SETTINGS, field, value)
