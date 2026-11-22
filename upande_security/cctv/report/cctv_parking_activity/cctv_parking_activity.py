# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Parking by hour: vehicles the parking cameras read, in and out, and the busiest hours.

Counts vehicles SEEN in parking per hour (from cameras whose role is Parking).
True bay-level occupancy needs bay cameras or sensors; this is the gate-level picture."""

import frappe
from frappe import _

from upande_security.cctv.report_utils import site_clause, window


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end = window(f, default_days=7)
	cond, vals = site_clause(f, alias="s")
	rows = frappe.db.sql(f"""
		select date(s.sighting_time) as day, hour(s.sighting_time) as hour, s.farm,
			count(distinct coalesce(s.vehicle_visit, s.plate_normalized)) as vehicles,
			sum(s.direction = 'in') as entries, sum(s.direction = 'out') as exits
		from `tabCCTV Vehicle Sighting` s join `tabCCTV Camera` c on c.name = s.camera
		where c.role = 'Parking' and s.sighting_time between %(start)s and %(end)s {cond}
		group by day, hour, s.farm order by day, hour""", {"start": start, "end": end, **vals}, as_dict=True)
	for r in rows:
		r.hour_label = f"{int(r.hour):02d}:00"
	cols = [
		{"fieldname": "day", "label": _("Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "hour_label", "label": _("Hour"), "width": 80},
		{"fieldname": "farm", "label": _("Site"), "fieldtype": "Link", "options": "Farm", "width": 110},
		{"fieldname": "vehicles", "label": _("Vehicles seen"), "fieldtype": "Int", "width": 120},
		{"fieldname": "entries", "label": _("In"), "fieldtype": "Int", "width": 70},
		{"fieldname": "exits", "label": _("Out"), "fieldtype": "Int", "width": 70},
	]
	by_hour = {}
	for r in rows:
		by_hour[r.hour_label] = by_hour.get(r.hour_label, 0) + r.vehicles
	labels = sorted(by_hour)
	chart = {"data": {"labels": labels, "datasets": [{"name": _("Vehicles seen"), "values": [by_hour[h] for h in labels]}]}, "type": "bar"} if labels else None
	return cols, rows, None, chart
