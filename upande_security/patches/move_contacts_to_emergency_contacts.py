# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Move every emergency number into the Security Emergency Contact list,
which now serves the guard app's emergency call, the escalation
SMS and badges alike:

- each SOS Fallback Contact row (one per company) becomes that company's
  company-wide contact;
- each Badges per Company row that carried its own phone becomes a contact:
  for its farm when it named one, else company-wide if the company has none
  yet.

Reads the old rows straight from their tables (the columns stay after the
fields leave the forms). Runs once; a site that already has Emergency
Contacts is left alone."""

import frappe


def execute():
	if not frappe.db.table_exists("Security Emergency Contact"):
		return
	if frappe.db.count("Security Emergency Contact"):
		return

	rows = []
	defaults = set()
	if frappe.db.table_exists("Security Fallback Contact"):
		for r in frappe.db.sql(
			"select company, contact_name, contact_phone from `tabSecurity Fallback Contact` "
			"where parent='Security Ops Settings' and ifnull(contact_phone,'')!='' order by idx",
			as_dict=True,
		):
			if r.company and r.company not in defaults:
				defaults.add(r.company)
				rows.append({"company": r.company, "contact_name": r.contact_name or "Emergency Contact",
					"contact_phone": r.contact_phone, "contact_label": "Emergency Contact", "farms": []})

	cols = frappe.db.get_table_columns("Security Badge Emergency Contact") if frappe.db.table_exists(
		"Security Badge Emergency Contact") else []
	if "contact_phone" in cols:
		farm_rows = {}
		for r in frappe.db.sql(
			"select company, farm, contact_label, contact_phone from `tabSecurity Badge Emergency Contact` "
			"where parent='Security Ops Settings' and ifnull(contact_phone,'')!='' order by idx",
			as_dict=True,
		):
			if not r.company:
				continue
			label = r.contact_label or "Emergency Contact"
			if r.farm:
				# Farms sharing a number become one contact covering them all.
				key = (r.company, r.contact_phone)
				if key not in farm_rows:
					farm_rows[key] = {"company": r.company, "contact_name": label, "contact_phone": r.contact_phone,
						"contact_label": label, "farms": []}
					rows.append(farm_rows[key])
				farm_rows[key]["farms"].append({"farm": r.farm})
			elif r.company not in defaults:
				defaults.add(r.company)
				rows.append({"company": r.company, "contact_name": label, "contact_phone": r.contact_phone,
					"contact_label": label, "farms": []})

	for r in rows:
		doc = frappe.get_doc(dict(r, doctype="Security Emergency Contact", enabled=1))
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True)
