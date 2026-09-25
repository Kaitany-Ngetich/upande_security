# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time cleanup: Security Ops Settings.fallback_contacts is a standard
field (added in 7e4153a, 2026-08-29), but production also carries a Custom
Field with the same fieldname, created through Customize Form 14 minutes
after that commit - a stopgap before the deploy landed. Two definitions of
one fieldname on the same doctype is a trap for the next Customize Form
save, so the Custom Field copy goes.

Only deletes the Custom Field when the standard DocField really exists, so
a site on an older build of this app keeps its only definition. Security
Ops Settings is a Single, so there's no table column to worry about - the
rows live in the Security Fallback Contact child table either way.
"""

import frappe

CUSTOM_FIELD = "Security Ops Settings-fallback_contacts"


def execute():
	if not frappe.db.exists("Custom Field", CUSTOM_FIELD):
		return
	standard = frappe.db.exists(
		"DocField", {"parent": "Security Ops Settings", "fieldname": "fallback_contacts"}
	)
	if not standard:
		return
	frappe.delete_doc("Custom Field", CUSTOM_FIELD, ignore_permissions=True, force=True)
	frappe.db.commit()
