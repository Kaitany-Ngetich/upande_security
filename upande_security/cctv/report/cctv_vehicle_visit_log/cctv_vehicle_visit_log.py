# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Every vehicle visit in the period: who, plate, in, out, time inside, status."""

import frappe
from frappe import _

from upande_security.cctv.report_utils import site_clause, window


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end = window(f)
	cond, vals = site_clause(f)
	if f.party_type:
		cond += " and party_type = %(party_type)s"
	if f.status:
		cond += " and status = %(status)s"
	rows = frappe.db.sql(f"""
		select name, plate, party_type, party_name, source, reference_name, farm, entry_time, entry_gate, exit_time, exit_gate,
			total_minutes, status, guard_confirmed, closed_by, flags_text
		from `tabCCTV Vehicle Visit`
		where coalesce(entry_time, exit_time) between %(start)s and %(end)s {cond}
		order by coalesce(entry_time, exit_time) desc""", {"start": start, "end": end, **vals, **f}, as_dict=True)
	cols = [
		{"fieldname": "name", "label": _("Visit"), "fieldtype": "Link", "options": "CCTV Vehicle Visit", "width": 130},
		{"fieldname": "plate", "label": _("Plate"), "width": 100},
		{"fieldname": "party_name", "label": _("Who"), "width": 200},
		{"fieldname": "party_type", "label": _("Type"), "width": 90},
		{"fieldname": "farm", "label": _("Site"), "fieldtype": "Link", "options": "Farm", "width": 100},
		{"fieldname": "entry_time", "label": _("In"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "exit_time", "label": _("Out"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "total_minutes", "label": _("Minutes inside"), "fieldtype": "Int", "width": 110},
		{"fieldname": "status", "label": _("Status"), "width": 120},
		{"fieldname": "guard_confirmed", "label": _("Gate confirmed"), "fieldtype": "Check", "width": 100},
		{"fieldname": "source", "label": _("Matched to"), "width": 160},
		{"fieldname": "reference_name", "label": _("Record"), "width": 160},
		{"fieldname": "flags_text", "label": _("Flags"), "width": 220},
	]
	return cols, rows
