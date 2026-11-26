# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

PEOPLE_TABLES = ("witnesses", "victims", "responsible_persons")


class IncidentReport(Document):
	def validate(self):
		self.fill_employee_people()
		self.net_loss = max(flt(self.estimated_damage_value) - flt(self.recovered_value), 0)

	def fill_employee_people(self):
		"""People picked as an Employee carry that employee's name, phone and
		ID. The form fills name and phone as the employee is picked (fetch_from
		on Incident Person); this covers records saved without the form. The
		ID is only filled here - National ID is not a field every site's
		Employee has, and a fetch_from naming a missing field breaks the form."""
		has_national_id = frappe.get_meta("Employee").has_field("national_id")
		for table in PEOPLE_TABLES:
			for row in self.get(table) or []:
				if row.person_type != "Employee":
					row.employee = None
					continue
				if not row.employee:
					continue
				emp = frappe.db.get_value("Employee", row.employee, ["employee_name", "cell_number"], as_dict=True) or {}
				row.person_name = row.person_name or emp.get("employee_name")
				row.contact = row.contact or emp.get("cell_number")
				if has_national_id and not row.id_number:
					row.id_number = frappe.db.get_value("Employee", row.employee, "national_id")
