# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class IncidentReport(Document):
	def validate(self):
		self.block_close_with_open_capa_actions()

	def block_close_with_open_capa_actions(self):
		"""An incident is only genuinely closed once every corrective action
		on it is done — not just because someone flipped a status field.
		Closing here is gated on the CAPA Actions table, not the other way
		around: this doctype enforces the rule, but the actual "is this
		incident really finished" decision lives in whether its CAPA rows
		say Completed, not in this status field alone."""
		if self.status != "Closed":
			return

		open_actions = [
			row for row in (self.capa_actions or []) if row.status != "Completed"
		]
		if open_actions:
			frappe.throw(
				_(
					"Cannot close this incident — {0} corrective action(s) in the "
					"CAPA table below are still not Completed. Complete them (or "
					"remove them if no longer relevant) before closing."
				).format(len(open_actions))
			)
