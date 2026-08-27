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
