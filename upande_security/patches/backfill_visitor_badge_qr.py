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


def execute():
	# Ran on every site long ago. Visitor Badge has since become Gate Badge,
	# which generates its own QR on insert - nothing left to backfill.
	return
