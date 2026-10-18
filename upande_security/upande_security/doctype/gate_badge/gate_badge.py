# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Every physical badge security hands out, in one pool per company:

- Visitor: one farm's numbered cards, lent for a visit (issue_visitor_badge),
  back to Available at check-out.
- Supplier: lent to a supplier for a visit or a delivery (issue_supplier_badge,
  issue_supplier_badge_for_receiving).
- Contractor: lent to one crew member for a job and scanned at every gate of
  the company (api/contractor_badge.py).

The cards are generic and pre-printed: the QR names the card, never whoever
holds it, so a badge is reissued without reprinting. Names follow the old
per-type badges exactly ({company}-{farm}-{n}, {company}-{n}, CB-{company}-{n})
so the QR codes on cards already printed keep resolving.
"""

import io
import urllib.parse

import frappe
from frappe import _
from frappe.model.document import Document


class GateBadge(Document):
	def autoname(self):
		if not self.badge_number:
			self.badge_number = next_badge_number(self.badge_type, self.company, self.farm)
		if self.badge_type == "Visitor":
			if not self.farm:
				frappe.throw(_("A visitor badge belongs to a farm."))
			self.name = "{0}-{1}-{2}".format(self.company, self.farm, self.badge_number)
		elif self.badge_type == "Supplier":
			self.name = "{0}-{1}".format(self.company, self.badge_number)
		else:
			self.name = "CB-{0}-{1}".format(self.company, self.badge_number)

	def validate(self):
		if self.badge_type != "Visitor":
			self.farm = None
		if self.status == "Lost":
			return
		if self.status == "Available" and self.has_value_changed("status"):
			# Released: nobody holds it any more.
			self._clear_holder()
			return
		held = bool(self.current_appointment or self.current_receiving or self.holder_name)
		self.status = "Issued" if held else "Available"
		if not held:
			self._clear_holder()

	def _clear_holder(self):
		for field in (
			"current_appointment", "current_receiving", "supplier", "holder_name",
			"holder_id_number", "valid_until", "issued_at", "issued_by",
		):
			self.set(field, None)

	def after_insert(self):
		self.generate_qr()

	def generate_qr(self):
		"""What each card's QR opens - unchanged from the old per-type badges:
		a visitor's host confirms the visit on /visitor-received; a supplier
		badge shows its supplier on /supplier-badge; a contractor badge opens
		the badge itself (the gate app reads its name off the link)."""
		if self.qr_image:
			return
		base = frappe.utils.get_url()
		if self.badge_type == "Visitor":
			url = (
				base + "/visitor-received?company=" + str(self.company).replace(" ", "%20")
				+ "&farm=" + str(self.farm).replace(" ", "%20") + "&badge=" + str(self.badge_number)
			)
		elif self.badge_type == "Supplier":
			url = base + "/supplier-badge?badge=" + urllib.parse.quote(str(self.name))
		else:
			url = base + "/app/gate-badge/" + urllib.parse.quote(str(self.name))
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "qr-" + str(self.name) + ".png",
				"attached_to_doctype": self.doctype,
				"attached_to_name": self.name,
				"attached_to_field": "qr_image",
				"content": render_qr_png(url),
				"is_private": 0,
			}
		)
		file_doc.insert(ignore_permissions=True)
		self.db_set("qr_image", file_doc.file_url, update_modified=False)


def next_badge_number(badge_type, company, farm=None):
	"""The number after the highest in this pool: per company and type, and
	per farm for visitor badges (each farm runs its own 1, 2, 3...)."""
	if badge_type == "Visitor":
		top = frappe.db.sql(
			"SELECT MAX(badge_number) FROM `tabGate Badge` WHERE badge_type = 'Visitor' AND company <=> %s AND farm <=> %s",
			(company, farm),
		)[0][0]
	else:
		top = frappe.db.sql(
			"SELECT MAX(badge_number) FROM `tabGate Badge` WHERE badge_type = %s AND company <=> %s",
			(badge_type, company),
		)[0][0]
	return int(top or 0) + 1


def render_qr_png(data):
	import qrcode

	qr = qrcode.QRCode(box_size=8, border=2)
	qr.add_data(data)
	qr.make(fit=True)
	img = qr.make_image(fill_color="black", back_color="white")
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return buf.getvalue()


_MAX_BULK = 500


@frappe.whitelist(methods=["POST"])
def create_badges(badge_type, company, count, farm=None):
	"""Add `count` badges to a pool - visitor badges per farm, supplier and
	contractor badges per company - numbered on from its highest (each gets
	its QR). Security Head / System Manager only."""
	if not any(r in frappe.get_roles() for r in ("Security Head", "System Manager")):
		frappe.throw(_("Only a Security Head can create badges."), frappe.PermissionError)
	if badge_type not in ("Visitor", "Supplier", "Contractor"):
		frappe.throw(_("Badge type must be Visitor, Supplier or Contractor."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} not found.").format(company))
	farm = (farm or "").strip() or None
	if badge_type == "Visitor":
		if not farm or not frappe.db.exists("Farm", farm):
			frappe.throw(_("Visitor badges belong to a farm - choose one."))
	else:
		farm = None
	try:
		count = int(count)
	except (TypeError, ValueError):
		frappe.throw(_("How many badges? Enter a whole number."))
	if count < 1:
		frappe.throw(_("Create at least one badge."))
	if count > _MAX_BULK:
		frappe.throw(_("At most {0} badges at a time.").format(_MAX_BULK))

	first = next_badge_number(badge_type, company, farm)
	for number in range(first, first + count):
		frappe.get_doc(
			{"doctype": "Gate Badge", "badge_type": badge_type, "company": company, "farm": farm, "badge_number": number, "status": "Available"}
		).insert(ignore_permissions=True)
	frappe.db.commit()
	return {"created": count, "first": first, "last": first + count - 1}


@frappe.whitelist()
def next_number(badge_type, company, farm=None):
	"""For the Create Badges dialog: where the next batch will start."""
	if not badge_type or not company:
		return None
	return next_badge_number(badge_type, company, farm or None)
