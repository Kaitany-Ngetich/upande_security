# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time move: every carried item now lives in Registered Personal Item, linked
to the gate record it came in on, instead of a child table per doctype.

Copies each Appointment Carried Item row (Appointment.custom_carried_items)
into a Registered Personal Item linked to its Appointment - exit status, times and
who checked it kept - then removes what is left of the old child table, the
same way drop_contractor_compliance_document does:

- Custom Field "Appointment-custom_carried_items" (fixture sync never
  deletes one).
- DocType "Appointment Carried Item" and its table. delete_doc leaves the
  table behind, so it is dropped explicitly - after the copy.

Idempotent: a row already copied (same Appointment, item, carried_by and
creation) is not copied twice, and only what is still there is deleted.
"""

import frappe

OLD = "Appointment Carried Item"
NEW = "Registered Personal Item"
CUSTOM_FIELD = "Appointment-custom_carried_items"


def execute():
	if frappe.db.table_exists(OLD):
		_copy_rows()

	if frappe.db.exists("Custom Field", CUSTOM_FIELD):
		frappe.delete_doc("Custom Field", CUSTOM_FIELD, ignore_permissions=True, force=True)

	if frappe.db.exists("DocType", OLD):
		frappe.delete_doc("DocType", OLD, ignore_missing=True, force=True)

	if frappe.db.table_exists(OLD):
		frappe.db.sql_ddl(f"DROP TABLE `tab{OLD}`")


def _copy_rows():
	columns = set(frappe.db.get_table_columns(OLD))
	rows = frappe.db.sql(f"SELECT * FROM `tab{OLD}` WHERE parenttype = 'Appointment'", as_dict=True)
	for row in rows:
		if frappe.db.exists(
			NEW,
			{
				"reference_doctype": "Appointment",
				"reference_name": row.parent,
				"item": row.item,
				"carried_by": row.carried_by,
				"entry_time": row.creation,
			},
		):
			continue
		appt = frappe.db.get_value(
			"Appointment",
			row.parent,
			["custom_visitor_type", "custom_farmunit", "custom_meet_with_farm", "custom_company", "custom_meet_with_company"],
			as_dict=True,
		)
		if not appt:
			continue
		farm = appt.custom_farmunit or appt.custom_meet_with_farm
		if farm and not frappe.db.exists("Farm", farm):
			farm = None
		doc = frappe.new_doc(NEW)
		doc.update(
			{
				"party_type": appt.custom_visitor_type
				if appt.custom_visitor_type in ("Visitor", "Customer", "Contractor")
				else "Visitor",
				"carried_by": row.carried_by,
				"reference_doctype": "Appointment",
				"reference_name": row.parent,
				"farm": farm,
				"company": appt.custom_company
				or appt.custom_meet_with_company
				or (frappe.db.get_value("Farm", farm, "company") if farm else None),
				"item": row.item,
				"qty": row.qty or 1,
				"serial_notes": row.serial_notes,
				"declared_at": row.get("declared_at") if "declared_at" in columns else "Entry",
				"entry_time": row.creation,
				"recorded_by": row.owner,
				"exit_status": row.exit_status or "Inside",
				"exit_time": row.exit_time,
				"exit_checked_by": row.exit_checked_by,
			}
		)
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
