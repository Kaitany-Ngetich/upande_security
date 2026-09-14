# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import format_datetime, get_datetime, get_link_to_form, get_timedelta, now_datetime

# Statuses derived from the clock. "Cancelled" is deliberately excluded — it is
# a human decision and the automation must never overwrite it.
DERIVED_STATUSES = ("Scheduled", "Active", "Ended")

# A shift still occupies a guard if it is running or yet to run. Ended and
# Cancelled shifts release them.
BLOCKING_STATUSES = ("Scheduled", "Active")

# A single Shift Assignment record models one shift instance — including an
# overnight one that crosses midnight (e.g. 18:00 -> 06:00) — never a
# multi-day range. derive_status() below only ever looks at the record's own
# start/end, so a record spanning a week or a month reads "Active" for that
# entire span, day and night, regardless of what start_time/end_time say —
# there's no per-day recurrence concept here at all. Real multi-day coverage
# already has a purpose-built path that gets this right: Security Guard
# Rotation Plan generates one single-day record per day (skipping the
# guard's configured off days), so each day's status is derived correctly on
# its own. This cap forces that path instead of silently mis-tracking a
# directly-typed wide range.
MAX_SHIFT_HOURS = 24

# For an Internal Guard, this whole record is a read-only render of what HR
# is already planning (per the user: "the internal HR are planning their own
# rosters so we just render from them") — Security doesn't edit any of it,
# including which station/farm they're rotated to. Locked on every save after
# creation (see validate_internal_guard_shift_is_hr_owned), including
# "security_guard" itself, so a record can't be switched to External Guard as
# a way around the lock. Status is deliberately left out: a Security Head
# still needs to be able to mark a synced shift Cancelled (guard called in
# sick) without waiting on HR to update their own roster — the one exception,
# per sync_shifts_from_hr_roster()'s own docstring. remarks/checked_in stay
# editable too, for the same reason.
LOCKED_FIELDS_FOR_INTERNAL_GUARD = (
	"security_guard",
	"internal_guard",
	"shift_type",
	"start_date",
	"start_time",
	"end_date",
	"end_time",
	"farm",
	"block",
)


def combine_date_time(date_val, time_val):
	"""Date + Time fields, combined into a single datetime — mirrors HR's own
	split (Shift Assignment holds the date, Shift Type holds the time). Returns
	None if either half is missing, since a shift can't be placed on a timeline
	without both.
	"""
	if not date_val or time_val is None:
		return None
	return get_datetime(date_val) + get_timedelta(time_val)


def derive_status(start_date, start_time, end_date, end_time, current_status=None):
	"""Return the status a shift should have right now, or None to leave it be.

	Cancelled is preserved, and a shift missing any bound can't be placed on a
	timeline, so both cases return None.
	"""
	if current_status == "Cancelled":
		return None

	start = combine_date_time(start_date, start_time)
	end = combine_date_time(end_date, end_time)
	if not start or not end:
		return None

	now = now_datetime()
	if now < start:
		return "Scheduled"
	if now > end:
		return "Ended"
	return "Active"


