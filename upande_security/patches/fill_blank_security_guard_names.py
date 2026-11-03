"""Guards entered by import or the API with a first name only kept a blank
Full Name, so every list, map and report showed them as bare SG-0000xx codes.
Fill each blank Full Name the way saving the record would."""

import frappe

from upande_security.upande_security.doctype.security_guard.security_guard import guard_full_name


def execute():
	fields = ["name", "first_name", "middle_name", "user"]
	if frappe.get_meta("Security Guard").has_field("custom_last_name"):
		fields.append("custom_last_name")
	for g in frappe.db.sql(
		"SELECT " + ", ".join("`" + f + "`" for f in fields)
		+ " FROM `tabSecurity Guard` WHERE IFNULL(full_name, '') = ''",
		as_dict=True,
	):
		name = guard_full_name(g)
		if name:
			frappe.db.set_value("Security Guard", g.name, "full_name", name, update_modified=False)
