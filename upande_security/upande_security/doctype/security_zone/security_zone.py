# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""A fenced section inside a farm, and who may be in it.

A farm already has one boundary (Farm.boundary_geojson) that the patrol
geofence tests against. A Security Zone is a smaller area inside it - a
fuel yard, a pack-house apron, a block - with its own rule about who
belongs there and when.

`default_access` is the policy and the rules are exceptions, the same way a
firewall reads:

  Deny  - a restricted section. Nobody belongs here unless a rule allows
          them. Use for a fuel store or a chemical yard.
  Allow - a monitored section. Anyone may be here unless a rule denies
          them. Use when you only want to catch one person, or one window.

Rules are evaluated in table order and the FIRST match wins, so a specific
Allow placed above a blanket Deny is how you carve out an exception.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class SecurityZone(Document):
	def validate(self):
		self._validate_boundary()
		self._validate_rules()

	def _validate_boundary(self):
		"""A zone with no boundary can never match a point, so it would sit
		Active and silently test nothing. Warn rather than block: a zone is
		often created before someone draws its outline."""
		if self.active and not self.boundary_geojson:
			frappe.msgprint(
				_("This zone is Active but has no boundary, so nothing will be checked against it."),
				indicator="orange",
				alert=True,
			)

	def _validate_rules(self):
		for row in self.access_rules or []:
			target = {
				"Role": row.role,
				"Employee": row.employee,
				"Security Guard": row.security_guard,
			}.get(row.applies_to)
			if row.applies_to != "Anyone" and not target:
				frappe.throw(
					_("Row {0}: choose the {1} this rule is about.").format(row.idx, row.applies_to)
				)
			# A window that is open at both ends is the whole day; one end
			# alone is ambiguous, and silently treating it as "from then
			# onwards" is the kind of guess that mis-fires at 2am.
			if bool(row.from_time) != bool(row.to_time):
				frappe.throw(
					_("Row {0}: set both From and To, or leave both blank for the whole day.").format(
						row.idx
					)
				)
