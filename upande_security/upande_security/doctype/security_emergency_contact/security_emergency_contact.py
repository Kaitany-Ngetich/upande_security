# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SecurityEmergencyContact(Document):
	def validate(self):
		"""A farm belongs to this contact's company and has one contact; a
		company has one company-wide contact (no farms)."""
		farms = [f.farm for f in self.farms or [] if f.farm]
		if len(set(farms)) != len(farms):
			frappe.throw("A farm is listed twice.")
		for farm in farms:
			farm_company = frappe.db.get_value("Farm", farm, "company")
			if farm_company and farm_company != self.company:
				frappe.throw("{0} belongs to {1}, not {2}.".format(frappe.bold(farm), farm_company, self.company))
		if not self.enabled:
			return
		others = frappe.get_all(
			"Security Emergency Contact",
			filters={"company": self.company, "enabled": 1, "name": ["!=", self.name or ""]},
			fields=["name", "contact_name"],
		)
		taken = {}
		for r in frappe.get_all(
			"Security Emergency Contact Farm",
			filters={"parenttype": "Security Emergency Contact", "parent": ["in", [o.name for o in others] or ["__none__"]]},
			fields=["parent", "farm"],
		):
			taken.setdefault(r.parent, []).append(r.farm)
		for o in others:
			clash = sorted(set(farms) & set(taken.get(o.name, [])))
			if clash:
				frappe.throw("{0} already has {1} as its emergency contact.".format(
					", ".join(frappe.bold(f) for f in clash), frappe.bold(o.contact_name)))
			if not farms and not taken.get(o.name):
				frappe.throw("{0} already has a company-wide contact, {1}. Give this one its farms, or disable that one.".format(
					frappe.bold(self.company), frappe.bold(o.contact_name)))
