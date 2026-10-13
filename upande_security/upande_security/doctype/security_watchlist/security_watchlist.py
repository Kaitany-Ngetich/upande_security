# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SecurityWatchlist(Document):
	def before_insert(self):
		self.added_by = frappe.session.user
		self.added_on = frappe.utils.now_datetime()

	def validate(self):
		self.fill_from_employee()
		if not (self.employee or self.id_number or self.phone_number or self.vehicle_plate or self.full_name):
			frappe.throw("Give at least one detail to watch for: Employee, ID, phone, plate or name.")
		if self.status == "Inactive" and not self.closed_on:
			self.closed_on = frappe.utils.now_datetime()
			self.closed_by = frappe.session.user
		elif self.status == "Active":
			self.closed_on = None
			self.closed_by = None

	def fill_from_employee(self):
		"""For a watched staff member, copy in what the other checks match on -
		ID and phone (incidents name people by these, not by Employee) and
		their staff sticker's plate (vehicle, dispatch and receiving checks).
		Only empty fields are filled; anything typed in is kept."""
		if not self.employee:
			return
		meta = frappe.get_meta("Employee")
		wanted = [f for f in ("employee_name", "national_id", "passport_number", "cell_number") if f == "employee_name" or meta.has_field(f)]
		emp = frappe.db.get_value("Employee", self.employee, wanted, as_dict=True) or {}
		if not self.full_name:
			self.full_name = emp.get("employee_name")
		if not self.id_number:
			self.id_number = emp.get("national_id") or emp.get("passport_number")
		if not self.phone_number:
			self.phone_number = emp.get("cell_number")
		if not self.vehicle_plate and frappe.db.table_exists("Staff Vehicle Sticker"):
			self.vehicle_plate = frappe.db.get_value(
				"Staff Vehicle Sticker",
				{"employee": self.employee, "status": "Active"},
				"plate_number",
				order_by="modified desc",
			)

	def on_update(self):
		from upande_security.api.watchlist import clear_cache

		clear_cache()
		# A gate request between this clear and the commit would re-cache the
		# pre-save list; clearing again once committed closes that window.
		frappe.db.after_commit.add(clear_cache)

	def on_trash(self):
		from upande_security.api.watchlist import clear_cache

		clear_cache()
		frappe.db.after_commit.add(clear_cache)
