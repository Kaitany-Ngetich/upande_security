# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, get_time, getdate

from upande_security.api.shift_times import standard_times
from upande_security.utils.holidays import is_guard_off


def _ends_next_day(start_time, end_time):
	"""An overnight shift (Night 17:00 -> 06:30) ends on the day after it starts."""
	return get_time(str(end_time)) <= get_time(str(start_time))

class SecurityGuardRotationPlan(Document):
	def validate(self):
		self.fill_shift_times()
		self.validate_rotation_farms()
		self.validate_dates()
		self.validate_rotation_interval()
		self.validate_external_guard()

	def shift_cycle(self):
		"""The shift types this plan moves through, in order - just its own
		shift_type unless Rotate Shifts is on."""
		if cint(self.rotate_shifts):
			return [row.shift_type for row in self.shift_sequence if row.shift_type]
		return [self.shift_type] if self.shift_type else []

	def fill_shift_times(self):
		"""Shift times are never typed by hand: they come from Security Ops
		Settings > Standard Shift Times. A rotating plan's own shift_type is
		its first shift, so the plan still reads as where the guard starts."""
		if cint(self.rotate_shifts):
			cycle = self.shift_cycle()
			if not cycle:
				frappe.throw(_("Add the shifts to rotate through under Shift Sequence."), title=_("No Shift Sequence"))
			if cint(self.shift_change_every_days) <= 0:
				frappe.throw(
					_("Change Shift Every (Days) must be a positive number of days."), title=_("Invalid Shift Change")
				)
			self.shift_type = cycle[0]
		if self.shift_type and (not self.start_time or not self.end_time or self.has_value_changed("shift_type")):
			start, end = standard_times(self.shift_type)
			if start and end:
				self.start_time, self.end_time = start, end

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

		Idempotency choice: this plan must still be status="Draft", and no
		existing preview row may be "Applied" - i.e. nothing has been
		committed into a real Shift Assignment yet. A "Failed" row alone
		does NOT block this: apply_rotation() only advances status to
		"Applied" once at least one row actually succeeds, so a run that
		failed on every row leaves the plan in "Draft" with only "Failed"
		rows - safe to wipe and regenerate, since nothing real exists to
		protect. Once any row IS "Applied", regeneration is blocked outright
		rather than attempting to merge old and new rows; the remaining
		window belongs in a new Rotation Plan instead. This is simpler to
		get right than a partial-merge and matches how the task described
		"keep it simple" as an acceptable v1 choice.

		Returns {"rows": <int total preview rows>, "off_days": <int marked
		Skipped>}.
		"""
		if self.status != "Draft":
			frappe.throw(
				_("This plan is no longer Draft - the preview can't be regenerated once it's been applied or cancelled."),
				title=_("Plan Not Draft"),
			)
		if any(row.status == "Applied" for row in self.preview_rows):
			frappe.throw(
				_(
					"This plan already has Applied rows from a previous run - "
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
		# Shifts change on their own clock, independent of the farm rotation.
		cycle = self.shift_cycle()
		rotating = cint(self.rotate_shifts) and len(cycle) > 0
		shift_every = max(cint(self.shift_change_every_days), 1)

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
			if rotating:
				row.shift_type = cycle[(day_index // shift_every) % len(cycle)]
				row.start_time, row.end_time = standard_times(row.shift_type)
			else:
				row.shift_type = self.shift_type
				row.start_time, row.end_time = self.start_time, self.end_time
			row.is_off_day = 1 if off_day else 0
			row.status = "Skipped" if off_day else "Pending"
			if off_day:
				off_days += 1

			current = add_days(current, 1)
			day_index += 1

		covers = _covers_by_date(self.external_guard, [r.rotation_date for r in self.preview_rows if r.is_off_day])
		for r in self.preview_rows:
			if r.is_off_day:
				r.cover_guard, r.cover_guard_name = covers.get(getdate(r.rotation_date), (None, None))

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
		remain AND at least one row actually succeeded - a partial apply
		with some "Failed" rows still counts as done, just imperfectly.
		A run where every row failed leaves the plan in "Draft" instead of
		"Applied", since nothing real was committed - otherwise a plan
		that failed 100% of the time would be permanently stuck (Draft-only
		regeneration would refuse it, but it has nothing worth protecting
		either). The failure count is returned so the caller can surface it
		to the Security Head.

		Off days are not covered here, but they are not passed over in
		silence either: the ones still without cover come back as
		uncovered_off_days, so the form can offer Fill Off Days.

		Returns {"applied": <int>, "failed": <int>, "skipped": <int>,
		"status": <this plan's status after the run>, "uncovered_off_days":
		[{"row", "date", "farm", "shift_type"}]}.
		"""
		applied = 0
		failed = 0
		skipped = sum(1 for row in self.preview_rows if row.status == "Skipped")

		# An overnight shift (e.g. Night: 18:00 -> 06:00) ends on the calendar
		# day AFTER it starts — end_date must roll forward one day whenever
		# end_time is not strictly after start_time, or the generated record
		# has its end sitting before its start on the same day, which makes
		# derive_status() jump straight from Scheduled to Ended the moment
		# the shift begins, never showing Active during the actual shift.
		# Mirrors the same rule tasks.sync_shifts_from_hr_roster() already
		# applies for HR-mirrored Internal Guard shifts.
		for row in self.preview_rows:
			if row.status != "Pending":
				continue
			# Each day carries its own shift (a rotating plan changes it);
			# rows from before that existed fall back to the plan's.
			shift_type = row.shift_type or self.shift_type
			start_time = row.start_time or self.start_time
			end_time = row.end_time or self.end_time
			end_date_offset = 1 if _ends_next_day(start_time, end_time) else 0
			try:
				shift = frappe.get_doc(
					{
						"doctype": "Security Guard Shift Assignment",
						"security_guard": "External Guard",
						"external_guard": self.external_guard,
						"farm": row.farm,
						"block": row.block,
						"shift_type": shift_type,
						"start_date": row.rotation_date,
						"end_date": add_days(row.rotation_date, end_date_offset),
						"start_time": start_time,
						"end_time": end_time,
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

		if applied > 0 and not any(r.status == "Pending" for r in self.preview_rows):
			self.status = "Applied"

		uncovered = self.sync_off_day_covers()
		self.save()
		return {
			"applied": applied,
			"failed": failed,
			"skipped": skipped,
			"status": self.status,
			"uncovered_off_days": uncovered,
		}

	def sync_off_day_covers(self):
		"""Set each off-day row's cover from the Shift Assignments (a cover
		can also be set or removed on the Shift Schedule grid) and return the
		off days that have none."""
		off_rows = [r for r in self.preview_rows if r.is_off_day]
		covers = _covers_by_date(self.external_guard, [r.rotation_date for r in off_rows])
		uncovered = []
		for r in off_rows:
			r.cover_guard, r.cover_guard_name = covers.get(getdate(r.rotation_date), (None, None))
			if not r.cover_guard:
				uncovered.append(
					{"row": r.name, "date": str(r.rotation_date), "farm": r.farm, "shift_type": r.shift_type}
				)
		return uncovered

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


@frappe.whitelist()
def toggle_preview_row_off_day(plan_name, row_name, mark_off, cover_guard=None):
	"""Check/uncheck one preview row's "Off Day" box directly, whether that
	plan is still Draft or already Applied - reuses the exact same action as
	the Shift Schedule grid's own off-day checkbox (toggle_guard_day), just
	triggered from this table instead, and keeping the row's own farm/block
	for that day rather than the guard's home farm (a rotation can move a
	guard across multiple farms on different days, unlike the grid's
	single-farm-per-guard toggle).

	Real effect either way: cancels or creates a real Shift Assignment for
	the guard on this row's date, fills/removes the reliever, and updates
	the guard's Security Guard Off Days list - not just a flag on this
	table. Safe to call on a Draft plan too: it updates the same Off Days
	list generate_preview() reads from, so a later Generate Preview click
	still reflects whatever was picked here.

	Deliberately a plain whitelisted function, not a Document method -
	calling a Document method from the client goes through
	frappe.client.run_doc_method, which syncs the ENTIRE doc (every row)
	back into the form on every response, visibly repainting the whole
	preview table for a single-row edit. A plain frappe.call has no such
	side effect, and frappe.db.set_value below touches only this one row.

	cover_guard is the guard the planner picked to cover the day off ("" or
	"none" for no cover); see toggle_guard_day.

	Returns {is_off_day, status} for this row, plus whatever
	toggle_guard_day() itself returned (state/covered_by/etc, for the
	client to show).
	"""
	from upande_security.api.shift_schedule import toggle_guard_day

	row = frappe.db.get_value(
		"Security Guard Rotation Preview Row",
		row_name,
		["parent", "rotation_date", "farm", "shift_type", "start_time", "end_time"],
		as_dict=True,
	)
	if not row or row.parent != plan_name:
		frappe.throw(_("Preview row {0} not found on plan {1}.").format(row_name, plan_name))

	plan = frappe.db.get_value("Security Guard Rotation Plan", plan_name, ["external_guard", "status"], as_dict=True)
	# On a Draft plan a day put back on duty stays Pending: Apply Rotation
	# creates its Shift Assignment, with this row's own shift and times. An
	# Applied plan's day gets its Shift Assignment straight away.
	applied = plan.status == "Applied"
	result = toggle_guard_day(
		guard=plan.external_guard,
		date=row.rotation_date,
		mark_off=mark_off,
		farm=row.farm,
		shift_type=row.shift_type,
		start_time=row.start_time,
		end_time=row.end_time,
		create_shift=1 if applied else 0,
		cover_guard=cover_guard,
	)

	is_off_day = 1 if cint(mark_off) else 0
	status = "Skipped" if is_off_day else ("Applied" if applied else "Pending")
	covered = is_off_day and result.get("state") == "off_covered"
	cover = {
		"cover_guard": result.get("covered_by") if covered else None,
		"cover_guard_name": result.get("covered_by_name") if covered else None,
	}
	frappe.db.set_value(
		"Security Guard Rotation Preview Row", row_name,
		{"is_off_day": is_off_day, "status": status, **cover},
		update_modified=False,
	)
	frappe.db.commit()

	return {"is_off_day": is_off_day, "status": status, **result, **cover}


def _covers_by_date(guard, dates):
	"""{date: (cover guard, their name)} for guard's covered days off among dates."""
	dates = [getdate(d) for d in dates if d]
	if not guard or not dates:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT sa.start_date, sa.external_guard, g.full_name
		FROM `tabSecurity Guard Shift Assignment` sa
		LEFT JOIN `tabSecurity Guard` g ON g.name = sa.external_guard
		WHERE sa.covering_for = %(guard)s AND sa.start_date IN %(dates)s
		""",
		{"guard": guard, "dates": tuple(dates)},
		as_dict=True,
	)
	return {getdate(r.start_date): (r.external_guard, r.full_name) for r in rows}


def _plan_off_rows(plan_name):
	from upande_security.api.relievers import require_planner

	require_planner()
	plan = frappe.get_doc("Security Guard Rotation Plan", plan_name)
	plan.check_permission("read")
	return plan, sorted((r for r in plan.preview_rows if r.is_off_day), key=lambda r: getdate(r.rotation_date))


@frappe.whitelist()
def get_off_day_cover_options(plan_name):
	"""For the Fill Off Days dialog: every off-day row of the plan with its
	ranked relievers (previous relievers first) and one pre-selected.

	The pre-selection walks the days in date order and takes the best
	available reliever not already picked for an overlapping shift on another
	row; a day already covered keeps its cover. A day where nobody is free
	pre-selects no cover.
	"""
	from upande_security.api.relievers import cover_window, rank_relievers

	plan, off_rows = _plan_off_rows(plan_name)
	covers = _covers_by_date(plan.external_guard, [r.rotation_date for r in off_rows])
	picked = {}  # guard -> [windows already given to them in this dialog]
	out = []
	for r in off_rows:
		ranked = rank_relievers(
			plan.external_guard, r.rotation_date, farm=r.farm, shift_type=r.shift_type or plan.shift_type,
			start_time=r.start_time or plan.start_time, end_time=r.end_time or plan.end_time,
		)
		win = ranked.window
		current, current_name = covers.get(getdate(r.rotation_date), (None, None))

		def clashes(g):
			return any(w[0] < win[1] and w[1] > win[0] for w in picked.get(g, []))

		selected = current
		if not selected:
			for c in ranked.suggestions:
				if c["available"] and not clashes(c["guard"]):
					selected = c["guard"]
					break
		if selected:
			picked.setdefault(selected, []).append(win)

		# Every free guard, for the dialog's search; `shortlist` marks the few
		# it lists up front (previous relievers, the designated one, the best
		# free guard).
		options = [
			{
				"guard": c["guard"],
				"full_name": c["full_name"],
				"home_farm": c["home_farm"],
				"available": c["available"],
				"on_off_day": c["on_off_day"],
				"previous": c["previous"],
				"designated": c["designated"],
				"shortlist": c["shortlist"] or c["guard"] in (current, selected),
				"reason": c["busy_reason"] if not c["available"] else c["reason"],
			}
			for c in ranked.suggestions
			if c["available"] or c["guard"] == current
		]
		if current and not any(o["guard"] == current for o in options):
			options.insert(0, {"guard": current, "full_name": current_name, "available": 1, "on_off_day": 0,
				"previous": None, "designated": 0, "shortlist": 1, "reason": ""})
		out.append(
			{
				"row": r.name,
				"date": str(r.rotation_date),
				"farm": r.farm,
				"shift_type": ranked.shift_type,
				"times": ranked.start_time + "-" + ranked.end_time,
				"current_cover": current,
				"current_cover_name": current_name,
				"selected": selected,
				"options": options,
				"available": ranked.counts["available"],
			}
		)
	return {"guard": plan.external_guard, "rows": out}


@frappe.whitelist()
def fill_off_day_covers(plan_name, choices):
	"""Cover the plan's off days in one go. choices maps preview row name ->
	guard to cover it ("" or "none" leaves the day without cover). Each pick
	is checked free again as it is booked, so two overlapping covers for the
	same guard cannot both go through.

	Returns {"covered": [{date, guard, guard_name}], "uncovered": [{date,
	reason}]}.
	"""
	from upande_security.api.shift_schedule import toggle_guard_day

	if isinstance(choices, str):
		choices = frappe.parse_json(choices)
	plan, off_rows = _plan_off_rows(plan_name)
	plan.check_permission("write")
	covered, uncovered = [], []
	for r in off_rows:
		if r.name not in choices:
			continue
		pick = (choices.get(r.name) or "").strip()
		result = toggle_guard_day(
			guard=plan.external_guard,
			date=r.rotation_date,
			mark_off=1,
			farm=r.farm,
			shift_type=r.shift_type or plan.shift_type,
			start_time=r.start_time or plan.start_time,
			end_time=r.end_time or plan.end_time,
			cover_guard=pick or "none",
		)
		is_covered = result.get("state") == "off_covered"
		frappe.db.set_value(
			"Security Guard Rotation Preview Row", r.name,
			{
				"cover_guard": result.get("covered_by") if is_covered else None,
				"cover_guard_name": result.get("covered_by_name") if is_covered else None,
			},
			update_modified=False,
		)
		if is_covered and (not pick or result.get("covered_by") == pick):
			covered.append({"date": str(r.rotation_date), "guard": result["covered_by"], "guard_name": result.get("covered_by_name")})
		else:
			uncovered.append(
				{
					"date": str(r.rotation_date),
					"reason": result.get("reason") or (_("No cover picked") if not pick else _("Not covered")),
					"still_covered_by": result.get("covered_by_name") if is_covered else None,
				}
			)
	frappe.db.commit()
	return {"covered": covered, "uncovered": uncovered}
