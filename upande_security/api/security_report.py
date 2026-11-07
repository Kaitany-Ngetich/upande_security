# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""The security report: the period's patrols (the dashboard's guard
ranking), incidents and watch list, emailed with a PDF attached - on demand
from the Security Dashboard, or on a schedule to the people in Security Ops
Settings' Security Reports table. The guard ranking on its own can also be
downloaded as Excel, CSV or PDF.

Nothing here is tied to one site: farms, companies and people come from the
site's own records, the incident types left out come from Security Ops
Settings (SOS by default), and links point at the site's own URL.

Patrol figures come from patrol_ranking.get_guard_ranking, so the report
says what the dashboard says. Run from the dashboard, everything is limited
to what the sender may see; the scheduled job runs as Administrator and is
narrowed by each subscription's company / farm instead.

The watch list is covert (see watchlist.py): it goes only to recipients
whose login holds Security Head or System Manager - the roles that can open
it in Desk. Everyone else on the same send gets the report without it, and
an address with no login never gets it.
"""

import csv
import datetime
import io
import re

import frappe
from frappe import _

from upande_security.api.patrol_ranking import (
	day_start,
	half_windows,
	get_guard_ranking,
	resolve_period,
	resolve_window,
	security_today,
	window_label,
)
from upande_security.api.security_dashboard import _farms_of_company, hidden_incident_types

# Who may email the report from the dashboard. Downloading the ranking only
# needs what viewing it needs.
SEND_ROLES = ("System Manager", "Security Head", "Security Manager")
WATCHLIST_ROLES = ("System Manager", "Security Head")
# In the order the report shows them. Each subscription (and each send from
# the dashboard) picks which go out.
SECTIONS = ("visitors", "contractors", "staff", "vehicles", "shifts", "patrols", "coverage", "incidents", "watchlist")
SECTION_LABELS = {
	"visitors": "Visitors",
	"contractors": "Contractors",
	"staff": "Staff movements",
	"vehicles": "Vehicles",
	"shifts": "Shift attendance",
	"patrols": "Patrols",
	"coverage": "Patrol coverage maps",
	"incidents": "Incidents",
	"watchlist": "Watch list",
}
# A subscription row's Covers: the whole security day, or its day or night
# half (day start to +12 h, +12 h to the next day start - 06:00-18:00 and
# 18:00-06:00 by default). Halves are for daily reports only.
HALF_OF_COVERS = {"Day": "day", "Night": "night"}
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
OPEN_STATUSES = ("Open", "In Progress")
SEVERITY_ORDER = ("Critical", "High", "Medium", "Low")
# The most incidents / watch list transactions listed in one email; the
# summary counts always cover all of them.
LIST_LIMIT = 300
# Doctypes a subscription cannot pick as "other records": raw or private
# data (GPS fixes, device tokens, people's messages), and the covert watch
# list, which has its own section that only Security Heads receive.
EXCLUDED_DOCTYPES = {
	"Patrol GPS Log", "Guard Device Token", "Security Conversation", "Security Message",
	"Security Watchlist", "Watchlist Activity", "Security Ops Settings",
}
# Columns that hold no value worth a report cell.
_NO_VALUE_TYPES = {"Table", "Table MultiSelect", "HTML", "Button", "Image", "Attach Image", "Signature",
	"Geolocation", "Code", "Text Editor", "HTML Editor", "Markdown Editor", "JSON", "Password"}

COLUMNS = [
	("farm", "Farm"),
	("rank", "Rank"),
	("name", "Guard"),
	("kind", "Type"),
	("score", "Score"),
	("area_ha", "Area patrolled (ha)"),
	("coverage_pct", "Coverage (%)"),
	("cells", "Grid cells"),
	("distance_km", "Distance (km)"),
	("patrol_hours", "Patrol time (h)"),
	("patrols", "Patrols"),
	("valid_scans", "Valid scans"),
	("scans", "All scans"),
	("shifts", "Shifts"),
	("incidents_scored", "Incidents on shift (scored)"),
	("incidents", "Incidents on shift (all)"),
	("incidents_serious", "Serious incidents"),
]



# --- data ----------------------------------------------------------------------

def _ranking(period=None, from_date=None, to_date=None, farm=None, company=None, half="all", with_cells=False):
	return get_guard_ranking(
		period=period or "this_week", from_date=from_date, to_date=to_date, farm=farm, company=company, half=half,
		with_cells=bool(with_cells),
	)


def _scope_label(farm=None, company=None):
	return farm or company or "All farms"


def _scope_farms(farm=None, company=None):
	"""Farm names the report covers, or None for every farm."""
	if farm:
		return [farm]
	if company:
		return _farms_of_company(company)
	return None


def _user_of(email):
	"""The enabled login behind an address, if any."""
	return frappe.db.get_value("User", {"email": email, "enabled": 1}, "name") or (
		frappe.db.get_value("User", {"name": email, "enabled": 1}, "name"))


def allowed_farms(user):
	"""The farms this login may see, from its User Permissions - their Farm
	rows if any (as Desk applies them), else every farm of their Company
	rows - or None when they are not limited at all."""
	perms = frappe.get_all("User Permission", filters={"user": user, "allow": ["in", ["Company", "Farm"]]},
		fields=["allow", "for_value"])
	farms = {p.for_value for p in perms if p.allow == "Farm"}
	companies = [p.for_value for p in perms if p.allow == "Company"]
	if farms:
		if companies:
			farms &= set(frappe.get_all("Farm", filters={"company": ["in", companies]}, pluck="name"))
		return farms
	if companies:
		return set(frappe.get_all("Farm", filters={"company": ["in", companies]}, pluck="name"))
	return None


def covers(user, farm=None, company=None):
	"""True when a report on farm / company (both blank: every farm) holds
	nothing this login is not allowed to see. An address with no login is
	not limited by anything - who gets what is then the sender's call."""
	if not user:
		return True
	allowed = allowed_farms(user)
	if allowed is None:
		return True
	wanted = _scope_farms(farm, company)
	if wanted is None:
		return False
	return set(wanted) <= allowed and bool(allowed)


