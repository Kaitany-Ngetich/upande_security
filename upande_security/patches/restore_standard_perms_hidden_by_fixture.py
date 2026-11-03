# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""The old Custom DocPerm fixture (Secretary, Visit Approver) was imported
straight onto doctypes that had no custom permissions, so Frappe stopped
reading their standard permissions and every other role lost access. Copy
back each standard rule that has no custom counterpart on those doctypes.
The role rules themselves are now added by role_permissions.apply.

Only a doctype whose custom rules are nothing but the fixture's roles (and
System Manager, added by hand on some sites since) is repaired - anything
else was set up by an admin, and a rule they removed stays removed."""

import frappe

from upande_security.role_permissions import ROLE_PERMISSIONS


def execute():
	for doctype in {doctype for doctype, _role in ROLE_PERMISSIONS}:
		custom = frappe.get_all(
			"Custom DocPerm", filters={"parent": doctype}, fields=["role", "permlevel", "if_owner"]
		)
		fixture_roles = {role for dt, role in ROLE_PERMISSIONS if dt == doctype} | {"System Manager"}
		if not custom or {r.role for r in custom} - fixture_roles:
			continue
		have = {(r.role, r.permlevel, r.if_owner) for r in custom}
		for std in frappe.get_all("DocPerm", filters={"parent": doctype}, fields="*"):
			if (std.role, std.permlevel, std.if_owner) in have:
				continue
			perm = frappe.new_doc("Custom DocPerm")
			perm.update({k: v for k, v in std.items() if k not in ("name", "creation", "modified", "owner", "modified_by")})
			perm.insert(ignore_permissions=True)
		frappe.clear_cache(doctype=doctype)
