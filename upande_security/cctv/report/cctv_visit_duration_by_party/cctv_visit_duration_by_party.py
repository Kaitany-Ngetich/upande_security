# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""How long each kind of visitor stays: visits, average, median and longest time inside."""

import frappe
from frappe import _

from upande_security.cctv.report_utils import median, site_clause, window


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end = window(f)
	cond, vals = site_clause(f)
	rows = frappe.db.sql(f"""
		select party_type, total_minutes from `tabCCTV Vehicle Visit`
		where entry_time between %(start)s and %(end)s and exit_time is not null and total_minutes is not null {cond}""",
		{"start": start, "end": end, **vals}, as_dict=True)
	groups = {}
	for r in rows:
		groups.setdefault(r.party_type or "Unknown", []).append(r.total_minutes)
	data = [{
		"party_type": k, "visits": len(v), "avg_minutes": round(sum(v) / len(v), 1), "median_minutes": median(v), "max_minutes": max(v),
	} for k, v in sorted(groups.items(), key=lambda x: -len(x[1]))]
	cols = [
		{"fieldname": "party_type", "label": _("Party type"), "width": 140},
		{"fieldname": "visits", "label": _("Visits"), "fieldtype": "Int", "width": 90},
		{"fieldname": "avg_minutes", "label": _("Average minutes"), "fieldtype": "Float", "width": 130},
		{"fieldname": "median_minutes", "label": _("Median minutes"), "fieldtype": "Float", "width": 130},
		{"fieldname": "max_minutes", "label": _("Longest"), "fieldtype": "Int", "width": 100},
	]
	chart = {"data": {"labels": [d["party_type"] for d in data], "datasets": [{"name": _("Average minutes"), "values": [d["avg_minutes"] for d in data]}]},
		"type": "bar"} if data else None
	return cols, data, None, chart
