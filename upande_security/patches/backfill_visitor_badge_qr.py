# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time backfill of the host-confirmation QR code image for every
Visitor Badge that predates upande_security.api.visitor_badge_qr's
after_insert hook (see that module's docstring - added in this same change).

201 farm-specific badges (the 200 Kaitet Ltd. Endebes/Lokitela/Saboti/Vale
badges, plus one Karen Roses/Torongo record) were bulk-imported before this
hook existed, so they were never given a QR image at all - the printed
badge would show a broken-image icon where the QR should be.

Idempotent: only touches records where qr_image is genuinely blank, and
only ever adds a new File + sets qr_image; never modifies/removes an
existing one.
"""

import frappe

from upande_security.api.visitor_badge_qr import generate_qr_for_badge


def execute():
	logger = frappe.logger("upande_security", allow_site=True)

	names = frappe.get_all(
		"Visitor Badge",
		filters={"qr_image": ["in", ["", None]]},
		pluck="name",
	)

	examined = len(names)
	generated = 0
	skipped_incomplete = 0
	errored = 0

	for name in names:
		try:
			doc = frappe.get_doc("Visitor Badge", name)
		except Exception:
			errored += 1
			frappe.log_error(
				title="upande_security backfill_visitor_badge_qr (load)",
				message=frappe.get_traceback(),
			)
			continue

		if not doc.company or not doc.farm or not doc.badge_number:
			skipped_incomplete += 1
			continue

		try:
			generate_qr_for_badge(doc)
			generated += 1
		except Exception:
			errored += 1
			frappe.log_error(
				title="upande_security backfill_visitor_badge_qr (generate)",
				message=frappe.get_traceback(),
			)

	frappe.db.commit()

	summary = (
		"upande_security backfill_visitor_badge_qr: "
		"examined={0} generated={1} skipped_incomplete={2} errored={3}"
	).format(examined, generated, skipped_incomplete, errored)
	logger.info(summary)
	print(summary)
