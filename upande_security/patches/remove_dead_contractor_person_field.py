# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time cleanup: Appointment.custom_contractor_person was removed from
this app's fixtures back on 2026-08-14 (fully superseded by
custom_contractor_personnel, the real personnel-list child table - zero
references, zero real data). Fixture sync is add/update-only, never
deletion - any site that already had this field before that fixture
change keeps it forever no matter how many times fixtures re-sync, unless
something explicitly deletes it. This patch is that explicit delete, so
it happens automatically on migrate everywhere this app deploys, not just
on whichever site someone remembers to clean up by hand.

Idempotent: only deletes if it's still there.
"""

import frappe


def execute():
	name = "Appointment-custom_contractor_person"
	if not frappe.db.exists("Custom Field", name):
		return

	frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
	frappe.db.commit()

	logger = frappe.logger("upande_security", allow_site=True)
	logger.info("upande_security remove_dead_contractor_person_field: deleted " + name)
	print("upande_security remove_dead_contractor_person_field: deleted " + name)
