# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""QR code generation for gate-facing print formats (Delivery Note's "Gate
Copy" print format, and any future dispatch-source print format that wants
the same treatment) — encodes the document's own URL so a guard's phone
camera (via the mobile app's existing extractDispatchReference()/
extractDeliveryReference() URL-stripping, or any generic QR scanner) lands
on the right reference without anyone typing it in.

Self-hosted deliberately, not a third-party QR image API: pyqrcode is
already a Frappe dependency (frappe.twofactor.get_qr_svg_code uses it for
2FA login codes) - reusing it means no document reference ever leaves this
site, and printing keeps working even with no internet access at print
time.
"""

from base64 import b64encode
from io import BytesIO

import frappe


def get_dispatch_qr_svg(doctype: str, name: str) -> str:
	"""Base64-encoded SVG QR code for one document, encoding its own Desk
	URL. Returns "" (not an exception) on any failure — a print format is
	never worth breaking over a QR code, same soft-fail spirit as the rest
	of this app's read-only lookups."""
	try:
		from pyqrcode import create as qrcreate

		url = frappe.utils.get_url_to_form(doctype, name)
		qr = qrcreate(url)
		stream = BytesIO()
		try:
			qr.svg(stream, scale=4, background="#ffffff", module_color="#000000")
			svg = stream.getvalue().decode().replace("\n", "")
		finally:
			stream.close()
		return b64encode(svg.encode()).decode()
	except Exception:
		frappe.log_error("get_dispatch_qr_svg failed for " + str(doctype) + " " + str(name))
		return ""
