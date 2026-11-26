# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""How well each camera reads plates: matched automatically, sent for review, ignored,
and average confidence. The figure to watch when deciding if a camera needs moving,
better lighting, or a dedicated ANPR camera."""

import frappe
from frappe import _

from upande_security.cctv.report_utils import site_clause, window


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end = window(f)
	cond, vals = site_clause(f)
	data = frappe.db.sql(f"""
		select camera, farm, count(*) as read_count,
			sum(match_status = 'Matched') as matched, sum(match_status = 'Review') as review,
			sum(match_status = 'Unmatched') as unmatched, sum(match_status = 'Ignored') as ignored,
			round(avg(confidence), 1) as avg_confidence
		from `tabCCTV Vehicle Sighting` where sighting_time between %(start)s and %(end)s {cond}
		group by camera, farm order by read_count desc""", {"start": start, "end": end, **vals}, as_dict=True)
	corrected = dict(frappe.db.sql(f"""
		select s.camera, count(*) from `tabCCTV Review Item` r join `tabCCTV Vehicle Sighting` s on s.name = r.sighting
		where r.resolution = 'Plate Corrected' and s.sighting_time between %(start)s and %(end)s group by s.camera""",
		{"start": start, "end": end}))
	names = dict(frappe.get_all("CCTV Camera", fields=["name", "camera_name"], as_list=True))
	for r in data:
		r.camera_name = names.get(r.camera, r.camera)
		r.auto_match_pct = round(100 * (r.matched or 0) / r.read_count, 1) if r.read_count else 0
		r.corrected = corrected.get(r.camera, 0)
	cols = [
		{"fieldname": "camera_name", "label": _("Camera"), "width": 200},
		{"fieldname": "farm", "label": _("Site"), "fieldtype": "Link", "options": "Farm", "width": 110},
		{"fieldname": "read_count", "label": _("Reads"), "fieldtype": "Int", "width": 80},
		{"fieldname": "auto_match_pct", "label": _("Matched %"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "review", "label": _("To review"), "fieldtype": "Int", "width": 90},
		{"fieldname": "unmatched", "label": _("Unmatched"), "fieldtype": "Int", "width": 90},
		{"fieldname": "ignored", "label": _("Too unsure"), "fieldtype": "Int", "width": 90},
		{"fieldname": "corrected", "label": _("Plates corrected by guards"), "fieldtype": "Int", "width": 170},
		{"fieldname": "avg_confidence", "label": _("Average confidence %"), "fieldtype": "Float", "width": 150},
	]
	return cols, data
