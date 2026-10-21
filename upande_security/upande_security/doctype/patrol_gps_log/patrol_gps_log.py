# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PatrolGPSLog(Document):
	pass


def on_doctype_update():
	# Covering index for the patrol coverage grid's time-window query: lets it
	# read only the index (stored in time order) instead of rows scattered
	# across the table by their random names, which goes to disk once the
	# table outgrows the InnoDB buffer pool. tracking_mode is in it because
	# that query skips On Duty points; the older index without it is dropped.
	if frappe.db.has_index("tabPatrol GPS Log", "captured_at_coverage"):
		frappe.db.sql_ddl("ALTER TABLE `tabPatrol GPS Log` DROP INDEX `captured_at_coverage`")
	frappe.db.add_index(
		"Patrol GPS Log",
		["captured_at", "latitude", "longitude", "gps_accuracy", "tracking_mode"],
		"captured_at_coverage_mode",
	)
	# Playback asks for one FARM over a time range, and farm is not in the
	# index above - so MariaDB had to range-scan every point in the window
	# and throw away the other farms' rows: EXPLAIN reported 449,502 rows
	# examined for a 40-day window on a farm holding 2,162 of them, which
	# timed the request out. Farm first makes that a seek.
	frappe.db.add_index(
		"Patrol GPS Log",
		["farm", "captured_at"],
		"farm_captured_at",
	)
