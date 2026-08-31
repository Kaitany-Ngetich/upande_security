# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Supplier Badge — a durable physical badge assigned to one supplier at a
time (never per-visit, unlike Visitor Badge), scanned at the gate to pull
up that supplier's currently open Purchase Orders instead of the guard
typing a PO number.

Deliberately its own doctype rather than a checkbox on Visitor Badge:
Visitor Badge auto-releases back to Available the moment its linked
Appointment reaches Visitor Checked Out (see release_badge_on_checkout in
visitor_badge_qr.py) - that exact behavior, applied here, would silently
un-assign a supplier from their badge after every single delivery, which is
the "changing badges now and then" problem this feature exists to avoid.
Reassigning a Supplier Badge to a different supplier is instead a
deliberate admin action in Desk (see auto_sync_status below), never an
automatic side effect of a gate scan.
"""

import io
import urllib.parse

import frappe


def generate_qr_for_badge(doc, method=None):
	"""Fixed, pre-printed physical object - the QR always encodes the same
	company + badge_number, never anything about whichever supplier
	currently holds it. Wired via hooks.py doc_events on
	Supplier Badge.after_insert, mirroring Visitor Badge's own QR gen.

	Encodes a public info-page URL (/supplier-badge?badge=...), not the
	bare doc name - so scanning with an ordinary phone camera shows the
	supplier it's currently assigned to (name only, nothing about any
	visit - a supplier badge has no host/purpose to show), same as
	Visitor Badge's own /visitor-received page. The gate app's own
	scanner still resolves this fine: search_receiving_by_supplier_badge
	pulls the badge name back out of the "badge" query param."""
	if doc.qr_image:
		return
	if not doc.company or not doc.badge_number:
		return

	url = frappe.utils.get_url() + "/supplier-badge?badge=" + urllib.parse.quote(str(doc.name))
	png_bytes = _render_qr_png(url)
	fname = "qr-" + str(doc.name) + ".png"

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": fname,
			"attached_to_doctype": doc.doctype,
			"attached_to_name": doc.name,
			"attached_to_field": "qr_image",
			"content": png_bytes,
			"is_private": 0,
		}
	)
	file_doc.insert(ignore_permissions=True)

	frappe.db.set_value(doc.doctype, doc.name, "qr_image", file_doc.file_url, update_modified=False)


def _render_qr_png(data):
	import qrcode

	qr = qrcode.QRCode(box_size=8, border=2)
	qr.add_data(data)
	qr.make(fit=True)
	img = qr.make_image(fill_color="black", back_color="white")

	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return buf.getvalue()


def auto_sync_status(doc, method=None):
	"""Keeps status consistent with whether a supplier is actually assigned,
	so reassigning is just "set/clear supplier" in Desk - nobody has to
	separately remember to also flip the Select field. Only moves between
	Unassigned <-> Active automatically; Suspended/Lost are deliberate
	states someone set on purpose and are never overwritten here."""
	if doc.status in ("Suspended", "Lost"):
		return
	if doc.supplier and doc.status != "Active":
		doc.status = "Active"
	elif not doc.supplier and doc.status != "Unassigned":
		doc.status = "Unassigned"
