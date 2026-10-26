# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Store the Booking Code SMS wording when the field first arrives, so the
settings form shows (and lets someone edit) the message actually sent. A
field added to an existing Single gets no stored value, so its default would
never appear. Leaves any wording already set alone."""

import frappe

from upande_security.api.visitor_sms import BOOKING_TEMPLATE


def execute():
	if not frappe.db.get_single_value("Security Ops Settings", "visitor_booking_sms_template"):
		frappe.db.set_single_value("Security Ops Settings", "visitor_booking_sms_template", BOOKING_TEMPLATE)
