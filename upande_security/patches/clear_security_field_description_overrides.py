"""Field help text is hidden on the security doctypes. Some sites also set
descriptions by hand through Customize Form (Property Setters), which outlive
the doctype change; remove those so the help text is gone everywhere."""

import frappe


def execute():
	doctypes = frappe.get_all("DocType", filters={"module": "Upande Security"}, pluck="name")
	if not doctypes:
		return
	for name in frappe.get_all(
		"Property Setter",
		filters={"property": "description", "doc_type": ("in", doctypes)},
		pluck="name",
	):
		frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
	for dt in doctypes:
		frappe.clear_cache(doctype=dt)