def default_scope(user):
	"""(farm, company) to fill in for a limited login whose row left both
	blank: their one farm, else their one company. (None, None) when they
	are not limited, or limited to more than one company."""
	allowed = allowed_farms(user)
	if not allowed:
		return None, None
	if len(allowed) == 1:
		return next(iter(allowed)), None
	companies = {frappe.db.get_value("Farm", f, "company") for f in allowed}
	if len(companies) == 1:
		company = companies.pop()
		if set(_farms_of_company(company)) == allowed:
			return None, company
	return None, None


def _incidents(start, end, farm=None, company=None):
	"""Incidents from start up to end, minus the types left out, as the
	person running the report may see them (get_list)."""
	filters = [["incident_datetime", ">=", str(start)], ["incident_datetime", "<", str(end)]]
	farms = _scope_farms(farm, company)
	if farms is not None:
		filters.append(["farm", "in", farms])
	hidden = hidden_incident_types()
	if hidden:
		filters.append(["nature_of_incident", "not in", hidden])
	rows = frappe.get_list(
		"Incident Report",
		filters=filters,
		fields=["name", "incident_datetime", "farm", "location", "nature_of_incident", "severity",
			"status", "reporter_name", "assigned_to", "description"],
		order_by="incident_datetime desc",
		limit_page_length=0,
	)

	def count(key):
		out = {}
		for r in rows:
			k = r.get(key) or "Not set"
			out[k] = out.get(k, 0) + 1
		return out

	return {
		"rows": rows,
		"total": len(rows),
		"open": sum(1 for r in rows if r.status in OPEN_STATUSES),
		"serious": sum(1 for r in rows if r.severity in ("High", "Critical")),
		"by_type": sorted(count("nature_of_incident").items(), key=lambda x: -x[1]),
		"by_severity": sorted(count("severity").items(),
			key=lambda x: SEVERITY_ORDER.index(x[0]) if x[0] in SEVERITY_ORDER else 9),
		"by_status": count("status"),
		"by_farm": sorted(count("farm").items(), key=lambda x: -x[1]),
		"hidden": list(hidden),
	}


def _watchlist(start, end, farm=None, company=None):
	"""Active watches, the window's transactions by watched people, and the
	watches opened or closed in it. A watch restricted to a company only
	appears in reports for that company (or all farms)."""
	start, end = str(start), str(end)
	report_company = company or (frappe.db.get_value("Farm", farm, "company") if farm else None)
	fields = ["name", "full_name", "person_type", "status", "incident", "restrict_to_company", "reason",
		"added_on", "closed_on", "activity_count", "last_activity_on"]
	entries = frappe.get_all(
		"Security Watchlist",
		filters=[["status", "=", "Active"]],
		or_filters=None,
		fields=fields,
		order_by="added_on desc",
		limit_page_length=0,
	)
	closed = frappe.get_all(
		"Security Watchlist",
		filters=[["status", "=", "Inactive"], ["closed_on", ">=", start], ["closed_on", "<", end]],
		fields=fields,
		order_by="closed_on desc",
		limit_page_length=0,
	)

	def in_scope(e):
		return not report_company or not e.restrict_to_company or e.restrict_to_company == report_company

	entries = [e for e in entries if in_scope(e)]
	closed = [e for e in closed if in_scope(e)]
	act_filters = [["occurred_at", ">=", start], ["occurred_at", "<", end]]
	farms = _scope_farms(farm, company)
	if farms is not None:
		act_filters.append(["farm", "in", farms])
	activity = frappe.get_all(
		"Watchlist Activity",
		filters=act_filters,
		fields=["watchlist", "person", "activity_type", "occurred_at", "matched_on", "farm", "gate",
			"reference_doctype", "reference_name"],
		order_by="occurred_at desc",
		limit_page_length=0,
	)
	keep = {e.name for e in entries} | {e.name for e in closed}
	activity = [a for a in activity if a.watchlist in keep]
	per_entry = {}
	for a in activity:
		per_entry[a.watchlist] = per_entry.get(a.watchlist, 0) + 1
	for e in entries + closed:
		e.period_activity = per_entry.get(e.name, 0)
	return {
		"active": entries,
		"closed": closed,
		"opened": sum(1 for e in entries + closed if e.added_on and start <= str(e.added_on) < end),
		"activity": activity,
	}


def _may_see_watchlist(email):
	"""True when this address belongs to an enabled login holding Security
	Head or System Manager."""
	user = frappe.db.get_value("User", {"email": email, "enabled": 1}, "name") or (
		frappe.db.get_value("User", {"name": email, "enabled": 1}, "name"))
	if not user:
		return False
	return bool(set(WATCHLIST_ROLES) & set(frappe.get_roles(user)))


def _fmt_mins(m):
	m = int(m or 0)
	return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def _hhmm(v):
	return frappe.utils.format_datetime(v, "HH:mm") if v else ""


def _in_farms(expr, farms, params):
	"""SQL fragment limiting `expr` to the report's farms (all when None)."""
	if farms is None:
		return ""
	params["farms"] = tuple(farms) or ("__no_farm__",)
	return f" AND {expr} IN %(farms)s"


