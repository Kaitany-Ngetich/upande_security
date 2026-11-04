# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Fill Security Ops Settings' Incident Types Left Out with its default
("SOS") on sites that have never set it, so the setting shows what the
dashboard and the security report actually leave out. A site that already
has a value - even an empty one - keeps it."""

import frappe


def execute():
	exists = frappe.db.sql(
		"select 1 from `tabSingles` where doctype='Security Ops Settings' and field='hidden_incident_types'"
	)
	if not exists:
		frappe.db.set_single_value("Security Ops Settings", "hidden_incident_types", "SOS")
