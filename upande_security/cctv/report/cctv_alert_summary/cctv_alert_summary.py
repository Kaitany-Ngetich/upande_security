# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Alerts by type and site: how many, how severe, how many were false alarms, how many still open."""

import frappe
from frappe import _

from upande_security.cctv.report_utils import site_clause, window


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end = window(f)
	cond, vals = site_clause(f)
	if f.severity:
		cond += " and severity = %(severity)s"
		vals["severity"] = f.severity
	data = frappe.db.sql(f"""
		select alert_type, farm, count(*) as total,
			sum(severity = 'Critical') as critical, sum(severity = 'High') as high,
			sum(status in ('Open', 'Escalated', 'Acknowledged')) as still_open,
			sum(status = 'False Alarm') as false_alarms, sum(repeat_count) as repeats
		from `tabCCTV Alert` where event_time between %(start)s and %(end)s {cond}
		group by alert_type, farm order by total desc""", {"start": start, "end": end, **vals}, as_dict=True)
	for r in data:
		r.false_alarm_pct = round(100 * (r.false_alarms or 0) / r.total, 1) if r.total else 0
	cols = [
		{"fieldname": "alert_type", "label": _("Alert"), "width": 200},
		{"fieldname": "farm", "label": _("Site"), "fieldtype": "Link", "options": "Farm", "width": 110},
		{"fieldname": "total", "label": _("Alerts"), "fieldtype": "Int", "width": 80},
		{"fieldname": "critical", "label": _("Critical"), "fieldtype": "Int", "width": 80},
		{"fieldname": "high", "label": _("High"), "fieldtype": "Int", "width": 70},
		{"fieldname": "still_open", "label": _("Still open"), "fieldtype": "Int", "width": 90},
		{"fieldname": "false_alarms", "label": _("False alarms"), "fieldtype": "Int", "width": 100},
		{"fieldname": "false_alarm_pct", "label": _("False alarm %"), "fieldtype": "Percent", "width": 110},
		{"fieldname": "repeats", "label": _("Repeats merged"), "fieldtype": "Int", "width": 110},
	]
	by_type = {}
	for r in data:
		by_type[r.alert_type] = by_type.get(r.alert_type, 0) + r.total
	chart = {"data": {"labels": list(by_type), "datasets": [{"name": _("Alerts"), "values": list(by_type.values())}]}, "type": "bar"} if by_type else None
	return cols, data, None, chart
