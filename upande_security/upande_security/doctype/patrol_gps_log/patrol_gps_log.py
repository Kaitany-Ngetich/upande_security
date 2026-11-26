# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import time

import frappe
from frappe.model.document import Document

CLEAR_BATCH = 5000
CLEAR_BUDGET_SEC = 60


class PatrolGPSLog(Document):
	@staticmethod
	def clear_old_logs(days=90):
		"""Lets Log Settings list Patrol GPS Log (~200,000 points a day). Log Settings clears every log in one
		daily job that the default queue stops after a few minutes, so this deletes oldest-first in small
		committed batches and stops at its time budget: a backlog shrinks over a few nights instead of
		outliving the job and rolling back."""
		cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -int(days))
		stop = time.monotonic() + CLEAR_BUDGET_SEC
		cleared = 0
		while time.monotonic() < stop:
			names = frappe.get_all(
				"Patrol GPS Log",
				filters={"creation": ("<", cutoff)},
				order_by="creation asc",
				limit=CLEAR_BATCH,
				pluck="name",
			)
			if not names:
				break
			frappe.db.delete("Patrol GPS Log", {"name": ("in", names)})
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- each batch stands alone, so a stopped job keeps what it cleared
			cleared += len(names)
		return cleared


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
	# "Latest point for this guard" (the missed-check-in and checkpoint
	# schedulers, SOS nearest guard) filters by guard and orders by time. With
	# only the time index MariaDB walks it backwards until it meets the guard -
	# the whole table for a guard with no recent points, every few minutes per
	# active shift. Guard first makes each lookup a seek.
	frappe.db.add_index("Patrol GPS Log", ["external_guard", "captured_at"], "external_guard_captured_at")
	frappe.db.add_index("Patrol GPS Log", ["internal_guard", "captured_at"], "internal_guard_captured_at")
