# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time data fix: move Supplier Badges off the retired "Active" status.

Before 2026-10-01 a Supplier Badge belonged permanently to one supplier and
sat at status "Active". It is now a reusable pool badge (Available / Issued /
Lost, same as Visitor Badge): Issued to whoever holds it for one visit or
delivery, released back to Available with supplier cleared afterwards - see
supplier_badge_qr.auto_sync_status.

"Active" is no longer a status option, but sites that had those badges kept
the value, and the "TEMP BRIDGE - Search Receiving By Supplier Badge" Server
Script kept them scanning. With that script deleted
(delete_migrated_security_scripts), search_receiving_by_supplier_badge only
accepts Issued badges, so each "Active" badge is normalised the way a release
would leave it:

- held (current_appointment or current_receiving set) -> Issued, supplier kept
- not held -> Available, supplier cleared, as Contractor Gate Checkout and
  confirm_receiving_departure do on release

Written with db.set_value, so no validate hook or QR regeneration runs.

Idempotent: only touches badges still at "Active".
"""

import frappe


def execute():
	if not frappe.db.table_exists("Supplier Badge"):
		return

	for badge in frappe.get_all(
		"Supplier Badge",
		filters={"status": "Active"},
		fields=["name", "current_appointment", "current_receiving"],
	):
		if badge.current_appointment or badge.current_receiving:
			frappe.db.set_value("Supplier Badge", badge.name, "status", "Issued", update_modified=False)
		else:
			frappe.db.set_value(
				"Supplier Badge",
				badge.name,
				{"status": "Available", "supplier": None},
				update_modified=False,
			)

	frappe.db.commit()
