# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time move: Visitor Badge, Supplier Badge and Contractor Badge become
one Gate Badge doctype, told apart by badge_type.

Every badge is copied with its own name, number, status, holder and QR
image - the names must not change: the QR printed on every card already in
circulation encodes either the name (supplier, contractor) or company +
farm + number (visitor), and the Appointment / Gate Receiving Verification /
Staff Gate Movement links store the name. Attached files, versions and
comments are re-pointed too.

Only when every badge has arrived are the old doctypes removed: their
Custom DocPerms, print formats, property setters, the DocTypes and their
tables. If a count does not match, the patch stops before deleting
anything, so it can be fixed and re-run.

Idempotent: a badge already in Gate Badge is not copied again.
"""

import frappe

TARGET = "Gate Badge"
OLD = {"Visitor Badge": "Visitor", "Supplier Badge": "Supplier", "Contractor Badge": "Contractor"}
OLD_FORMATS = ("Visitor Badge Card", "Supplier Badge Card", "Contractor Badge Card")
CUSTOM_FIELDS = ("Appointment-custom_visitor_badge", "Appointment-custom_supplier_badge")
STATUSES = ("Available", "Issued", "Lost")


def execute():
	present = [dt for dt in OLD if frappe.db.table_exists(dt)]
	for dt in present:
		_copy(dt, OLD[dt])

	for dt in present:
		expected = frappe.db.sql(f"SELECT COUNT(*) FROM `tab{dt}`")[0][0]
		arrived = frappe.db.sql(
			f"SELECT COUNT(*) FROM `tab{dt}` o JOIN `tab{TARGET}` g ON g.name = o.name"
		)[0][0]
		if arrived != expected:
			frappe.throw(f"{dt}: only {arrived} of {expected} badges reached {TARGET} - nothing deleted.")

	for field in CUSTOM_FIELDS:
		if frappe.db.exists("Custom Field", field):
			frappe.db.set_value("Custom Field", field, "options", TARGET)

	old = list(OLD)
	frappe.db.sql("UPDATE `tabFile` SET attached_to_doctype = %s WHERE attached_to_doctype IN %s", (TARGET, old))
	frappe.db.sql("UPDATE `tabVersion` SET ref_doctype = %s WHERE ref_doctype IN %s", (TARGET, old))
	frappe.db.sql("UPDATE `tabComment` SET reference_doctype = %s WHERE reference_doctype IN %s", (TARGET, old))

	for name in frappe.get_all("Custom DocPerm", filters={"parent": ["in", old]}, pluck="name"):
		frappe.delete_doc("Custom DocPerm", name, ignore_permissions=True, force=True)
	for name in frappe.get_all("Property Setter", filters={"doc_type": ["in", old]}, pluck="name"):
		frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
	for name in OLD_FORMATS:
		if frappe.db.exists("Print Format", name):
			frappe.delete_doc("Print Format", name, ignore_permissions=True, force=True)

	for dt in old:
		if frappe.db.exists("DocType", dt):
			frappe.delete_doc("DocType", dt, ignore_missing=True, force=True)
		if frappe.db.table_exists(dt):
			frappe.db.sql_ddl(f"DROP TABLE `tab{dt}`")

	frappe.clear_cache()


def _copy(dt, badge_type):
	columns = set(frappe.db.get_table_columns(dt))
	for row in frappe.db.sql(f"SELECT * FROM `tab{dt}`", as_dict=True):
		if frappe.db.exists(TARGET, row.name):
			continue
		get = lambda f: row.get(f) if f in columns else None  # noqa: E731
		status = get("status") if get("status") in STATUSES else None
		held = bool(get("current_appointment") or get("current_receiving") or get("holder_name"))
		if not status:
			# e.g. the retired "Unassigned"/"Active" supplier statuses
			status = "Issued" if held else "Available"
		doc = frappe.get_doc(
			{
				"doctype": TARGET,
				"name": row.name,
				"badge_type": badge_type,
				"badge_number": get("badge_number"),
				"company": get("company"),
				"farm": get("farm") if badge_type == "Visitor" else None,
				"status": status,
				"qr_image": get("qr_image"),
				"current_appointment": get("current_appointment"),
				"current_receiving": get("current_receiving"),
				"supplier": get("supplier") or get("contractor"),
				"holder_name": get("holder_name"),
				"holder_id_number": get("holder_id_number"),
				"valid_until": get("valid_until"),
				"issued_at": get("issued_at"),
				"issued_by": get("issued_by"),
				"owner": row.owner,
				"creation": row.creation,
				"modified": row.modified,
				"modified_by": row.modified_by,
			}
		)
		doc.db_insert()