def _visits(start, end, farm=None, company=None, contractors=False):
	"""Visitors (or contractors) checked in during the window at the
	report's farms: figures, every visit with its times, and overstays."""
	params = {"start": str(start), "end": str(end)}
	who = "a.custom_visitor_type = 'Contractor'" if contractors else "COALESCE(a.custom_visitor_type, '') <> 'Contractor'"
	farm_sql = _in_farms("COALESCE(NULLIF(a.custom_farmunit, ''), a.custom_meet_with_farm)", _scope_farms(farm, company), params)
	rows = frappe.db.sql(
		f"""
		SELECT a.name, a.customer_name, a.customer_organization, a.custom_visitor_type,
			COALESCE(NULLIF(e.employee_name, ''), a.custom_meet_with) AS host,
			COALESCE(NULLIF(a.custom_farmunit, ''), a.custom_meet_with_farm) AS farm,
			a.custom_check_in_time AS time_in, a.custom_check_out_time AS time_out, a.workflow_state
		FROM `tabAppointment` a LEFT JOIN `tabEmployee` e ON e.name = a.custom_meet_with
		WHERE {who}{farm_sql}
		  AND a.custom_check_in_time >= %(start)s AND a.custom_check_in_time < %(end)s
		ORDER BY a.custom_check_in_time
		""",
		params,
		as_dict=True,
	)
	now = frappe.utils.now_datetime()
	out_count, mins, overstays = 0, [], []
	table = []
	for r in rows:
		inside = not r.time_out and r.workflow_state == "Visitor Checked In"
		if r.time_out:
			out_count += 1
			mins.append(frappe.utils.time_diff_in_seconds(r.time_out, r.time_in) / 60)
		stay = frappe.utils.time_diff_in_seconds(r.time_out or now, r.time_in) / 60
		if inside and stay > 8 * 60:
			overstays.append({"label": f"{r.customer_name} · {r.host or '—'}", "detail": f"{_fmt_mins(stay)} inside"})
		table.append([
			_hhmm(r.time_in),
			r.customer_name or "",
			(r.customer_organization or "") if contractors else (r.host or ""),
			r.farm or "",
			_hhmm(r.time_out) if r.time_out else ("inside" if inside else "not recorded"),
			_fmt_mins(stay),
		])
	return {
		"title": SECTION_LABELS["contractors" if contractors else "visitors"],
		"kpis": [
			("Checked in", len(rows), None),
			("Checked out", out_count, None),
			("Still inside", sum(1 for t in table if t[4] == "inside"), None),
			("Average visit", _fmt_mins(sum(mins) / len(mins)) if mins else "—", None),
		],
		"tables": [{
			"title": "Contractor visits" if contractors else "Visits",
			"columns": [("In", "left"), ("Contractor" if contractors else "Visitor", "left"),
				("Company" if contractors else "Host", "left"), ("Farm", "left"), ("Out", "left"), ("Stay", "right")],
			"rows": table[:LIST_LIMIT],
			"more": max(0, len(table) - LIST_LIMIT),
		}],
		"watch": [{"title": "Inside more than 8 hours", "tone": "danger", "rows": overstays}] if overstays else [],
		"empty": "No contractor visits in this period." if contractors else "No visitors in this period.",
	}


def _staff_moves(start, end, farm=None, company=None):
	"""Gate movements (staff, and drivers or others logged the same way) in
	the window at the report's farms."""
	params = {"start": str(start), "end": str(end)}
	farm_sql = _in_farms("m.farm", _scope_farms(farm, company), params)
	rows = frappe.db.sql(
		f"""
		SELECT m.party_type, COALESCE(NULLIF(m.employee_name, ''), m.employee, m.id_number) AS who,
			m.farm, m.entry_gate, m.exit_gate, m.vehicle_plate,
			TIMESTAMP(m.movement_date, m.time_in) AS time_in,
			IF(m.time_out IS NULL, NULL, TIMESTAMP(m.movement_date, m.time_out)) AS time_out
		FROM `tabGate Movement` m
		WHERE m.docstatus < 2{farm_sql}
		  AND TIMESTAMP(m.movement_date, COALESCE(m.time_in, m.time_out)) >= %(start)s
		  AND TIMESTAMP(m.movement_date, COALESCE(m.time_in, m.time_out)) < %(end)s
		ORDER BY time_in
		""",
		params,
		as_dict=True,
	)
	by_type = {}
	for r in rows:
		by_type[r.party_type or "Other"] = by_type.get(r.party_type or "Other", 0) + 1
	still_in = [r for r in rows if r.time_in and not r.time_out]
	return {
		"title": SECTION_LABELS["staff"],
		"kpis": [
			("Movements", len(rows), None),
			("People", len({r.who for r in rows}), None),
			("Still inside", len(still_in), None),
			("With a vehicle", sum(1 for r in rows if r.vehicle_plate), None),
		],
		"breakdown": [("By type", sorted(by_type.items(), key=lambda x: -x[1]))],
		"tables": [{
			"title": "Movements",
			"columns": [("In", "left"), ("Who", "left"), ("Type", "left"), ("Farm / gate", "left"), ("Out", "left"), ("Vehicle", "left")],
			"rows": [[_hhmm(r.time_in), r.who or "", r.party_type or "", " · ".join(x for x in (r.farm, r.entry_gate) if x),
				_hhmm(r.time_out) or "inside", r.vehicle_plate or ""] for r in rows][:LIST_LIMIT],
			"more": max(0, len(rows) - LIST_LIMIT),
		}],
		"watch": [],
		"empty": "No staff gate movements in this period.",
	}


def _vehicles(start, end, farm=None, company=None):
	"""Company vehicles through the gate (Gate Vehicle Verification): exits
	and returns in the window at the report's farms, rejections, and any
	still out."""
	params = {"start": str(start), "end": str(end)}
	farms = _scope_farms(farm, company)
	farm_sql = ""
	if farms is not None:
		params["farms"] = tuple(farms) or ("__no_farm__",)
		farm_sql = " AND (v.from_farm IN %(farms)s OR v.to_farm IN %(farms)s)"
	rows = frappe.db.sql(
		f"""
		SELECT v.vehicle_no, v.from_farm, v.to_farm, v.task_description, v.gate_exit_time, v.gate_exit_status,
			v.gate_entry_time, v.gate_entry_status, v.exit_gate, v.entry_gate
		FROM `tabGate Vehicle Verification` v
		WHERE ((v.gate_exit_time >= %(start)s AND v.gate_exit_time < %(end)s)
		    OR (v.gate_entry_time >= %(start)s AND v.gate_entry_time < %(end)s)){farm_sql}
		ORDER BY COALESCE(v.gate_exit_time, v.gate_entry_time)
		""",
		params,
		as_dict=True,
	)
	rejected = [r for r in rows if r.gate_exit_status == "Rejected" or r.gate_entry_status == "Rejected"]
	out_now = [r for r in rows if r.gate_exit_time and r.gate_exit_status == "Verified" and not r.gate_entry_time]
	return {
		"title": SECTION_LABELS["vehicles"],
		"kpis": [
			("Exits", sum(1 for r in rows if r.gate_exit_time), None),
			("Returns", sum(1 for r in rows if r.gate_entry_time), None),
			("Still out", len(out_now), "#ba7517" if out_now else None),
			("Rejected", len(rejected), "#a32d2d" if rejected else None),
		],
		"tables": [{
			"title": "Vehicle movements",
			"columns": [("Vehicle", "left"), ("Task", "left"), ("Out", "left"), ("Back", "left"), ("Status", "left")],
			"rows": [[r.vehicle_no or "", (r.task_description or "")[:60], _hhmm(r.gate_exit_time), _hhmm(r.gate_entry_time) or ("still out" if r.gate_exit_time else ""),
				"Rejected" if r in rejected else "Verified"] for r in rows][:LIST_LIMIT],
			"more": max(0, len(rows) - LIST_LIMIT),
		}],
		"watch": [{"title": "Rejected at the gate", "tone": "danger",
			"rows": [{"label": r.vehicle_no or "", "detail": (r.task_description or "")[:80]} for r in rejected]}] if rejected else [],
		"empty": "No company vehicles through the gate in this period.",
	}


