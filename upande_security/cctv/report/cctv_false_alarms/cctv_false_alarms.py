# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""False alarms by rule and reason - what to tune (camera position, schedule, threshold)."""

import frappe
from frappe import _

from upande_security.cctv.report_utils import site_clause, window


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end = window(f)
	cond, vals = site_clause(f)
	data = frappe.db.sql(f"""
		select alert_type, coalesce(rule, '(default)') as rule, camera, false_alarm_reason as reason, count(*) as count
		from `tabCCTV Alert` where status = 'False Alarm' and event_time between %(start)s and %(end)s {cond}
		group by alert_type, rule, camera, false_alarm_reason order by count desc""", {"start": start, "end": end, **vals}, as_dict=True)
	names = dict(frappe.get_all("CCTV Camera", fields=["name", "camera_name"], as_list=True))
	for r in data:
		r.camera_name = names.get(r.camera, r.camera)
	cols = [
		{"fieldname": "alert_type", "label": _("Alert"), "width": 200},
		{"fieldname": "rule", "label": _("Rule"), "width": 180},
		{"fieldname": "camera_name", "label": _("Camera"), "width": 180},
		{"fieldname": "reason", "label": _("Reason"), "width": 160},
		{"fieldname": "count", "label": _("False alarms"), "fieldtype": "Int", "width": 110},
	]
	reasons = {}
	for r in data:
		reasons[r.reason or "-"] = reasons.get(r.reason or "-", 0) + r.count
	chart = {"data": {"labels": list(reasons), "datasets": [{"values": list(reasons.values())}]}, "type": "pie"} if reasons else None
	return cols, data, None, chart
