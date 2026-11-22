# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document


class CCTVEngineModel(Document):
	def validate(self):
		if self.enabled and self.licence in ("", None, "Other - check"):
			frappe.throw(_("Clear the model's licence before enabling it (Apache-2.0 / MIT / BSD or a bought commercial licence)."))
		if self.model_file and self.has_value_changed("model_file"):
			f = frappe.get_doc("File", {"file_url": self.model_file})
			with open(f.get_full_path(), "rb") as fh:
				self.sha256 = hashlib.sha256(fh.read()).hexdigest()
		if self.enabled and not self.shadow_mode:
			other = frappe.db.get_value("CCTV Engine Model", {"task": self.task, "enabled": 1, "shadow_mode": 0, "name": ["!=", self.name]})
			if other:
				frappe.throw(_("{0} is already the live {1} model. Disable it, or run this one in shadow mode first.").format(other, self.task))