def _shift_attendance(first, last, farm=None, company=None, window=None):
	"""Who was on duty: shifts starting in the security days first to last,
	checked in (HR biometric where the guard punches one, else the app's
	shift check-in), late, not in, and who was off without cover. `window`
	(start, end) keeps only shifts starting in it - a day or night report;
	off days are dated, not timed, so they go with the day half."""
	from upande_security.api.security_dashboard import _fetch_shifts_tab

	data = _fetch_shifts_tab(first, last, farm=farm, company=company)
	rows = [r for r in data.get("rows") or [] if r.get("status") != "Cancelled"]
	if window:
		a, b = window
		rows = [r for r in rows if r.get("start_date") and a <= frappe.utils.get_datetime(r["start_date"]) < b]
		if (b - a) < datetime.timedelta(hours=13) and a.time() != day_start():
			data["off_days"] = []
	now = frappe.utils.now_datetime()

	def state(r):
		bio = r.get("biometric") or {}
		res = bio.get("result")
		if res in ("On time", "Late", "Absent", "No clock-in"):
			return res
		if r.get("checked_in"):
			return "Checked in"
		start = frappe.utils.get_datetime(r["start_date"]) if r.get("start_date") else None
		return "Not checked in" if start and start <= now else "Upcoming"

	states = [(r, state(r)) for r in rows]
	present = [x for x in states if x[1] in ("On time", "Late", "Checked in")]
	missing = [x for x in states if x[1] in ("Absent", "No clock-in", "Not checked in")]
	late = [x for x in states if x[1] == "Late"]
	off = data.get("off_days") or []
	uncovered = [o for o in off if not o.get("covered_by")]

	def row_of(r, st):
		bio = r.get("biometric") or {}
		return [r.get("guard_name") or "", r.get("farm") or "", r.get("shift_type") or "",
			_hhmm(r.get("start_date")) + "-" + _hhmm(r.get("end_date")),
			st + (f" {bio.get('late_min')}m" if st == "Late" and bio.get("late_min") else "")]

	cols = [("Guard", "left"), ("Farm", "left"), ("Shift", "left"), ("Time", "left"), ("Status", "left")]
	tables = []
	if missing:
		tables.append({"title": "Not checked in", "columns": cols, "rows": [row_of(r, st) for r, st in missing], "more": 0})
	if late:
		tables.append({"title": "Late", "columns": cols, "rows": [row_of(r, st) for r, st in late], "more": 0})
	if off:
		tables.append({"title": "Off", "columns": [("Date", "left"), ("Guard", "left"), ("Farm", "left"), ("Cover", "left")],
			"rows": [[o["date"], o["guard_name"], o.get("farm") or "", o.get("covered_by") or "No cover"] for o in off], "more": 0})
	return {
		"title": SECTION_LABELS["shifts"],
		"kpis": [
			("Shifts", len(rows), None),
			("Checked in", len(present), "#3b6d11"),
			("Not checked in", len(missing), "#a32d2d" if missing else None),
			("Off · no cover", f"{len(off)} · {len(uncovered)}", "#a32d2d" if uncovered else None),
		],
		"tables": tables,
		"watch": [],
		"empty": "No shifts in this period.",
	}


def parse_doctypes(value):
	"""The doctypes a subscription row picked (one per line or comma), in
	order, without repeats."""
	out = []
	for part in re.split(r"[\n,]+", value or ""):
		dt = part.strip()
		if dt and dt not in out:
			out.append(dt)
	return out


def doctype_problem(dt, user=None):
	"""Why dt cannot be a report section (for this user), or None."""
	if dt in EXCLUDED_DOCTYPES:
		return _("{0} cannot be sent in a report.").format(dt)
	row = frappe.db.get_value("DocType", dt, ["istable", "issingle"], as_dict=True)
	if not row:
		return _("{0} is not a doctype on this site.").format(dt)
	if row.istable or row.issingle:
		return _("{0} has no records of its own to list.").format(dt)
	if user and not frappe.has_permission(dt, "read", user=user):
		return _("{0} cannot read {1}.").format(user, dt)
	return None


@frappe.whitelist()
def report_doctype_options():
	"""For the Choose records to include picker: every Upande Security
	doctype and any other doctype whose records carry a farm, minus the
	excluded ones."""
	if not set(SEND_ROLES) & set(frappe.get_roles()):
		return []
	modules = frappe.get_all("Module Def", filters={"app_name": "upande_security"}, pluck="name")
	names = set(frappe.get_all("DocType", filters={"module": ["in", modules], "istable": 0, "issingle": 0}, pluck="name"))
	for table in ("DocField", "Custom Field"):
		names |= set(frappe.get_all(table, filters={"fieldtype": "Link", "options": "Farm"}, pluck="parent" if table == "DocField" else "dt"))
	out = []
	for dt in sorted(names):
		if not doctype_problem(dt):
			out.append({"doctype": dt, "module": frappe.db.get_value("DocType", dt, "module")})
	return out


def _link_field(meta, target):
	for f in meta.fields:
		if f.fieldtype == "Link" and f.options == target:
			return f.fieldname
	return None


