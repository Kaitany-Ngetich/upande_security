# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time cleanup: Appointment.custom_qr_token ("QR Confirmation Token")
is read/written by nothing - no Server Script, Client Script, Web Page, or
Print Format anywhere in this app references it. It was never added to
hooks.py's Custom Field fixture allowlist either, so it was never really
part of the shipped design - just an orphaned column on whichever site
happened to have it (found via a full local-DB-vs-fixture-allowlist audit
prompted by a user question about staging drift, the same class of gap as
custom_id_number/custom_visitor_badge/custom_host_received_time earlier).

Only other fixture-tracked field that referenced it was
Appointment-custom_host_received_time's insert_after ordering hint,
repointed to custom_visitor_badge in the same change that added this
patch.

Idempotent: only deletes if it's still there.
"""

import frappe


def execute():
	name = "Appointment-custom_qr_token"
	if not frappe.db.exists("Custom Field", name):
		return

	frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
	frappe.db.commit()

	logger = frappe.logger("upande_security", allow_site=True)
	logger.info("upande_security remove_dead_qr_token_field: deleted " + name)
	print("upande_security remove_dead_qr_token_field: deleted " + name)
