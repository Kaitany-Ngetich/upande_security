# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time cleanup: retire the standalone Near Miss Report doctype.

Near misses are recorded as Incident Reports with Nature of Incident =
"Near Miss" (the "Near Misses" workspace shortcut already opens that
filtered list - 84b5856). The doctype's folder was removed from this app,
but a standard doctype that disappears from code stays behind in every
site's DB - its row, its table, and the Server Script that wrote to it.
This removes them:

- Server Script "Report Near Miss" (API report_near_miss - nothing in this
  app, its web pages or dashboards calls it). It is no longer in the
  fixtures, but fixture sync never deletes.
- DocType "Near Miss Report" and its table - only when it holds no
  records. A site that does have some keeps the doctype and gets an Error
  Log entry instead, so nothing is lost silently; move them to Incident
  Report and re-run.

"Security Analytics Summary" now counts near misses from Incident Report,
and the Security Navigation tile / Patrol Map rail link point at the
filtered Incident Report list, so nothing still reads the old doctype.

Idempotent: only deletes whatever is still there.
"""

import frappe

DOCTYPE = "Near Miss Report"
SERVER_SCRIPT = "Report Near Miss"


def execute():
	if frappe.db.exists("Server Script", SERVER_SCRIPT):
		frappe.delete_doc("Server Script", SERVER_SCRIPT, ignore_permissions=True, force=True)

	if frappe.db.exists("DocType", DOCTYPE):
		records = frappe.db.count(DOCTYPE) if frappe.db.table_exists(DOCTYPE) else 0
		if records:
			frappe.log_error(
				title="Near Miss Report not retired",
				message=f"{records} Near Miss Report record(s) still exist - move them to Incident Report "
				"(Nature of Incident = Near Miss) and re-run upande_security.patches.retire_near_miss_report.",
			)
		else:
			frappe.delete_doc("DocType", DOCTYPE, ignore_missing=True, force=True)

	frappe.db.commit()