def _cell(v):
	if v is None or v == "":
		return ""
	if isinstance(v, datetime.datetime):
		return frappe.utils.format_datetime(v, "d MMM HH:mm")
	if isinstance(v, datetime.date):
		return frappe.utils.format_date(v, "d MMM yyyy")
	text = " ".join(frappe.utils.strip_html(str(v)).split())
	return text if len(text) <= 80 else text[:77] + "…"


def _doctype_section(dt, start, end, farm=None, company=None):
	"""A report section listing dt's records created in start..end, narrowed
	to the report's farms by the doctype's own Farm (else Company) field.
	Read through get_list, so a report sent from the dashboard holds only
	what the sender may see."""
	meta = frappe.get_meta(dt)
	label = _(dt)
	section = {"title": label, "kpis": [], "tables": [], "watch": [], "empty": f"No {label} records in this period."}
	filters = [["creation", ">=", start], ["creation", "<", end]]
	farms = _scope_farms(farm, company)
	if farms is not None:
		farm_f, company_f = _link_field(meta, "Farm"), _link_field(meta, "Company")
		if farm_f:
			filters.append([farm_f, "in", farms or [""]])
		elif company_f:
			companies = [company] if company else list({frappe.db.get_value("Farm", f, "company") for f in farms})
			filters.append([company_f, "in", companies or [""]])
		else:
			section["empty"] = f"{label} records have no farm or company, so they are left out of a report on {_scope_label(farm, company)}."
			return section
	cols = [f for f in meta.fields if f.in_list_view and f.fieldtype not in _NO_VALUE_TYPES][:5]
	if meta.title_field and meta.title_field not in [f.fieldname for f in cols] and meta.has_field(meta.title_field):
		cols = [meta.get_field(meta.title_field)] + cols[:4]
	total = frappe.get_list(dt, filters=filters, fields=[{"COUNT": "*", "as": "n"}])[0].n
	rows = frappe.get_list(dt, filters=filters, fields=["name", "creation"] + [f.fieldname for f in cols],
		order_by="creation desc", limit_page_length=LIST_LIMIT)
	section["kpis"] = [("Records", total, None)]
	if rows:
		section["tables"] = [{
			"title": label,
			"columns": [("Created", "left"), ("ID", "left")] + [(_(f.label), "left") for f in cols],
			"rows": [[_cell(r.creation), r.name] + [_cell(r.get(f.fieldname)) for f in cols] for r in rows],
			"more": max(0, total - len(rows)),
		}]
	return section


def build_report(first, last, farm=None, company=None, sections=SECTIONS, half="all", doctypes=()):
	"""Everything the report shows for the security days first to last
	(each running from the day start, 06:00 unless changed, to the same time
	next day), worked out once and shared by every recipient of one send.
	half "day" / "night" narrows a one-day report to that half of the day."""
	# An empty list is a report of picked doctypes only; None is every section.
	sections = [s for s in SECTIONS if s in (SECTIONS if sections is None else sections)]
	first, last, start, end = resolve_window("custom", str(first), str(last))
	half = half if half in ("day", "night") and first == last else "all"
	window = None
	if half != "all":
		start, end = half_windows(first, last, start, end, half)[0]
		window = (start, end)
	report = {"from_date": str(first), "to_date": str(last), "start": str(start), "end": str(end),
		"period_text": window_label(start, end), "scope": _scope_label(farm, company), "half": half,
		"doctypes": list(doctypes or []),
		"sections": sections, "brand": _brand(farm, company), "farm": farm, "company": company}
	if half != "all":
		report["period_text"] += " · " + ("day" if half == "day" else "night")
	# The gate and shift sections share one shape (figures, tables, watch
	# lists) and one template block.
	gate = []
	if "visitors" in sections:
		gate.append(_visits(start, end, farm, company))
	if "contractors" in sections:
		gate.append(_visits(start, end, farm, company, contractors=True))
	if "staff" in sections:
		gate.append(_staff_moves(start, end, farm, company))
	if "vehicles" in sections:
		gate.append(_vehicles(start, end, farm, company))
	if "shifts" in sections:
		gate.append(_shift_attendance(first, last, farm, company, window))
	for dt in doctypes or []:
		if doctype_problem(dt):
			continue
		try:
			gate.append(_doctype_section(dt, start, end, farm, company))
		except Exception:
			frappe.log_error(f"Security report: {dt} section failed")
	report["gate_sections"] = gate
	if "patrols" in sections or "coverage" in sections:
		ranking = _ranking("custom", str(first), str(last), farm, company, half=half, with_cells="coverage" in sections)
		if "patrols" in sections:
			report["ranking"] = {k: v for k, v in ranking.items() if k != "covered_cells"}
		if "coverage" in sections:
			from upande_security.api.coverage_map import farm_coverage_maps

			# The farms in scope that have a usable boundary.
			farms_with_grid = list(ranking.get("covered_cells") or {})
			report["coverage_maps"] = farm_coverage_maps(farms_with_grid, start, end, ranking.get("farms"))
	if "incidents" in sections:
		report["incidents"] = _incidents(start, end, farm, company)
	if "watchlist" in sections:
		report["watchlist"] = _watchlist(start, end, farm, company)
	return report


# --- rendering -----------------------------------------------------------------

def _fmt_hours(h):
	m = int(round((h or 0) * 60))
	return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def _fmt_ha(x):
	if x is None:
		return "—"
	return f"{x:.0f} ha" if x >= 100 else (f"{x:.1f} ha" if x >= 10 else f"{x:.2f} ha")


def _period_text(first, last):
	return str(first) if str(first) == str(last) else f"{first} to {last}"


def _dt(v):
	return frappe.utils.format_datetime(v, "dd MMM yyyy HH:mm") if v else ""


def _brand(farm=None, company=None):
	"""Whose report this is, for its heading: the company of the report's
	scope. A report on every farm spans companies, so it says so."""
	if company:
		return company
	if farm:
		c = frappe.db.get_value("Farm", farm, "company")
		if c:
			return c
	return _("All companies")


NEUTRAL_ACCENT = "#1f1f1c"
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _mix(hex_colour, other, share):
	"""hex_colour moved `share` of the way towards other."""
	a = [int(hex_colour[i:i + 2], 16) for i in (1, 3, 5)]
	b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
	return "#" + "".join(f"{round(x + (y - x) * share):02x}" for x, y in zip(a, b))