class SecurityGuardShiftAssignment(Document):
	def validate(self):
		self.set_derived_status()
		# Runs before the overlap check on purpose: if this create/edit isn't
		# even allowed, that's the error a Security Head should see — not an
		# overlap-conflict message for a record that shouldn't exist anyway.
		self.validate_internal_guard_shift_is_hr_owned()
		# Also a structural gate, not a business rule — a record that spans
		# too many days can't have a meaningful overlap check run against it
		# either (its own "window" is already wrong), so this runs before
		# validate_no_overlapping_assignment too.
		self.validate_date_range_is_single_shift()
		self.validate_no_overlapping_assignment()

	def set_derived_status(self):
		"""Keep status truthful on every save; the scheduler handles the rest."""
		derived = derive_status(self.start_date, self.start_time, self.end_date, self.end_time, self.status)
		if derived:
			self.status = derived

	def validate_date_range_is_single_shift(self):
		"""One record, one shift instance. HR-synced Internal Guard shifts and
		Rotation-Plan-applied External Guard shifts both already save this way
		on their own (see tasks.sync_shifts_from_hr_roster and
		SecurityGuardRotationPlan.apply_rotation) — this only ever fires when
		someone types a multi-day range directly into start_date/end_date.

		Only enforced on a NEW record, or on an edit that actually CHANGES
		one of the date/time fields — never on an already-saved record whose
		range is untouched. Plenty of legacy records already exist with a
		too-wide range from before this check existed; a Security Head must
		still be able to open one and cancel it, fix a remark, etc. without
		being blocked by a rule about a range they aren't even editing.
		"""
		if not self.is_new():
			before = self.get_doc_before_save()
			range_fields = ("start_date", "start_time", "end_date", "end_time")
			if before and all(self.get(f) == before.get(f) for f in range_fields):
				return

		start = combine_date_time(self.start_date, self.start_time)
		end = combine_date_time(self.end_date, self.end_time)
		if not start or not end:
			return

		duration_hours = (end - start).total_seconds() / 3600
		if duration_hours > MAX_SHIFT_HOURS:
			frappe.throw(
				_(
					"This shift runs from {0} to {1} — about {2} days. A single Shift "
					"Assignment can only cover one shift instance (up to {3} hours, including "
					"an overnight shift crossing midnight), not a multi-day range — otherwise "
					"its status shows Active for the whole span, day and night, regardless of "
					"the actual shift hours. Use + New Rotation Plan For This Guard instead to "
					"schedule this guard across multiple days — it creates one correctly-timed "
					"Shift Assignment per day and skips the guard's configured off days "
					"automatically."
				).format(
					format_datetime(start),
					format_datetime(end),
					round(duration_hours / 24, 1),
					MAX_SHIFT_HOURS,
				),
				title=_("Shift Spans Too Many Days"),
			)

	def validate_internal_guard_shift_is_hr_owned(self):
		"""Internal guards' shifts are entirely HR's — this doctype only ever
		*renders* what sync_shifts_from_hr_roster() mirrors in from HR's own
		Shift Type / Shift Assignment. A Security Head does not plan shifts
		for Internal Guards here at all, so:

		- creating a NEW Internal Guard record is blocked unless it's the
		  sync job itself (flagged via self.flags.from_hr_sync — see
		  tasks.py's sync_shifts_from_hr_roster()).
		- editing the HR-owned fields on an already-saved record is blocked
		  (LOCKED_FIELDS_FOR_INTERNAL_GUARD above), including switching
		  "security_guard" itself, so a record can't dodge the lock by first
		  being flipped to External Guard.

		External Guards are entirely unaffected — they have no HR roster to
		mirror, so Security plans their shifts directly, same as always.
		"""
		if self.is_new():
			if self.security_guard != "Internal Guard":
				return
			if not self.flags.from_hr_sync:
				frappe.throw(
					_(
						"Internal Guard shifts aren't planned here — they're mirrored in "
						"automatically from HR's Shift Type / Shift Assignment. Set up the "
						"guard's shift in HR instead."
					),
					title=_("Shift Comes From HR"),
				)
			return

		# Existing record: gate on what it WAS, not what this save is trying
		# to change it to — otherwise switching security_guard to "External
		# Guard" in the same save would dodge every check below by making
		# self.security_guard no longer read "Internal Guard".
		before = self.get_doc_before_save()
		if not before or before.security_guard != "Internal Guard":
			return

		for field in LOCKED_FIELDS_FOR_INTERNAL_GUARD:
			if self.get(field) != before.get(field):
				frappe.throw(
					_(
						"{0} cannot be changed for an Internal Guard's shift — it mirrors HR's "
						"Shift Type / Shift Assignment. Update the guard's shift in HR instead."
					).format(frappe.bold(_(self.meta.get_field(field).label))),
					title=_("Shift Comes From HR"),
				)

	def validate_no_overlapping_assignment(self):
		# A guard can't physically be at two farms at once — block any other
		# scheduled or running assignment for the same guard that overlaps this
		# one. Ended and Cancelled shifts are no longer a conflict.
		if self.status not in BLOCKING_STATUSES:
			return

		if self.security_guard == "Internal Guard":
			guard_field, guard_value = "internal_guard", self.internal_guard
		else:
			guard_field, guard_value = "external_guard", self.external_guard

		self_start = combine_date_time(self.start_date, self.start_time)
		self_end = combine_date_time(self.end_date, self.end_time)
		if not guard_value or not self_start or not self_end:
			return

		# Date + Time are two separate columns now, so the overlap window has
		# to be compared as combined datetimes (MySQL's TIMESTAMP(date, time))
		# rather than via frappe.get_all's plain per-column filters.
		#
		# Strict < / > on purpose, not <= / >= — two shifts that merely TOUCH
		# at a boundary (one ends the exact instant the other starts, e.g. a
		# guard handing over at 06:00 sharp, or a back-to-back rotation where
		# each day's shift starts right where the last one ended) is a normal
		# handover, not a double booking. Inclusive comparison would flag
		# every day after the first as an "overlap" whenever a rotation's End
		# Time equals the next shift's Start Time.
		clash = frappe.db.sql(
			"""
			SELECT name, farm, start_date, start_time, end_date, end_time
			FROM `tabSecurity Guard Shift Assignment`
			WHERE {guard_field} = %(guard_value)s
			  AND status IN %(statuses)s
			  AND name != %(name)s
			  AND TIMESTAMP(start_date, start_time) < %(self_end)s
			  AND TIMESTAMP(end_date, end_time) > %(self_start)s
			LIMIT 1
			""".format(guard_field=guard_field),
			{
				"guard_value": guard_value,
				"statuses": BLOCKING_STATUSES,
				"name": self.name or "",
				"self_end": self_end,
				"self_start": self_start,
			},
			as_dict=True,
		)

		if clash:
			row = clash[0]
			frappe.throw(
				_(
					"This guard is already assigned to {0} from {1} to {2} ({3}), which overlaps "
					"this shift. A guard cannot be scheduled at two farms at the same time."
				).format(
					frappe.bold(row.farm or _("another farm")),
					format_datetime(combine_date_time(row.start_date, row.start_time)),
					format_datetime(combine_date_time(row.end_date, row.end_time)),
					get_link_to_form("Security Guard Shift Assignment", row.name),
				),
				title=_("Overlapping Shift Assignment"),
			)


