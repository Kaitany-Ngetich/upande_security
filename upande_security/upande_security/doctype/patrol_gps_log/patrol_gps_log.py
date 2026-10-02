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
	# table outgrows the InnoDB buffer pool.
	frappe.db.add_index(
		"Patrol GPS Log",
		["captured_at", "latitude", "longitude", "gps_accuracy"],
		"captured_at_coverage",
	)
