# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

# A Cancelled shift never put anyone on a farm, so it can't explain a patrol.
MATCHABLE_SHIFT_STATUSES = ("Scheduled", "Active", "Ended")


class PatrolReport(Document):
	def validate(self):
		self.pull_window_from_gps_log()
		self.resolve_shift_assignment()
		self.pull_farm_and_personel_from_shift()
		self.count_gps_points()
		self.stamp_review()

	# ------------------------------------------------------------------ GPS
	def pull_window_from_gps_log(self):
		"""Patrol window and guard identity come from the uploaded GPS trail.

		The trail is the only record of when the guard actually walked and who
		they were, so it is authoritative for these — not hand entry.
		"""
		if not self.patrol:
			return

		rows = frappe.db.sql(
			"""
			SELECT MIN(captured_at) AS first_fix,
			       MAX(captured_at) AS last_fix,
			       MAX(internal_guard) AS internal_guard,
			       MAX(external_guard) AS external_guard
			FROM `tabPatrol GPS Log`
			WHERE patrol = %s
			""",
			(self.patrol,),
			as_dict=True,
		)
		if not rows or not rows[0].first_fix:
			return

		row = rows[0]
		self.started_at = row.first_fix
		self.ended_at = row.last_fix
		self.internal_guard = row.internal_guard
		self.external_guard = row.external_guard

	# ---------------------------------------------------------------- Shift
	def resolve_shift_assignment(self):
		"""Find the Shift Planning entry that covers this patrol.

		Matched on the guard from the GPS trail plus an overlap with the patrol
		window. Left alone if a supervisor has already picked one by hand.
		"""
		if self.shift_assignment:
			return
		if not (self.started_at and self.ended_at):
			return

		if self.internal_guard:
			guard_field, guard_value = "internal_guard", self.internal_guard
		elif self.external_guard:
			guard_field, guard_value = "external_guard", self.external_guard
		else:
			return

		matches = frappe.get_all(
			"Security Guard Shift Assignment",
			filters={
				guard_field: guard_value,
				"status": ["in", MATCHABLE_SHIFT_STATUSES],
				"start_date": ["<=", self.ended_at],
				"end_date": [">=", self.started_at],
			},
			fields=["name"],
			order_by="start_date desc",
			limit_page_length=1,
		)
		if matches:
			self.shift_assignment = matches[0].name

	def pull_farm_and_personel_from_shift(self):
		"""Farm and personel are the shift's facts, not the patrol's.

		Shift Planning is what assigns a guard to a farm, so it owns both. If no
		shift matched they stay blank rather than being guessed from the trail —
		a blank field is honest, a wrong farm is not.
		"""
		if not self.shift_assignment:
			self.farm = None
			self.personel = None
			return

		shift = frappe.db.get_value(
			"Security Guard Shift Assignment",
			self.shift_assignment,
			["farm", "security_guard"],
			as_dict=True,
		)
		if not shift:
			return

		self.farm = shift.farm
		self.personel = shift.security_guard

	# ----------------------------------------------------------------- misc
	def count_gps_points(self):
		self.points_logged = (
			frappe.db.count("Patrol GPS Log", {"patrol": self.patrol}) if self.patrol else 0
		)

	def stamp_review(self):
		"""Record who reviewed it, the moment the status leaves Submitted."""
		if self.status == "Submitted":
			self.reviewed_by = None
			self.reviewed_on = None
			return

		previous = self.get_doc_before_save()
		if previous and previous.status == self.status and self.reviewed_by:
			return

		self.reviewed_by = frappe.session.user
		self.reviewed_on = now_datetime()
