# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import format_datetime, get_link_to_form


class SecurityGuardShiftAssignment(Document):
	def validate(self):
		self.validate_no_overlapping_assignment()

	def validate_no_overlapping_assignment(self):
		# A guard can't physically be at two farms at once — block any other
		# Active assignment for the same guard whose time range overlaps this one.
		if self.status != "Active":
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
				"status": "Active",
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