def _luminance(hex_colour):
	def ch(c):
		c = c / 255
		return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
	r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
	return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _logo_src(path, for_pdf):
	"""The logo for an <img>: the public URL for email (mail clients block
	inline data), the file itself inlined for the PDF (the PDF renderer
	cannot always reach the site's own URL)."""
	if not path:
		return None
	if not for_pdf:
		return None if path.startswith("/private/") else frappe.utils.get_url(path)
	try:
		import base64
		import mimetypes

		f = frappe.get_doc("File", {"file_url": path})
		mime = mimetypes.guess_type(path)[0] or "image/png"
		return f"data:{mime};base64," + base64.b64encode(f.get_content()).decode()
	except Exception:
		return None


def _theme(report, for_pdf=False):
	"""Each company's report in its own colour: the company's colour (and
	logo) from Security Ops Settings > Badges per Company - the same one its
	badges print in, a farm's own row winning over the company's. A report
	spanning companies stays neutral. Red / green / severity colours are
	never themed, so they read the same in every company's report."""
	farm, company = report.get("farm"), report.get("company")
	if farm and not company:
		company = frappe.db.get_value("Farm", farm, "company")
	accent, logo = NEUTRAL_ACCENT, None
	if company:
		from upande_security.api.badge_branding import get_badge_branding

		b = get_badge_branding(company, farm)
		if b.badge_colour and HEX_RE.match(b.badge_colour):
			accent = b.badge_colour
		logo = b.logo
	dark = _luminance(accent) < 0.4
	return frappe._dict(
		accent=accent,
		soft=_mix(accent, "#ffffff", 0.88),
		on_accent="#ffffff" if dark else "#1f1f1c",
		on_accent_muted=_mix("#ffffff" if dark else "#1f1f1c", accent, 0.3),
		logo=_logo_src(logo, for_pdf),
	)


def render_html(report, note=None, with_watchlist=False, for_pdf=False):
	"""The report through templates/security_report.html - the email body
	and, through get_pdf, the PDF (for_pdf inlines the logo)."""
	r = frappe._dict(report)
	r.period_text = r.get("period_text") or _period_text(r.from_date, r.to_date)
	if r.get("ranking"):
		by_farm = {}
		for g in r.ranking.get("rows") or []:
			by_farm.setdefault(g["farm"], []).append(frappe._dict(g))
		r.guards_by_farm = by_farm
		r.ranking = frappe._dict(r.ranking, farms=[frappe._dict(f) for f in r.ranking.get("farms") or []])
		measured = [f for f in r.ranking.farms if f.get("covered_ha") is not None]
		r.area_total = frappe._dict(
			covered=sum(f.covered_ha for f in measured), area=sum(f.area_ha or 0 for f in measured)
		) if measured else None
	if r.get("incidents"):
		for i in r.incidents["rows"]:
			text = " ".join(frappe.utils.strip_html(i.description or "").split())
			i.summary = text if len(text) <= 240 else text[:237].rsplit(" ", 1)[0] + "…"
		r.incidents = frappe._dict(r.incidents)
	if r.get("watchlist"):
		r.watchlist = frappe._dict(r.watchlist)
	if r.get("coverage_maps"):
		r.coverage_maps = [frappe._dict(m) for m in r.coverage_maps]
	return frappe.render_template(
		"upande_security/templates/security_report.html",
		{
			"r": r,
			"theme": _theme(report, for_pdf),
			"with_watchlist": with_watchlist,
			"note": note,
			"for_pdf": for_pdf,
			"brand": r.get("brand") or _brand(),
			"generated": frappe.utils.format_datetime(frappe.utils.now_datetime(), "dd MMM yyyy HH:mm"),
			"dashboard_url": frappe.utils.get_url("/security-dashboard"),
			"list_limit": LIST_LIMIT,
			"ha": _fmt_ha,
			"hours": _fmt_hours,
			"dt": _dt,
			"pct": lambda x: f"{round((x or 0) * 100)}%",
			"form_url": frappe.utils.get_url_to_form,
		},
	)


def _pdf(html):
	from frappe.utils.pdf import get_pdf

	page = "<!doctype html><html><head><meta charset='utf-8'></head><body style='margin:0'>" + html + "</body></html>"
	return get_pdf(page, {"orientation": "Portrait", "page-size": "A4", "margin-top": "12mm", "margin-bottom": "12mm", "margin-left": "10mm", "margin-right": "10mm"})


def _filename(prefix, first, last, scope):
	slug = re.sub(r"[^A-Za-z0-9]+", "-", scope).strip("-") or "all"
	return f"{prefix}-{slug}-{first}-to-{last}"


# --- downloads -----------------------------------------------------------------

def _table_rows(data):
	"""The ranking as rows for Excel and CSV: header, one row per guard,
	then each farm's total row."""
	out = [[label for _k, label in COLUMNS]]
	by_farm = {}
	for r in data.get("rows") or []:
		by_farm.setdefault(r["farm"], []).append(r)
	for f in data.get("farms") or []:
		for r in by_farm.get(f["farm"], []):
			out.append([r.get(k) for k, _l in COLUMNS])
		out.append([
			f["farm"], "", "Farm total", f"{f['guards']} guards", "",
			f.get("covered_ha"), f.get("coverage_pct"), "",
			f.get("distance_km"), f.get("patrol_hours"), f.get("patrols"),
			f.get("valid_scans"), f.get("scans"), "", "", "", "",
		])
	return out


