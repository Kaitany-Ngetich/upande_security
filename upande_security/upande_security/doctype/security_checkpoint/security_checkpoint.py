# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SecurityCheckpoint(Document):
	"""A physical point on a farm a patrol must reach - a gate, a store, a
	block corner - marked with a printed QR. Guards scan it on patrol
	(upande_security.api.checkpoints.scan_checkpoint); a scan only counts
	within radius_m of the position set on site from the app, so a photo of
	the QR is useless anywhere else. Also read by
	upande_security.tasks.check_unscanned_checkpoints."""

	def validate(self):
		# The farm's company, not the user's default one - a checkpoint on a
		# Karen Roses farm created by someone whose default is another
		# company would otherwise be labelled and alerted under the wrong one.
		if self.farm:
			self.company = frappe.db.get_value("Farm", self.farm, "company") or self.company

	def after_insert(self):
		self.make_qr()

	def make_qr(self):
		"""QR of the checkpoint's Desk URL, the same shape as Asset labels -
		a phone camera opens the record, the app reads the name out of it."""
		if self.qr_image:
			return
		from upande_security.api.staff_vehicle_sticker_qr import _render_qr_png

		url = frappe.utils.get_url("/app/security-checkpoint/" + self.name)
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "qr-" + self.name + ".png",
				"attached_to_doctype": self.doctype,
				"attached_to_name": self.name,
				"attached_to_field": "qr_image",
				"content": _render_qr_png(url),
				"is_private": 0,
			}
		)
		file_doc.insert(ignore_permissions=True)
		self.db_set("qr_image", file_doc.file_url, update_modified=False)
