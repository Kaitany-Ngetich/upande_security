# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Everyone and every vehicle on site right now - for an evacuation head count.

Built from the records the gate already keeps, so it works without face
recognition: visitors checked in and not out (with their passengers and
contractor crews), today's staff/contractor/driver gate movements with no
time out, and vehicles the cameras have on site. Where people presence is
switched on (and legally cleared), people the cameras saw recently are added
with where they were last seen.

A muster list is only as good as the check-outs: anyone who left without
being checked out still shows. Print it, call names, tick off.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime, today

from upande_security.cctv.settings import is_on


def _site_ok(farm, f):
	if f.farm:
		return farm == f.farm
	if f.company:
		return frappe.db.get_value("Farm", farm, "company") == f.company if farm else False
	return True


def execute(filters=None):
	f = frappe._dict(filters or {})
	data = []

	for a in frappe.get_all("Appointment", filters={"workflow_state": "Visitor Checked In", "custom_check_out_time": ["is", "not set"]},
			fields=["name", "customer_name", "custom_visitor_type", "custom_farmunit", "custom_meet_with_farm", "custom_check_in_time",
				"custom_meet_with_name", "custom_vehicles_number_plate", "customer_phone_number"], limit=2000):
		farm = a.custom_farmunit if frappe.db.exists("Farm", a.custom_farmunit or "") else a.custom_meet_with_farm
		if not _site_ok(farm, f):
			continue
		base = {"site": farm, "since": a.custom_check_in_time, "source": "Appointment", "record": a.name}
		data.append({**base, "category": a.custom_visitor_type or "Visitor", "name": a.customer_name,
			"detail": " · ".join(filter(None, [f"host {a.custom_meet_with_name}" if a.custom_meet_with_name else None,
				a.custom_vehicles_number_plate, a.customer_phone_number]))})
		for p in frappe.get_all("Appointment Passenger", filters={"parent": a.name, "parenttype": "Appointment"}, fields=["full_name", "phone"]):
			data.append({**base, "category": "Passenger", "name": p.full_name, "detail": f"with {a.customer_name}"})
		for p in frappe.get_all("Contractor Personnel", filters={"parent": a.name, "parenttype": "Appointment"}, fields=["full_name", "is_team_leader"]):
			data.append({**base, "category": "Contractor crew", "name": p.full_name,
				"detail": ("team leader · " if p.is_team_leader else "") + f"with {a.customer_name}"})

	for m in frappe.get_all("Gate Movement", filters={"movement_date": today(), "time_in": ["is", "set"], "time_out": ["is", "not set"]},
			fields=["name", "party_type", "employee_name", "farm", "time_in", "entry_gate", "vehicle_plate"], limit=5000):
		if not _site_ok(m.farm, f):
			continue
		data.append({"category": m.party_type or "Staff", "name": m.employee_name, "site": m.farm,
			"since": f"{today()} {m.time_in}", "detail": " · ".join(filter(None, [m.entry_gate, m.vehicle_plate])),
			"source": "Gate Movement", "record": m.name})

	if is_on("anpr_enabled"):
		for v in frappe.get_all("CCTV Vehicle Visit", filters={"status": ["in", ["On Premises", "Overstayed"]]},
				fields=["name", "plate", "party_name", "party_type", "farm", "entry_time", "last_seen_zone", "last_seen_time"], limit=2000):
			if not _site_ok(v.farm, f):
				continue
			data.append({"category": f"Vehicle ({v.party_type})", "name": f"{v.plate} · {v.party_name}", "site": v.farm, "since": v.entry_time,
				"detail": f"last seen {v.last_seen_zone or ''} {frappe.utils.format_datetime(v.last_seen_time, 'HH:mm') if v.last_seen_time else ''}".strip(),
				"source": "CCTV Vehicle Visit", "record": v.name})

	if is_on("presence_enabled"):
		since = add_to_date(now_datetime(), hours=-12)
		latest = {}
		for s in frappe.get_all("CCTV Person Sighting", filters={"sighting_time": [">=", since]},
				fields=["person_profile", "farm", "zone", "sighting_time", "direction"], order_by="sighting_time asc", limit=20000):
			latest[s.person_profile] = s
		for profile, s in latest.items():
			if s.direction == "out" or not _site_ok(s.farm, f):
				continue
			name = frappe.db.get_value("CCTV Person Profile", profile, "full_name")
			data.append({"category": "Seen by camera", "name": name, "site": s.farm, "since": s.sighting_time,
				"detail": f"last seen in {s.zone or '-'}", "source": "CCTV Person Sighting", "record": profile})

	data.sort(key=lambda r: (r.get("site") or "", r["category"], r.get("name") or ""))
	cols = [
		{"fieldname": "site", "label": _("Site"), "fieldtype": "Link", "options": "Farm", "width": 110},
		{"fieldname": "category", "label": _("Who"), "width": 150},
		{"fieldname": "name", "label": _("Name"), "width": 220},
		{"fieldname": "since", "label": _("Since"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "detail", "label": _("Detail"), "width": 260},
		{"fieldname": "source", "label": _("From"), "width": 150},
		{"fieldname": "record", "label": _("Record"), "fieldtype": "Dynamic Link", "options": "source", "width": 180},
		{"fieldname": "accounted", "label": _("Accounted for"), "fieldtype": "Check", "width": 110},
	]
	people = sum(1 for r in data if not r["category"].startswith("Vehicle"))
	summary = [{"label": _("People"), "value": people, "indicator": "blue"},
		{"label": _("Vehicles"), "value": len(data) - people, "indicator": "gray"}]
	return cols, data, _("Generated {0}. Anyone not checked out still shows.").format(frappe.utils.format_datetime(now_datetime())), None, summary
