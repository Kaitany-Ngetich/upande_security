# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Who watched what: every live view and every playback, with the alert or visit it came from."""

import frappe
from frappe import _

from upande_security.cctv.report_utils import window


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end = window(f)
	ucond = " and user = %(user)s" if f.user else ""
	vals = {"start": start, "end": end, "user": f.user}
	live = frappe.db.sql(f"""select 'Live' as kind, user, camera, started_at as at, ended_at as until, null as alert, null as range_start,
			null as range_end, ip_address from `tabCCTV Live View Log` where started_at between %(start)s and %(end)s {ucond}""", vals, as_dict=True)
	pb = frappe.db.sql(f"""select concat('Playback (', source, ')') as kind, user, camera, opened_at as at, null as until, alert,
			range_start, range_end, ip_address from `tabCCTV Playback Log` where opened_at between %(start)s and %(end)s {ucond}""", vals, as_dict=True)
	cams = frappe.db.sql("select name, camera_name, farm from `tabCCTV Camera`", as_dict=True)
	cams = {c.name: c for c in cams}
	data = sorted(live + pb, key=lambda r: r.at, reverse=True)
	for r in data:
		c = cams.get(r.camera)
		r.camera_name, r.farm = (c.camera_name, c.farm) if c else (r.camera, None)
	if f.farm:
		data = [r for r in data if r.farm == f.farm]
	elif f.company:
		farms = set(frappe.get_all("Farm", filters={"company": f.company}, pluck="name"))
		data = [r for r in data if r.farm in farms]
	cols = [
		{"fieldname": "at", "label": _("When"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "user", "label": _("User"), "fieldtype": "Link", "options": "User", "width": 200},
		{"fieldname": "kind", "label": _("What"), "width": 150},
		{"fieldname": "camera_name", "label": _("Camera"), "width": 180},
		{"fieldname": "farm", "label": _("Site"), "width": 100},
		{"fieldname": "alert", "label": _("Alert"), "fieldtype": "Link", "options": "CCTV Alert", "width": 150},
		{"fieldname": "range_start", "label": _("Footage from"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "range_end", "label": _("to"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "ip_address", "label": _("IP"), "width": 120},
	]
	return cols, data
