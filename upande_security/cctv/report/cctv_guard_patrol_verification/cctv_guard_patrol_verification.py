# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Patrol proof from cameras: each guard's camera passes (matched by GPS or
checkpoint scan), and how many "person seen" alerts were cleared as a guard
on patrol instead of reaching anyone."""

import frappe
from frappe import _

from upande_security.cctv.report_utils import site_clause, window


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end = window(f, default_days=7)
	cond, vals = site_clause(f)
	if f.security_guard:
		cond += " and security_guard = %(security_guard)s"
		vals["security_guard"] = f.security_guard
	passes = frappe.db.sql(f"""
		select coalesce(guard_name, security_guard, employee) as guard, security_guard, employee, farm,
			count(*) as passes, count(distinct camera) as cameras, min(sighting_time) as first_seen, max(sighting_time) as last_seen,
			sum(identified_by = 'Checkpoint Scan') as by_checkpoint, sum(identified_by = 'Guard GPS') as by_gps
		from `tabCCTV Person Sighting`
		where identified_by in ('Guard GPS', 'Checkpoint Scan') and sighting_time between %(start)s and %(end)s {cond}
		group by guard, security_guard, employee, farm order by passes desc""", {"start": start, "end": end, **vals}, as_dict=True)
	cleared = dict(frappe.db.sql(f"""
		select coalesce(guard_name, security_guard, guard_employee), count(*) from `tabCCTV Alert`
		where status = 'False Alarm' and false_alarm_reason = 'Authorised Person' and resolution_notes like 'Guard %%'
			and event_time between %(start)s and %(end)s {cond.replace('security_guard', 'security_guard')}
		group by 1""", {"start": start, "end": end, **vals}))
	for r in passes:
		r.alerts_cleared = cleared.get(r.guard, 0)
	cols = [
		{"fieldname": "guard", "label": _("Guard"), "width": 200},
		{"fieldname": "farm", "label": _("Site"), "fieldtype": "Link", "options": "Farm", "width": 110},
		{"fieldname": "passes", "label": _("Camera passes"), "fieldtype": "Int", "width": 120},
		{"fieldname": "cameras", "label": _("Different cameras"), "fieldtype": "Int", "width": 130},
		{"fieldname": "by_gps", "label": _("Matched by GPS"), "fieldtype": "Int", "width": 120},
		{"fieldname": "by_checkpoint", "label": _("Matched by checkpoint"), "fieldtype": "Int", "width": 150},
		{"fieldname": "first_seen", "label": _("First pass"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "last_seen", "label": _("Last pass"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "alerts_cleared", "label": _("False alarms avoided"), "fieldtype": "Int", "width": 150},
	]
	summary = [
		{"label": _("Guard passes"), "value": sum(r.passes for r in passes), "indicator": "blue"},
		{"label": _("False alarms avoided"), "value": sum(cleared.values()), "indicator": "green"},
	]
	return cols, passes, None, None, summary
