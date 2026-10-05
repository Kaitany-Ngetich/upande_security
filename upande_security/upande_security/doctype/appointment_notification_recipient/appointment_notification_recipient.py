# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

# prefered_email is what the Employee form itself resolves to, but it is
# blank on plenty of real records - fall back rather than silently dropping
# the recipient.
EMAIL_FIELDS = ("prefered_email", "company_email", "personal_email")
PHONE_FIELDS = ("cell_number", "custom_phone_number")


def employee_contact(employee):
	"""(email, phone) for an Employee, trying each field in turn and finally
	the linked User's own email."""
	row = frappe.db.get_value(
		"Employee", employee,
		["user_id"] + list(EMAIL_FIELDS) + list(PHONE_FIELDS),
		as_dict=True,
	) or {}
	email = next((row.get(f) for f in EMAIL_FIELDS if row.get(f)), None)
	if not email and row.get("user_id"):
		email = frappe.db.get_value("User", row["user_id"], "email")
	phone = next((row.get(f) for f in PHONE_FIELDS if row.get(f)), None)
	return email, phone


class AppointmentNotificationRecipient(Document):
	def validate(self):
		if not self.employee and not self.email and not self.whatsapp_no:
			frappe.throw("Pick an Employee, or enter an Email or WhatsApp number.")
		if self.employee:
			email, phone = employee_contact(self.employee)
			if not self.email:
				self.email = email
			if not self.whatsapp_no:
				self.whatsapp_no = phone
		if not self.email and not self.whatsapp_no:
			frappe.throw(
				"{0} has no email or phone number on their Employee record - "
				"add one there, or type it here.".format(self.employee)
			)
