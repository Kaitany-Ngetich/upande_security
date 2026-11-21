# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Supplier turnaround at the docks: gate in -> first dock read -> last dock read -> gate out."""

import frappe
from frappe import _
from frappe.utils import time_diff_in_seconds

from upande_security.cctv.report_utils import median, site_clause, window


def _m(a, b):
	return round(time_diff_in_seconds(b, a) / 60, 1) if a and b else None


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end = window(f)
	cond, vals = site_clause(f, alias="v")
	rows = frappe.db.sql(f"""
		select v.name, v.plate, v.party_name, v.party_type, v.farm, v.entry_time, v.exit_time,
			min(s.sighting_time) as dock_in, max(s.sighting_time) as dock_out
		from `tabCCTV Vehicle Visit` v
		join `tabCCTV Vehicle Sighting` s on s.vehicle_visit = v.name
		join `tabCCTV Camera` c on c.name = s.camera and c.role = 'Dock'
		where v.entry_time between %(start)s and %(end)s {cond}
		group by v.name order by v.entry_time desc""", {"start": start, "end": end, **vals}, as_dict=True)
	for r in rows:
		r.to_dock = _m(r.entry_time, r.dock_in)
		r.at_dock = _m(r.dock_in, r.dock_out)
		r.dock_to_exit = _m(r.dock_out, r.exit_time)
		r.total = _m(r.entry_time, r.exit_time)
	cols = [
		{"fieldname": "name", "label": _("Visit"), "fieldtype": "Link", "options": "CCTV Vehicle Visit", "width": 130},
		{"fieldname": "party_name", "label": _("Who"), "width": 200},
		{"fieldname": "plate", "label": _("Plate"), "width": 100},
		{"fieldname": "entry_time", "label": _("Gate in"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "to_dock", "label": _("Min to dock"), "fieldtype": "Float", "width": 100},
		{"fieldname": "at_dock", "label": _("Min at dock"), "fieldtype": "Float", "width": 100},
		{"fieldname": "dock_to_exit", "label": _("Min dock to exit"), "fieldtype": "Float", "width": 120},
		{"fieldname": "total", "label": _("Total min"), "fieldtype": "Float", "width": 90},
	]
	summary = [
		{"label": _("Dock visits"), "value": len(rows), "indicator": "blue"},
		{"label": _("Median min at dock"), "value": median([r.at_dock for r in rows]) or 0, "indicator": "gray"},
		{"label": _("Median total min"), "value": median([r.total for r in rows]) or 0, "indicator": "gray"},
	] if rows else None
	return cols, rows, None, None, summary
