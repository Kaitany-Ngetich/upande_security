# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SecurityGuard(Document):
	def before_save(self):
		# full_name is the title every link to a guard displays (Shift
		# Assignments, Patrol Logs, Patrol Reports). Records created by import
		# or the API arrived with it blank and showed as bare SG-0000xx codes.
		# Only filled when empty, so a name corrected by hand is never undone.
		# custom_last_name is a Custom Field on some sites only, hence .get().
		if not (self.full_name or "").strip():
			self.full_name = guard_full_name(self)


def guard_full_name(guard):
	"""First, middle and last name; without a last name, the linked user's
	full name (guards are often entered with a first name only, and their
	user account carries the whole name), else whatever name there is."""
	parts = [
		p.strip()
		for p in (guard.get("first_name"), guard.get("middle_name"), guard.get("custom_last_name"))
		if p and p.strip()
	]
	if not (guard.get("custom_last_name") or "").strip() and guard.get("user"):
		user_name = (frappe.db.get_value("User", guard.get("user"), "full_name") or "").strip()
		if len(user_name.split()) > len(parts):
			return user_name
	return " ".join(parts)
