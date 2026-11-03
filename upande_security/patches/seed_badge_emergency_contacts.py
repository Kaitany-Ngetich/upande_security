# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""The Gate Badge Card used to print these numbers from the template itself,
with Kaitet Ltd.'s number on every other company's badge. They now live in
Security Ops Settings > Badge Emergency Contacts. Carry them over only for
companies that exist on this site and have no row yet, so badges already in
use keep their number and no other site gets one it never had."""

import frappe

PREVIOUS_BADGE_NUMBERS = {
	"Karen Roses": "0718 253 145",
	"Kaitet Group": "+254 721 320 226",
	"Kaitet Ltd.": "+254 721 407 598",
}


def execute():
	frappe.reload_doc("upande_security", "doctype", "security_badge_emergency_contact")
	frappe.reload_doc("upande_security", "doctype", "security_ops_settings")
	settings = frappe.get_single("Security Ops Settings")
	have = {row.company for row in settings.get("badge_emergency_contacts") or []}
	added = False
	for company, phone in PREVIOUS_BADGE_NUMBERS.items():
		if company not in have and frappe.db.exists("Company", company):
			settings.append("badge_emergency_contacts", {"company": company, "contact_phone": phone})
			added = True
	if added:
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
