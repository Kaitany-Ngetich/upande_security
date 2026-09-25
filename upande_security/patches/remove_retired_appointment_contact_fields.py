# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time cleanup: the four Appointment contact fields retired on
2026-09-21 (d8f45c5, b44ce95) were only dropped from this app's fixture
allowlist - and a fixture sync only ever inserts/updates, it never deletes -
so every site that already had them kept them:

- custom_meet_with_phone / custom_meet_with_wa (Meet With Phone / WhatsApp
  No) - replaced by the host's own Employee contact details
  (689ce90 repointed the Host Alert notification off them).
- custom_secretary_email / custom_secretary_wa (Company Secretary Email /
  WhatsApp No) - computed from a hardcoded secretary lookup; retired by
  decision along with the alerts that used them.

Also deletes the WhatsApp Notification "Visitor at Reception - Secretary
Alert (Karen Roses)": b44ce95 disabled rather than deleted it because
frappe_whatsapp isn't installed locally, but its field_name and condition
read custom_secretary_wa, so it can't outlive that field. It's no longer in
the fixture allowlist either. Guarded - frappe_whatsapp isn't on every site.

Idempotent: only deletes whatever is still there.
"""

import frappe

FIELDS = (
	"Appointment-custom_meet_with_phone",
	"Appointment-custom_meet_with_wa",
	"Appointment-custom_secretary_email",
	"Appointment-custom_secretary_wa",
)
SECRETARY_ALERT = "Visitor at Reception - Secretary Alert (Karen Roses)"


def execute():
	if frappe.db.exists("DocType", "WhatsApp Notification") and frappe.db.exists(
		"WhatsApp Notification", SECRETARY_ALERT
	):
		frappe.delete_doc("WhatsApp Notification", SECRETARY_ALERT, ignore_permissions=True, force=True)

	for name in FIELDS:
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)

	frappe.db.commit()
