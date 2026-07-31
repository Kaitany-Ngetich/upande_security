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

	def set_derived_status(self):
		"""Keep status truthful on every save; the scheduler handles the rest."""
		derived = derive_status(self.start_date, self.end_date, self.status)
		if derived:
			self.status = derived

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
