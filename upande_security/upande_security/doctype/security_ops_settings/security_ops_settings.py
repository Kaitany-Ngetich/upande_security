# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SecurityOpsSettings(Document):
	def validate(self):
		if (
			self.missed_checkin_minutes
			and self.escalation_minutes
			and self.escalation_minutes < self.missed_checkin_minutes
		):
			frappe.throw(
				"SOS Escalation Threshold ({0} min) must be longer than the Missed Check-in"
				" Threshold ({1} min), otherwise every missed check-in escalates immediately.".format(
					self.escalation_minutes, self.missed_checkin_minutes
				)
			)
		self.validate_coverage_grid()
		self.auto_mark_single_gate_farms_as_main()

	def validate_coverage_grid(self):
		for label, value in (
			("Grid Cell Width", self.coverage_grid_cell_width_m),
			("Grid Cell Height", self.coverage_grid_cell_height_m),
			("Patrol Influence Radius", self.coverage_influence_radius_m),
		):
			if value and not 10 <= value <= 500:
				frappe.throw("{0} must be between 10 and 500 meters.".format(label))
		if self.coverage_boundary_tolerance_m and not 0 <= self.coverage_boundary_tolerance_m <= 500:
			frappe.throw("Boundary Tolerance must be between 0 and 500 meters.")
		if (
			self.coverage_fresh_hours
			and self.coverage_stale_hours
			and self.coverage_stale_hours <= self.coverage_fresh_hours
		):
			frappe.throw(
				"Not Patrolled After ({0} h) must be longer than Fully Patrolled Within ({1} h).".format(
					self.coverage_stale_hours, self.coverage_fresh_hours
				)
			)

	def auto_mark_single_gate_farms_as_main(self):
		"""A farm with exactly one active gate has nothing to disambiguate -
		its one gate IS the main gate. Rather than making every single-gate
		farm remember to tick "Main Gate" by hand, set it for them. Farms
		with 2+ active gates are left alone - that's a real choice someone
		has to make.
		"""
		by_farm = {}
		for row in self.farm_gates or []:
			if row.active:
				by_farm.setdefault(row.farm, []).append(row)
		for farm, rows in by_farm.items():
			if len(rows) == 1:
				rows[0].is_main_gate = 1
