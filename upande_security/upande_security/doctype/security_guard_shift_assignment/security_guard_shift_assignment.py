# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import format_datetime, get_datetime, get_link_to_form, now_datetime

# Statuses derived from the clock. "Cancelled" is deliberately excluded — it is
# a human decision and the automation must never overwrite it.
DERIVED_STATUSES = ("Scheduled", "Active", "Ended")

# A shift still occupies a guard if it is running or yet to run. Ended and
# Cancelled shifts release them.
BLOCKING_STATUSES = ("Scheduled", "Active")

# For an Internal Guard, these fields describe HR's own Shift Type / Shift
# Assignment record, not something Security owns — editing them here would
# silently drift from what HR actually has on file. Locked on every save
# except the very first (see validate_no_shift_edit_for_internal_guard).
# Deliberately excludes farm/block/status/remarks — those stay editable, per
# sync_shifts_from_hr_roster()'s own docstring, as the Security Head's call.
LOCKED_FIELDS_FOR_INTERNAL_GUARD = ("internal_guard", "shift_type", "start_date", "end_date")


def derive_status(start_date, end_date, current_status=None):
	"""Return the status a shift should have right now, or None to leave it be.

	Cancelled is preserved, and a shift missing either bound can't be placed on
	a timeline, so both cases return None.
	"""
	if current_status == "Cancelled":
		return None
	if not start_date or not end_date:
		return None

	start = get_datetime(start_date)
	end = get_datetime(end_date)

	# Shifts are routinely entered as plain dates, which Frappe stores as
	# midnight. Read a midnight end as "through the end of that day", otherwise
	# a single-day shift would expire the instant it began and never show Active.
	if end.hour == 0 and end.minute == 0 and end.second == 0:
		end = end.replace(hour=23, minute=59, second=59)

	now = now_datetime()
	if now < start:
		return "Scheduled"
	if now > end:
		return "Ended"
	return "Active"


class SecurityGuardShiftAssignment(Document):
	def validate(self):
		self.set_derived_status()
		self.validate_no_overlapping_assignment()
		self.validate_no_shift_edit_for_internal_guard()

	def set_derived_status(self):
		"""Keep status truthful on every save; the scheduler handles the rest."""
		derived = derive_status(self.start_date, self.end_date, self.status)
		if derived:
			self.status = derived

	def validate_no_shift_edit_for_internal_guard(self):
		"""Internal guards' shift schedule belongs to HR (Shift Type / Shift
		Assignment) and is only ever mirrored in here by
		sync_shifts_from_hr_roster() — a manual edit here would silently
		drift from what HR actually has on record. Only blocks changes to an
		*already-saved* record: creation (by the sync job, or a Security
		Head entering a same-day ad-hoc shift before HR's own sync has run)
		is untouched, and this whole check is skipped for External Guards,
		who have no HR roster to mirror.
		"""
		if self.is_new():
			return

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

		if not guard_value or not self.start_date or not self.end_date:
			return

		clash = frappe.get_all(
			"Security Guard Shift Assignment",
			filters={
				guard_field: guard_value,
				"status": ["in", BLOCKING_STATUSES],
				"name": ["!=", self.name or ""],
				"start_date": ["<=", self.end_date],
				"end_date": [">=", self.start_date],
			},
			fields=["name", "farm", "start_date", "end_date"],
			limit_page_length=1,
		)

		if clash:
			row = clash[0]
			frappe.throw(
				_(
					"This guard is already assigned to {0} from {1} to {2} ({3}), which overlaps "
					"this shift. A guard cannot be scheduled at two farms at the same time."
				).format(
					frappe.bold(row.farm or _("another farm")),
					format_datetime(row.start_date),
					format_datetime(row.end_date),
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
		       farm, block, shift_type, status, start_date, end_date
		FROM `tabSecurity Guard Shift Assignment`
		WHERE start_date <= %(end)s AND end_date >= %(start)s {conditions}
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
				"start": r.start_date,
				"end": r.end_date,
				"status": r.status,
				"color": STATUS_COLOR.get(r.status, "#8D99AE"),
			}
		)
	return events
