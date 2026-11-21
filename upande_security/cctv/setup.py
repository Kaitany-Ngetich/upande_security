# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""after_migrate: give CCTV Settings its defaults (all switches OFF) and the
default plate formats, without touching anything an admin already set."""

import frappe

from upande_security.cctv.plates import DEFAULT_FORMATS
from upande_security.cctv.settings import DEFAULTS, SWITCHES


def after_migrate():
	if not frappe.db.exists("DocType", "CCTV Settings"):
		return
	existing = {r.field for r in frappe.db.sql("select field from `tabSingles` where doctype='CCTV Settings'", as_dict=True)}
	for key in SWITCHES:
		if key not in existing:
			frappe.db.set_single_value("CCTV Settings", key, 0)
	for key, value in DEFAULTS.items():
		if key not in existing:
			frappe.db.set_single_value("CCTV Settings", key, value)
	if not frappe.db.count("CCTV Plate Format", {"parent": "CCTV Settings"}):
		doc = frappe.get_single("CCTV Settings")
		for row in DEFAULT_FORMATS:
			doc.append("plate_formats", row)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.save()
	frappe.db.commit()
