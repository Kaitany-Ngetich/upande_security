# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SecurityGuard(Document):
	def before_save(self):
		# full_name is the title every link to a guard displays (Shift
		# Assignments, Patrol Logs, Patrol Reports). Records created by import
		# or the API arrived with it blank and showed as bare SG-0000xx codes.
		# Only filled when empty, so a name corrected by hand is never undone.
		# custom_last_name is a Custom Field on some sites only, hence .get().
		if not (self.full_name or "").strip():
			self.full_name = " ".join(
				part.strip()
				for part in (self.first_name, self.middle_name, self.get("custom_last_name"))
				if part and part.strip()
			)
