# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class GateDeliveryVerification(Document):
	def validate(self):
		if self.gate_verification_status == "Rejected" and not self.remarks:
			frappe.throw(
				_(
					"Remarks are required when rejecting a delivery at the gate — record why "
					"entry was refused (no PO found, wrong vehicle/driver, supplier not active)."
				),
				title=_("Remarks Required"),
			)