# Status -> colour for the Calendar/Gantt view. Cancelled reads as struck-out
# grey rather than a false "everything's fine" green.
STATUS_COLOR = {
	"Scheduled": "#8D99AE",
	"Active": "#2ECC71",
	"Ended": "#B0B0B0",
	"Cancelled": "#E74C3C",
}


@frappe.whitelist()
def get_shift_events(start, end, filters=None):
	"""Feeds the Calendar and Gantt views — see
	security_guard_shift_assignment_calendar.js for the field_map this
	return shape has to match (start/end/id/title/color).

	The doctype itself has no stored title (removed — it just duplicated
	the guard/farm info already reachable via the record's own linked
	fields). The label bar in Calendar/Gantt still needs *something*
	readable though — a plain list of "SGSA-00001", "SGSA-00002" would
	defeat the point of a visual planning view — so it's composed here,
	on the fly, for display only, never persisted back onto the record.
	"""
	from frappe.desk.reportview import get_filters_cond

	conditions = get_filters_cond("Security Guard Shift Assignment", filters, [])

	rows = frappe.db.sql(
		"""
		SELECT name, security_guard, internal_guard, external_guard,
		       farm, block, shift_type, status, start_date, start_time, end_date, end_time
		FROM `tabSecurity Guard Shift Assignment`
		WHERE TIMESTAMP(start_date, start_time) <= %(end)s
		  AND TIMESTAMP(end_date, end_time) >= %(start)s {conditions}
		""".format(conditions=conditions),
		{"start": start, "end": end},
		as_dict=True,
	)

	# Batch-resolve guard display names instead of one query per row.
	employee_ids = [r.internal_guard for r in rows if r.security_guard == "Internal Guard" and r.internal_guard]
	guard_ids = [r.external_guard for r in rows if r.security_guard == "External Guard" and r.external_guard]
	employee_names = {}
	if employee_ids:
		employee_names = dict(
			frappe.db.sql(
				"SELECT name, employee_name FROM `tabEmployee` WHERE name IN %(ids)s",
				{"ids": tuple(employee_ids)},
			)
		)
	guard_names = {}
	if guard_ids:
		guard_names = dict(
			frappe.db.sql(
				"SELECT name, full_name FROM `tabSecurity Guard` WHERE name IN %(ids)s",
				{"ids": tuple(guard_ids)},
			)
		)

	events = []
	for r in rows:
		if r.security_guard == "Internal Guard" and r.internal_guard:
			guard_name = employee_names.get(r.internal_guard) or r.internal_guard
		elif r.security_guard == "External Guard" and r.external_guard:
			guard_name = guard_names.get(r.external_guard) or r.external_guard
		else:
			guard_name = _("Unassigned Guard")

		where = r.farm or _("Unknown Farm")
		if r.block:
			where = where + " · " + r.block

		label = "{0} — {1} ({2})".format(guard_name, where, r.shift_type) if r.shift_type else "{0} — {1}".format(guard_name, where)

		events.append(
			{
				"name": r.name,
				"id": r.name,
				"title": label,
				"start": combine_date_time(r.start_date, r.start_time),
				"end": combine_date_time(r.end_date, r.end_time),
				"status": r.status,
				"color": STATUS_COLOR.get(r.status, "#8D99AE"),
			}
		)
	return events
