# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Staff Vehicle Sticker — a durable windscreen/plate sticker assigned to
one staff member at a time, scanned at the gate to check that employee in
and stamp their vehicle's plate onto the day's Attendance record in one
motion, instead of the guard searching for them by name/ID.

QR encodes the bare doctype name, not a public URL - unlike Visitor Badge
and Supplier Badge, nobody is meant to land on a webpage from this; the
gate app's own scanner is the only consumer, feeding straight into the
existing search_staff / create_staff_attendance check-in flow.
"""

import io

import frappe


def generate_qr_for_sticker(doc, method=None):
	"""Fixed, pre-printed physical object - the QR always encodes the same
	company + sticker_number, never anything about whichever staff member
	currently holds it. Wired via hooks.py doc_events on
	Staff Vehicle Sticker.after_insert, mirroring Supplier Badge's own QR
	gen (see supplier_badge_qr.py)."""
	if doc.qr_image:
		return
	if not doc.company or not doc.sticker_number:
		return

	png_bytes = _render_qr_png(doc.name)
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
	"""Keeps status consistent with whether a staff member is actually
	assigned, so reassigning is just "set/clear employee" in Desk - nobody
	has to separately remember to also flip the Select field. Only moves
	between Unassigned <-> Active automatically; Suspended/Lost are
	deliberate states someone set on purpose and are never overwritten
	here. Mirrors Supplier Badge's own auto_sync_status exactly."""
	if doc.status in ("Suspended", "Lost"):
		return
	if doc.employee and doc.status != "Active":
		doc.status = "Active"
	elif not doc.employee and doc.status != "Unassigned":
		doc.status = "Unassigned"
