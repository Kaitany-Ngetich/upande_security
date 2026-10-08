# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time cleanup: drop the Contractor Compliance Document child table.

It was only ever used as Supplier.custom_compliance_documents, read by the
daily check_contractor_document_expiry task. The doctype folder, the task
and the Custom Field fixture were removed from this app, but a standard
doctype that disappears from code stays behind in every site's DB, and
fixture sync never deletes a Custom Field. This removes:

- Custom Field "Supplier-custom_compliance_documents" (and its column).
- DocType "Contractor Compliance Document" and its table, rows included.
  It is a child table with no controller left in code, so keeping it
  around would break loading any Supplier that still has rows. delete_doc
  leaves the table behind (it waits for bench trim-database), so it is
  dropped explicitly.
- The Scheduled Job Type for the retired expiry task.

Idempotent: only deletes whatever is still there.
"""

import frappe

DOCTYPE = "Contractor Compliance Document"
CUSTOM_FIELD = "Supplier-custom_compliance_documents"
TASK = "upande_security.tasks.check_contractor_document_expiry"


def execute():
	if frappe.db.exists("Custom Field", CUSTOM_FIELD):
		frappe.delete_doc("Custom Field", CUSTOM_FIELD, ignore_permissions=True, force=True)

	if frappe.db.exists("DocType", DOCTYPE):
		frappe.delete_doc("DocType", DOCTYPE, ignore_missing=True, force=True)

	if frappe.db.table_exists(DOCTYPE):
		frappe.db.sql_ddl(f"DROP TABLE `tab{DOCTYPE}`")

	for job in frappe.get_all("Scheduled Job Type", filters={"method": TASK}, pluck="name"):
		frappe.delete_doc("Scheduled Job Type", job, ignore_permissions=True, force=True)

	frappe.db.commit()