@frappe.whitelist()
def export_ranking(fmt="xlsx", period=None, from_date=None, to_date=None, farm=None, company=None, half="all"):
	"""Download what the dashboard shows: the guard ranking as Excel, CSV or
	PDF, or ("report") the whole security report as a PDF - its watch list
	included only for a Security Head or System Manager."""
	from frappe.desk.utils import provide_binary_file

	scope = _scope_label(farm, company)
	if fmt == "report":
		first, last = resolve_period(period, from_date, to_date)
		report = build_report(first, last, farm, company)
		html = render_html(report, with_watchlist=bool(set(WATCHLIST_ROLES) & set(frappe.get_roles())), for_pdf=True)
		provide_binary_file(_filename("security-report", first, last, scope), "pdf", _pdf(html))
		return
	data = _ranking(period, from_date, to_date, farm, company, half)
	name = _filename("guard-ranking" + ("-" + half if half in ("day", "night") else ""), data["from_date"], data["to_date"], scope)
	if fmt == "pdf":
		report = {"from_date": data["from_date"], "to_date": data["to_date"], "scope": scope,
			"sections": ["patrols"], "ranking": data, "brand": _brand(farm, company), "farm": farm, "company": company,
			"period_text": data.get("window_label")}
		provide_binary_file(name, "pdf", _pdf(render_html(report, for_pdf=True)))
	elif fmt == "csv":
		buf = io.StringIO()
		csv.writer(buf).writerows(_table_rows(data))
		provide_binary_file(name, "csv", buf.getvalue().encode("utf-8-sig"))
	else:
		from frappe.utils.xlsxutils import make_xlsx

		provide_binary_file(name, "xlsx", make_xlsx(_table_rows(data), "Guard ranking").getvalue())


# --- sending -------------------------------------------------------------------

def _clean_emails(recipients):
	if isinstance(recipients, str):
		try:
			parsed = frappe.parse_json(recipients)
			recipients = parsed if isinstance(parsed, list) else recipients
		except Exception:
			pass
	if isinstance(recipients, str):
		recipients = re.split(r"[,;\s]+", recipients)
	out, seen = [], set()
	for e in recipients or []:
		e = (e or "").strip()
		if e and e.lower() not in seen:
			if not EMAIL_RE.match(e):
				frappe.throw(_("{0} is not a valid email address.").format(frappe.bold(e)))
			seen.add(e.lower())
			out.append(e)
	return out


def _clean_sections(sections):
	if isinstance(sections, str):
		try:
			sections = frappe.parse_json(sections)
		except Exception:
			sections = sections.split(",")
	out = [s for s in SECTIONS if s in (sections or [])]
	return out or list(SECTIONS)


def deliver(recipients, report, note=None):
	"""Email the report. Recipients who may see the watch list get it;
	the rest get the same report without it, in a separate email so it
	never reaches them even as a Cc."""
	with_wl = "watchlist" in report["sections"]
	groups = {True: [], False: []}
	for e in recipients:
		groups[with_wl and _may_see_watchlist(e)].append(e)
	subject = f"Security report · {report['scope']} · {report.get('period_text') or _period_text(report['from_date'], report['to_date'])}"
	fname = _filename("security-report", report["from_date"], report["to_date"], report["scope"]) + ".pdf"
	for show_wl, people in groups.items():
		if not people:
			continue
		html = render_html(report, note, with_watchlist=show_wl)
		pdf = _pdf(render_html(report, note, with_watchlist=show_wl, for_pdf=True))
		frappe.sendmail(
			recipients=people,
			subject=subject,
			message=html,
			attachments=[{"fname": fname, "fcontent": pdf}],
			now=False,
		)


@frappe.whitelist(methods=["POST"])
def send_report(recipients, period=None, from_date=None, to_date=None, farm=None, company=None,
		sections=None, note=None):
	"""The dashboard's Send report button: email the security report for the
	period and scope on screen. Built in the background (a month of patrols
	and the PDF can take a while)."""
	if not set(SEND_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only a Security Head or Security Manager can send the report."), frappe.PermissionError)
	emails = _clean_emails(recipients)
	if not emails:
		frappe.throw(_("Add at least one email address."))
	if len(emails) > 50:
		frappe.throw(_("Send to 50 people at most at a time."))
	outside = [e for e in emails if not covers(_user_of(e), farm, company)]
	if outside:
		frappe.throw(_("{0} cannot see everything in a report on {1}. Pick a narrower company or farm, or leave them out.").format(
			", ".join(outside), frappe.bold(_scope_label(farm, company))))
	sections = _clean_sections(sections)
	# Only someone who can read the watch list can send it.
	if "watchlist" in sections and not frappe.has_permission("Security Watchlist", ptype="read"):
		sections = [s for s in sections if s != "watchlist"]
	if {"patrols", "coverage"} & set(sections) and not frappe.has_permission("Patrol GPS Log", ptype="read"):
		frappe.throw(_("You do not have permission to view Patrol GPS Logs."), frappe.PermissionError)
	first, last = resolve_period(period, from_date, to_date)
	if frappe.utils.date_diff(last, first) > 92:
		frappe.throw(_("Pick a period of three months or less."))
	frappe.enqueue(
		"upande_security.api.security_report._send_now",
		queue="long",
		timeout=1500,
		recipients=emails,
		first=str(first),
		last=str(last),
		farm=farm or None,
		company=company or None,
		sections=sections,
		note=(note or "").strip()[:1000] or None,
	)
	return {"queued": True, "recipients": emails, "sections": sections}


def _send_now(recipients, first, last, farm=None, company=None, sections=SECTIONS, note=None):
	"""Background half of send_report - runs as the sender, so it holds
	only what they can see."""
	try:
		report = build_report(first, last, farm, company, sections)
		sender = frappe.utils.get_fullname(frappe.session.user)
		note = f"{note}\n\n— {sender}" if note else f"Sent by {sender} from the Security Dashboard."
		deliver(recipients, report, note)
	except Exception:
		frappe.log_error("Security report send failed")
		raise


@frappe.whitelist()
def report_recipient_options():
	"""For the Send report dialog: suggested people (the subscription list
	and everyone with a security role, marking who would get the watch
	list) and the incident types the report leaves out."""
	if not set(SEND_ROLES) & set(frappe.get_roles()):
		return {"people": [], "hidden_incident_types": []}
	people = {}
	for row in frappe.get_all(
		"Security Report Subscription", fields=["user", "email"], filters={"parenttype": "Security Ops Settings"}
	):
		if row.email:
			people[row.email.lower()] = {"email": row.email,
				"name": frappe.utils.get_fullname(row.user) if row.user else row.email}
	users = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": ["in", ["Security Head", "Security Manager", "Security Supervisor"]]},
		pluck="parent",
		distinct=True,
	)
	for u in frappe.get_all("User", filters={"name": ["in", users or ["__none__"]], "enabled": 1},
			fields=["name", "full_name", "email"]):
		if u.email and u.email.lower() not in people:
			people[u.email.lower()] = {"email": u.email, "name": u.full_name or u.email}
	for p in people.values():
		p["watchlist"] = _may_see_watchlist(p["email"])
	return {
		"people": sorted(people.values(), key=lambda p: (p["name"] or "").lower()),
		"hidden_incident_types": list(hidden_incident_types()),
	}


