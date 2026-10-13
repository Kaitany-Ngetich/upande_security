# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Pre-model-sync: drop the Desk-built Asset Scan Log so the app's own replaces it.

Asset Scan Log was first built in Desk (custom=1) and never fixture-tracked,
so it only ever existed on the site it was built on - every other site's
scan_asset failed writing its log row. It is now an app-owned doctype linked
to ERPNext Asset instead of Security Asset, and model sync will not take over
a custom DocType of the same name, so the old one goes first. Its rows point
at Security Asset codes that no longer mean anything to scan_asset.

No-op where the doctype is absent or already app-owned.
"""

import frappe


def execute():
	if frappe.db.get_value("DocType", "Asset Scan Log", "custom"):
		frappe.delete_doc("DocType", "Asset Scan Log", ignore_permissions=True, force=True)
		# delete_doc leaves a custom DocType's table behind, and model sync
		# then tries to ALTER its Data columns (latitude, longitude,
		# gps_accuracy) to Float - which fails on the existing values.
		frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabAsset Scan Log`")
		frappe.db.commit()
