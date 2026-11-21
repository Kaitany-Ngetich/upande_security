# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CCTVCamera(Document):
	def validate(self):
		if self.enabled and (self.is_new() or self.has_value_changed("enabled")):
			from upande_security.cctv.settings import max_cameras

			farm = self.farm or frappe.db.get_value("CCTV Server", self.server, "farm")
			limit = max_cameras(farm)
			if limit and frappe.db.count("CCTV Camera", {"farm": farm, "enabled": 1, "name": ["!=", self.name or ""]}) >= limit:
				frappe.throw(_("The licence for {0} allows {1} cameras.").format(farm, limit))
