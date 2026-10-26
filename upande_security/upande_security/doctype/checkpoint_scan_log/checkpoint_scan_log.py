# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CheckpointScanLog(Document):
	"""One attempt to scan a Security Checkpoint's QR on patrol - accepted or
	not. Written only by upande_security.api.checkpoints.scan_checkpoint."""

	pass


def on_doctype_update():
	# Progress and alerts ask "what has this patrol / this guard scanned".
	frappe.db.add_index("Checkpoint Scan Log", ["patrol", "scanned_at"], "patrol_scanned_at")
	frappe.db.add_index("Checkpoint Scan Log", ["external_guard", "scanned_at"], "external_guard_scanned_at")
	frappe.db.add_index("Checkpoint Scan Log", ["internal_guard", "scanned_at"], "internal_guard_scanned_at")
