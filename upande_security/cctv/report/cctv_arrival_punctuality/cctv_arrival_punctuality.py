# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Booked time against the gate camera's actual arrival, per visit and per organisation."""

import frappe
from frappe import _
from frappe.utils import time_diff_in_seconds

from upande_security.cctv.report_utils import median, site_clause, window


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end = window(f)
	cond, vals = site_clause(f, alias="v")
	rows = frappe.db.sql(f"""
		select v.name, v.plate, v.party_type, v.party_name, v.farm, v.appointment, v.expected_arrival, v.entry_time,
			a.customer_organization as organisation
		from `tabCCTV Vehicle Visit` v left join `tabAppointment` a on a.name = v.appointment
		where v.entry_time between %(start)s and %(end)s and v.expected_arrival is not null {cond}
		order by v.entry_time desc""", {"start": start, "end": end, **vals}, as_dict=True)
	for r in rows:
		r.minutes_late = int(time_diff_in_seconds(r.entry_time, r.expected_arrival) // 60)
		r.verdict = "Early" if r.minutes_late < -15 else "On time" if r.minutes_late <= 15 else "Late"
	cols = [
		{"fieldname": "appointment", "label": _("Appointment"), "fieldtype": "Link", "options": "Appointment", "width": 200},
		{"fieldname": "party_name", "label": _("Who"), "width": 180},
		{"fieldname": "organisation", "label": _("Organisation"), "width": 150},
		{"fieldname": "party_type", "label": _("Type"), "width": 90},
		{"fieldname": "plate", "label": _("Plate"), "width": 100},
		{"fieldname": "expected_arrival", "label": _("Booked"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "entry_time", "label": _("Arrived"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "minutes_late", "label": _("Minutes late (- early)"), "fieldtype": "Int", "width": 140},
		{"fieldname": "verdict", "label": _("Verdict"), "width": 90},
	]
	lates = [r.minutes_late for r in rows]
	summary = [
		{"label": _("Visits"), "value": len(rows), "indicator": "blue"},
		{"label": _("On time (±15 min)"), "value": sum(r.verdict == "On time" for r in rows), "indicator": "green"},
		{"label": _("Late"), "value": sum(r.verdict == "Late" for r in rows), "indicator": "orange"},
		{"label": _("Median minutes late"), "value": median(lates) or 0, "indicator": "gray"},
	] if rows else None
	return cols, rows, None, None, summary
