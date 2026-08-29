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
		self.auto_mark_single_gate_farms_as_main()

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