# --- schedule --------------------------------------------------------------------

def _row_half(row):
	"""'day' / 'night' for a daily row covering half the security day, else 'all'."""
	if row.get("frequency") == "Daily":
		return HALF_OF_COVERS.get(row.get("covers") or "", "all")
	return "all"


def _due_period(row, today, now=None):
	"""(first, last) when this subscription is due today, else None.
	Daily: yesterday; Weekly: last week, on the chosen weekday; Monthly:
	last month, on the 1st. A daily Day row: the latest day half that has
	ended (today's from the half's end, 18:00 by default, else yesterday's);
	a daily Night row: the night that ended at this morning's day start."""
	if row.frequency == "Daily":
		y = frappe.utils.add_days(today, -1)
		if _row_half(row) == "day":
			now = now or frappe.utils.now_datetime()
			day_end = datetime.datetime.combine(today, day_start()) + datetime.timedelta(hours=12)
			return (today, today) if now >= day_end else (y, y)
		return y, y
	if row.frequency == "Weekly":
		if WEEKDAYS[today.weekday()] != (row.send_on or "Monday"):
			return None
		monday = frappe.utils.add_days(today, -today.weekday())
		return frappe.utils.add_days(monday, -7), frappe.utils.add_days(monday, -1)
	if row.frequency == "Monthly":
		if today.day != 1:
			return None
		last = frappe.utils.add_days(today, -1)
		return last.replace(day=1), last
	return None


def _row_sections(row):
	return tuple(sec for sec in SECTIONS if row.get("include_" + sec))


def _group_rows(rows):
	"""{(farm, company, sections, half, doctypes): rows} - rows asking for
	the same report share one build."""
	groups = {}
	for r in rows:
		sections = _row_sections(r)
		doctypes = tuple(parse_doctypes(r.get("doctypes")))
		if sections or doctypes:
			key = (r.farm or "", "" if r.farm else (r.company or ""), sections, _row_half(r), doctypes)
			groups.setdefault(key, []).append(r)
	return groups


def _still_allowed(r):
	"""Access may have changed since the row was saved."""
	if covers(r.user or _user_of(r.email), r.farm, r.company):
		return True
	frappe.log_error(f"Security report not sent to {r.email}",
		f"{r.email} can no longer see everything in a report on {_scope_label(r.farm, r.company)}. "
		"Fix the row in Security Ops Settings > Security Reports.")
	return False


def _send_group(first, last, farm, company, sections, members, note, half="all", doctypes=()):
	report = build_report(first, last, farm or None, company or None, sections, half, doctypes)
	deliver(_clean_emails([m.email for m in members]), report, note)


DEFAULT_SEND_AT = datetime.time(7, 0)


def _send_at(row):
	try:
		return frappe.utils.get_time(row.send_at) if row.send_at else DEFAULT_SEND_AT
	except Exception:
		return DEFAULT_SEND_AT


def send_scheduled_reports():
	"""Every 15 minutes (hooks cron): email each subscription whose Send At
	time has passed today and that has not gone out today. Daily covers the
	last finished security day; weekly and monthly the last finished week or
	month. Rows asking for the same report share one build and one email per
	audience; last_sent_on keeps it to once a day."""
	now = frappe.utils.now_datetime()
	today = now.date()
	# The security day it is now: a Send At before the day start (05:00)
	# reports on the day before the one still running.
	sec_today = security_today(now)
	settings = frappe.get_single("Security Ops Settings")
	rows = [r for r in (settings.get("security_report_subscriptions") or []) if r.enabled and r.email]
	due_rows = {}
	for r in rows:
		if r.last_sent_on and frappe.utils.getdate(r.last_sent_on) == today:
			continue
		if now.time() < _send_at(r):
			continue
		if not _still_allowed(r):
			continue
		due = _due_period(r, sec_today, now)
		if due:
			due_rows.setdefault(due, []).append(r)
	for due, members_due in due_rows.items():
		first, last = due
		for (farm, company, sections, half, doctypes), members in _group_rows(members_due).items():
			try:
				freq = {m.frequency.lower() for m in members}
				kind = {"day": " day", "night": " night"}.get(half, "")
				_send_group(first, last, farm, company, sections, members,
					f"Your {' / '.join(sorted(freq))}{kind} security report.", half, doctypes)
				for m in members:
					frappe.db.set_value("Security Report Subscription", m.name, "last_sent_on", today,
						update_modified=False)
				frappe.db.commit()
			except Exception:
				frappe.db.rollback()
				frappe.log_error(f"Security report for {_scope_label(farm, company)} failed")


@frappe.whitelist(methods=["POST"])
def send_to_subscribers_now(day=None):
	"""Email every enabled subscriber now, whatever their frequency, the
	report for one security day (default: the last full one - yesterday
	06:00 to today 06:00). Does not touch their schedule. For a Security
	Head or System Manager; built in the background."""
	if not set(WATCHLIST_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only a Security Head or System Manager can send to every subscriber."), frappe.PermissionError)
	day = frappe.utils.getdate(day) if day else frappe.utils.add_days(security_today(), -1)
	if day >= security_today():
		frappe.throw(_("Pick a security day that has ended."))
	frappe.enqueue("upande_security.api.security_report._send_to_subscribers", queue="long", timeout=3000,
		day=str(day))
	return {"queued": True, "day": str(day)}


def _send_to_subscribers(day):
	settings = frappe.get_single("Security Ops Settings")
	rows = [r for r in (settings.get("security_report_subscriptions") or [])
		if r.enabled and r.email and _still_allowed(r)]
	for (farm, company, sections, half, doctypes), members in _group_rows(rows).items():
		try:
			_send_group(day, day, farm, company, sections, members, "Your security report.", half, doctypes)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(f"Security report for {_scope_label(farm, company)} failed")
