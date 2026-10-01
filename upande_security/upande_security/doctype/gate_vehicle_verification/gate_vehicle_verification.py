# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class GateVehicleVerification(Document):
	def validate(self):
		rejected = self.gate_exit_status == "Rejected" or self.gate_entry_status == "Rejected"
		if rejected and not self.remarks:
			frappe.throw(
				_("Remarks are required when rejecting a vehicle at the gate — record why it didn't match."),
				title=_("Remarks Required"),
			)
