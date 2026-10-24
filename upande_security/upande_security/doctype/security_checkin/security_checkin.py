# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SecurityCheckin(Document):
	pass


def on_doctype_update():
	frappe.db.add_index("Security Checkin", ["security_guard", "time"], "security_guard_time")
