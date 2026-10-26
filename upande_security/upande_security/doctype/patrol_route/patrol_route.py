# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PatrolRoute(Document):
	"""A supervisor's set of checkpoints for a patrol. Which route a patrol
	gets, and in what order, is decided by
	upande_security.api.checkpoints.patrol_plan."""

	def validate(self):
		seen = set()
		for row in self.checkpoints:
			if row.checkpoint in seen:
				frappe.throw(_("Checkpoint {0} is listed twice.").format(row.checkpoint))
			seen.add(row.checkpoint)
			farm = frappe.db.get_value("Security Checkpoint", row.checkpoint, "farm")
			if farm and farm != self.farm:
				frappe.throw(
					_("Checkpoint {0} is on {1}, not {2}.").format(row.checkpoint_name or row.checkpoint, farm, self.farm)
				)
		if self.personel != "Internal Guard":
			self.internal_guard = None
		if self.personel != "External Guard":
			self.external_guard = None
