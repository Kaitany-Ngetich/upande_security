# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate

from upande_security.utils.holidays import is_guard_off

# Rows in either of these states are still "not yet committed" — a
# regeneration is free to wipe and rebuild them. Anything else (Applied,
# Failed) represents a real outcome from a previous apply_rotation() run and
# must never be silently discarded by a later generate_preview() call.
REGENERATABLE_ROW_STATUSES = ("Pending", "Skipped")


class SecurityGuardRotationPlan(Document):
	def validate(self):
		self.validate_rotation_farms()
		self.validate_dates()
		self.validate_rotation_interval()
		self.validate_external_guard()

	def validate_rotation_farms(self):
		if not self.rotation_farms:
			frappe.throw(_("Add at least one farm to the rotation before saving."), title=_("No Rotation Farms"))

	def validate_dates(self):
		if self.start_date and self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End Date cannot be before Start Date."), title=_("Invalid Date Range"))

	def validate_rotation_interval(self):
		if not self.rotation_interval_days or self.rotation_interval_days <= 0:
			frappe.throw(
				_("Rotation Interval (Days) must be a positive number of days."),
				title=_("Invalid Rotation Interval"),
			)

	def validate_external_guard(self):
		# external_guard is a Link -> Security Guard, so it can never point at
		# an Employee record by construction (that's a different doctype/link
		# target entirely) - this check exists to catch a blank or dangling
		# link (e.g. the guard record was renamed/deleted after being picked
		# on this form), not to guard against an Employee being chosen.
		if self.external_guard and not frappe.db.exists("Security Guard", self.external_guard):
			frappe.throw(
				_("{0} is not a valid Security Guard record.").format(self.external_guard),
				title=_("Invalid External Guard"),
			)

	@frappe.whitelist()
	def generate_preview(self):
		"""(Re)build preview_rows for this plan's start_date..end_date window.

		Walks the window day by day, cycling rotation_farms in order and
		switching farm every rotation_interval_days days (day 0 sits on
		farms[0]; after rotation_interval_days days it moves to farms[1],
		wrapping back to farms[0] after the last farm in the list). Every
		date is checked against the guard's own Security Guard Off Days
		record via is_guard_off() - an off day still gets a preview row
		(is_off_day=1, status="Skipped") so the Security Head can SEE the gap
		instead of it silently vanishing; everything else is status="Pending".

		Idempotency choice: this plan must still be status="Draft", and
		every existing preview row must still be "Pending" or "Skipped"
		(see REGENERATABLE_ROW_STATUSES) - i.e. nothing has been committed
		into a real Shift Assignment yet. Once any row is "Applied" or
		"Failed" from a previous apply_rotation() run, regeneration is
		blocked outright rather than attempting to merge old and new rows;
		the remaining window belongs in a new Rotation Plan instead. This
		is simpler to get right than a partial-merge and matches how the
		task described "keep it simple" as an acceptable v1 choice.

		Returns {"rows": <int total preview rows>, "off_days": <int marked
		Skipped>}.
		"""
		if self.status != "Draft":
			frappe.throw(
				_("This plan is no longer Draft - the preview can't be regenerated once it's been applied or cancelled."),
				title=_("Plan Not Draft"),
			)
		if any(row.status not in REGENERATABLE_ROW_STATUSES for row in self.preview_rows):
			frappe.throw(
				_(
					"This plan already has Applied or Failed rows from a previous run - "
					"start a new Rotation Plan for the remaining window instead of "
					"regenerating this one."
				),
				title=_("Cannot Regenerate"),
			)

		self.validate_rotation_farms()
		self.validate_dates()
		self.validate_rotation_interval()

		# (farm, block) pairs, not just farm — a guard can rotate to the same
		# farm at different times with a different block, or different farms
		# each with their own block, so block travels with its farm here
		# rather than living as one plan-wide value.
		stops = [(row.farm, row.block) for row in self.rotation_farms]

		self.set("preview_rows", [])

		off_days = 0
		current = getdate(self.start_date)
		last = getdate(self.end_date)
		day_index = 0
		while current <= last:
			farm, block = stops[(day_index // self.rotation_interval_days) % len(stops)]
			off_day = is_guard_off(self.external_guard, current)

			row = self.append("preview_rows", {})
			row.rotation_date = current
			row.farm = farm
			row.block = block
			row.is_off_day = 1 if off_day else 0
			row.status = "Skipped" if off_day else "Pending"
			if off_day:
				off_days += 1

			current = add_days(current, 1)
			day_index += 1

		self.save()
		return {"rows": len(self.preview_rows), "off_days": off_days}

	@frappe.whitelist()
	def apply_rotation(self):
		"""Turn every preview_rows entry currently "Pending" into a real,
		single-day Security Guard Shift Assignment (one record per day,
		matching how this doctype is otherwise used) - security_guard is
		always "External Guard", start_date == end_date == the row's date,
		and start_time/end_time always come from this plan (never left
		date-only - see the module docstring's note on the kaitetv16 "every
		shift shows 03:00" bug this must not repeat).

		"Skipped" (off-day) rows never produce a Shift Assignment - that is
		the entire point of marking them off. A failure creating one day's
		Shift Assignment (e.g. an overlap generate_preview() couldn't have
		known about, created by something else after the preview was built)
		is caught per-row, marks that row "Failed", and does not stop the
		rest of the apply.

		Sets this plan's own status to "Applied" once no "Pending" rows
		remain - a partial apply with some "Failed" rows still counts as
		done, just imperfectly; the failure count is returned so the caller
		can surface it to the Security Head.

		Returns {"applied": <int>, "failed": <int>, "skipped": <int>,
		"status": <this plan's status after the run>}.
		"""
		applied = 0
		failed = 0
		skipped = sum(1 for row in self.preview_rows if row.status == "Skipped")

		for row in self.preview_rows:
			if row.status != "Pending":
				continue
			try:
				shift = frappe.get_doc(
					{
						"doctype": "Security Guard Shift Assignment",
						"security_guard": "External Guard",
						"external_guard": self.external_guard,
						"farm": row.farm,
						"block": row.block,
						"shift_type": self.shift_type,
						"start_date": row.rotation_date,
						"end_date": row.rotation_date,
						"start_time": self.start_time,
						"end_time": self.end_time,
						"remarks": "Generated by Rotation Plan " + self.name,
					}
				)
				shift.insert()
				row.status = "Applied"
				applied += 1
			except Exception as e:
				# One bad day (most likely the overlap check in Security
				# Guard Shift Assignment.validate()) must never stop the
				# rest of the rotation from being applied.
				frappe.log_error("Security Guard Rotation Plan apply_rotation row", str(e))
				row.status = "Failed"
				failed += 1

		if not any(r.status == "Pending" for r in self.preview_rows):
			self.status = "Applied"

		self.save()
		return {"applied": applied, "failed": failed, "skipped": skipped, "status": self.status}

	@frappe.whitelist()
	def generate_and_apply(self):
		"""One-click path for mode == "Automatic": generate_preview()
		immediately followed by apply_rotation(), so an Automatic plan never
		needs a human to look at the preview before it's committed - see
		security_guard_rotation_plan.js's single "Generate & Apply" button
		for Automatic mode, versus the separate "Generate Preview" /
		"Apply Rotation" buttons Semi-Automatic mode gets.

		Returns {"preview": <generate_preview()'s return>, "apply":
		<apply_rotation()'s return>}.
		"""
		preview_result = self.generate_preview()
		apply_result = self.apply_rotation()
		return {"preview": preview_result, "apply": apply_result}
