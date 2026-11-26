# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Role permission rules this app adds to doctypes, applied on every migrate.

These used to ship as Custom DocPerm fixtures. Importing a Custom DocPerm
row onto a doctype that had none makes Frappe ignore that doctype's
standard permissions, so every role except the fixture's lost access
(Appointment kept only Secretary and Visit Approver, Page only Visit
Approver). Going through frappe.permissions instead copies the standard
rules across first, the same as the Role Permission Manager does, so the
roles below are added next to the existing ones and never replace them.

Only grants: a right set here is switched on, nothing is switched off, so
anything a site's admin added on top is kept.
"""

import frappe
from frappe.permissions import add_permission, update_permission_property

# (doctype, role) -> rights at permlevel 0, not restricted to owner.
ROLE_PERMISSIONS = {
	# Visit Approver needs base read/write/create on Appointment: a Workflow
	# Transition's allowed role can only narrow a granted permission, never
	# create one. "Only your own appointments" is narrowed by the Host Sees
	# Own Appointments permission query, not here.
	("Appointment", "Secretary"): ("select", "read", "write", "create", "delete", "export", "email"),
	("Appointment", "Visit Approver"): ("read", "write", "create", "export"),
	("Page", "Visit Approver"): ("select", "read", "write", "create", "delete", "export"),
	("Incident Report", "Secretary"): ("select", "read", "write", "create", "delete", "report", "export", "print"),
	("Security Guard", "Secretary"): ("read", "export"),
	("Security Watchlist", "Secretary"): ("select", "read", "write", "create", "delete", "export", "print"),
	("Staff Vehicle Sticker", "Secretary"): ("select", "read", "write", "create", "delete", "export", "print"),
	("Staff Vehicle Sticker Request", "Secretary"): ("select", "read", "write", "create", "delete", "export", "email"),
}


def apply():
	"""after_migrate: add the rules above where they are missing."""
	for (doctype, role), rights in ROLE_PERMISSIONS.items():
		if not (frappe.db.exists("DocType", doctype) and frappe.db.exists("Role", role)):
			continue
		try:
			rule = {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
			if not frappe.db.exists("Custom DocPerm", rule):
				add_permission(doctype, role, 0)
			current = frappe.db.get_value("Custom DocPerm", rule, list(rights), as_dict=True) or {}
			for right in rights:
				if not current.get(right):
					update_permission_property(doctype, role, 0, right, 1, validate=False)
			frappe.clear_cache(doctype=doctype)
		except Exception:
			frappe.log_error(title=f"Could not add {role} permissions on {doctype}")
	frappe.db.commit()
