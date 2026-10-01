# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Supplier Badge — a reusable physical badge pool, same model as Visitor
Badge (badge_number + company identify the physical card; current_
appointment is a point-in-time snapshot of whoever currently holds it),
scanned at the gate to pull up that supplier's currently open Purchase
Orders instead of the guard typing a PO number.

Deliberately its own doctype rather than a checkbox on Visitor Badge
since it carries supplier-specific lookup behavior (search_receiving_by_
supplier_badge / Purchase Order pull-up), but the status field itself
(Available/Issued/Lost) and its lifecycle are intentionally identical to
Visitor Badge: Issue Supplier Badge assigns it, Contractor Gate Checkout
releases it back to Available for the next supplier (see
release_badge_on_checkout's equivalent in visitor_badge_qr.py) - never a
long-term per-supplier assignment.
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
	"""Keeps status consistent with whether this badge is actually checked
	out to a visit right now, so Issue Supplier Badge / Contractor Gate
	Checkout don't also have to fight this hook to make their own status
	writes stick. Only moves between Available <-> Issued automatically;
	Lost is a deliberate state someone set on purpose and is never
	overwritten here.

	Status vocabulary (Available/Issued/Lost) and lifecycle deliberately
	match Visitor Badge exactly, not a supplier-specific scheme - same
	three values, same checkout-releases-it-to-the-pool behavior (see
	Contractor Gate Checkout).

	Driven by current_appointment, not supplier (2026-10-01): this badge is
	no longer durably assigned to one supplier long-term (see the module
	docstring above for why that changed) - supplier is now just a
	snapshot of whoever currently holds it, cleared on every checkout just
	like Visitor Badge never stores visitor identity at all. Deriving
	status from supplier instead would force it back to Available on
	every reissue to a contractor visit with no linked Supplier record,
	fighting the explicit status="Issued" the issue flow just set."""
	if doc.status == "Lost":
		return
	if doc.current_appointment and doc.status != "Issued":
		doc.status = "Issued"
	elif not doc.current_appointment and doc.status != "Available":
		doc.status = "Available"
