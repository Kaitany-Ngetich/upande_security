# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Auto-generates the host-confirmation QR code for a Visitor Badge.

A badge is a fixed, pre-printed physical object - per issue_visitor_badge.py's
own comment, its QR always encodes the same company + farm + badge_number,
never a per-visit code. Whoever it's currently issued to changes
(current_appointment), but the physical card and its printed QR never do.

Wired via hooks.py doc_events on Visitor Badge.after_insert, so every new
badge - any future farm's stock, not just today's - gets one automatically
instead of depending on whoever bulk-imports the records to also generate
images by hand.
"""

import io

import frappe


def generate_qr_for_badge(doc, method=None):
	if doc.qr_image:
		return
	if not doc.company or not doc.farm or not doc.badge_number:
		# Can't build a meaningful confirm URL without all three - leave
		# blank rather than encode a broken link. Whoever finishes setting
		# up the record can re-save to trigger this again.
		return

	url = (
		frappe.utils.get_url()
		+ "/visitor-received?company="
		+ str(doc.company).replace(" ", "%20")
		+ "&farm="
		+ str(doc.farm).replace(" ", "%20")
		+ "&badge="
		+ str(doc.badge_number)
	)

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
