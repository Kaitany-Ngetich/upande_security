# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Visits that ran past their expected exit (appointment's Expected Exit, or the default stay)."""

import frappe
from frappe import _
from frappe.utils import now_datetime, time_diff_in_seconds

from upande_security.cctv.report_utils import site_clause, window


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end = window(f)
	cond, vals = site_clause(f)
	rows = frappe.db.sql(f"""
		select name, plate, party_type, party_name, farm, host, appointment, entry_time, expected_exit, exit_time, status
		from `tabCCTV Vehicle Visit`
		where entry_time between %(start)s and %(end)s and expected_exit is not null
			and coalesce(exit_time, %(now)s) > expected_exit {cond}
		order by entry_time desc""", {"start": start, "end": end, "now": now_datetime(), **vals}, as_dict=True)
	for r in rows:
		r.minutes_over = int(time_diff_in_seconds(r.exit_time or now_datetime(), r.expected_exit) // 60)
		r.host_name = frappe.db.get_value("Employee", r.host, "employee_name") if r.host else None
	cols = [
		{"fieldname": "name", "label": _("Visit"), "fieldtype": "Link", "options": "CCTV Vehicle Visit", "width": 130},
		{"fieldname": "plate", "label": _("Plate"), "width": 100},
		{"fieldname": "party_name", "label": _("Who"), "width": 200},
		{"fieldname": "party_type", "label": _("Type"), "width": 90},
		{"fieldname": "host_name", "label": _("Host"), "width": 150},
		{"fieldname": "entry_time", "label": _("In"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "expected_exit", "label": _("Expected out"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "exit_time", "label": _("Out"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "minutes_over", "label": _("Minutes over"), "fieldtype": "Int", "width": 110},
		{"fieldname": "status", "label": _("Status"), "width": 120},
	]
	return cols, rows
