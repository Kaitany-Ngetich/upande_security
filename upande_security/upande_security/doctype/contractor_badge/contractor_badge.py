# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""A numbered contractor badge from the company's pool - the same physical
model as Visitor and Supplier Badge: the card is generic and carries no
name. The guard assigns it to one crew member for a job (holder fields,
valid_until); scanned at any gate of the company it records that person's
movement (api/contractor_badge.py); at the end of the job it goes back to
the pool."""

import urllib.parse

import frappe
from frappe.model.document import Document


class ContractorBadge(Document):
	def autoname(self):
		# Numbers run on per company: leave Badge Number blank and the badge
		# gets the next one after the company's highest.
		if not self.badge_number:
			self.badge_number = next_badge_number(self.company)
		self.name = "CB-" + str(self.company) + "-" + str(self.badge_number)

	def validate(self):
		if self.status == "Available":
			self.holder_name = None
			self.holder_id_number = None
			self.contractor = None
			self.current_appointment = None
			self.valid_until = None
			self.issued_at = None
			self.issued_by = None

	def after_insert(self):
		self.generate_qr()

	def generate_qr(self):
		"""The QR names this badge only - never whoever holds it - so a card
		can be reissued without reprinting."""
		if self.qr_image:
			return
		from upande_security.api.supplier_badge_qr import _render_qr_png

		url = frappe.utils.get_url() + "/app/contractor-badge/" + urllib.parse.quote(str(self.name))
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "qr-" + str(self.name) + ".png",
				"attached_to_doctype": self.doctype,
				"attached_to_name": self.name,
				"attached_to_field": "qr_image",
				"content": _render_qr_png(url),
				"is_private": 0,
			}
		)
		file_doc.insert(ignore_permissions=True)
		self.db_set("qr_image", file_doc.file_url, update_modified=False)


def next_badge_number(company):
	"""The number after this company's highest contractor badge (1 if none)."""
	top = frappe.db.sql(
		"SELECT MAX(badge_number) FROM `tabContractor Badge` WHERE company = %s", (company,)
	)[0][0]
	return int(top or 0) + 1
