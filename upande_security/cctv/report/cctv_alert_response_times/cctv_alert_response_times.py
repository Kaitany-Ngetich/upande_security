# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""How fast alerts are seen, acknowledged and closed, by severity and site (minutes)."""

import frappe
from frappe import _
from frappe.utils import time_diff_in_seconds

from upande_security.cctv.report_utils import median, site_clause, window


def _mins(a, b):
	return round(time_diff_in_seconds(b, a) / 60, 1) if a and b else None


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end = window(f)
	cond, vals = site_clause(f)
	rows = frappe.db.sql(f"""
		select severity, farm, creation, first_viewed_at, acknowledged_at, resolved_at, escalation_level
		from `tabCCTV Alert` where event_time between %(start)s and %(end)s {cond}""", {"start": start, "end": end, **vals}, as_dict=True)
	groups = {}
	for r in rows:
		g = groups.setdefault((r.severity or "Medium", r.farm or ""), {"seen": [], "ack": [], "closed": [], "n": 0, "escalated": 0, "never_ack": 0})
		g["n"] += 1
		g["seen"].append(_mins(r.creation, r.first_viewed_at))
		g["ack"].append(_mins(r.creation, r.acknowledged_at))
		g["closed"].append(_mins(r.creation, r.resolved_at))
		g["escalated"] += 1 if r.escalation_level else 0
		g["never_ack"] += 0 if r.acknowledged_at or r.resolved_at else 1
	order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
	data = [{
		"severity": sev, "farm": farm, "alerts": g["n"], "median_seen": median(g["seen"]), "median_ack": median(g["ack"]),
		"median_closed": median(g["closed"]), "escalated": g["escalated"], "never_acknowledged": g["never_ack"],
	} for (sev, farm), g in sorted(groups.items(), key=lambda x: (order.get(x[0][0], 9), x[0][1]))]
	cols = [
		{"fieldname": "severity", "label": _("Severity"), "width": 100},
		{"fieldname": "farm", "label": _("Site"), "fieldtype": "Link", "options": "Farm", "width": 110},
		{"fieldname": "alerts", "label": _("Alerts"), "fieldtype": "Int", "width": 80},
		{"fieldname": "median_seen", "label": _("Median min to first view"), "fieldtype": "Float", "width": 170},
		{"fieldname": "median_ack", "label": _("Median min to acknowledge"), "fieldtype": "Float", "width": 180},
		{"fieldname": "median_closed", "label": _("Median min to close"), "fieldtype": "Float", "width": 150},
		{"fieldname": "escalated", "label": _("Escalated"), "fieldtype": "Int", "width": 90},
		{"fieldname": "never_acknowledged", "label": _("Never acknowledged"), "fieldtype": "Int", "width": 140},
	]
	return cols, data
