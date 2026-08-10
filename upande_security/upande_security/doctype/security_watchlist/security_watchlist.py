# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SecurityWatchlist(Document):
	def before_insert(self):
		self.added_by = frappe.session.user
		self.added_on = frappe.utils.now_datetime()
