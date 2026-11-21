# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Read endpoints for the Dashboard v2 CCTV pages.

Lists go through frappe.get_list, so the user's own permissions (and their
site/company User Permissions) decide what they see - the same rule the
alert links and tokens use.
"""

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, getdate, now_datetime, time_diff_in_seconds

from upande_security.cctv.settings import get_settings, require

OPS_ROLES = {"System Manager", "Security Head", "Security Manager", "CCTV Operator"}
GATE_ROLES = OPS_ROLES | {"Gate Guard"}


def capabilities():
	"""For the dashboard bootstrap: which CCTV pages this user gets, if any."""
	s = get_settings()
	roles = set(frappe.get_roles())
	ops = bool(roles & OPS_ROLES)
	gate = bool(roles & GATE_ROLES)
	s = frappe._dict(s, enabled=s.enabled and s.ops_flag)
	return {
		"enabled": s.enabled,
		"live": s.enabled and s.live_view_enabled and gate,
		"alerts": s.enabled and s.alerts_enabled and (ops or "Gate Guard" in roles),
		"vehicles": s.enabled and s.anpr_enabled and gate,
		"review": s.enabled and s.anpr_enabled and gate,
		"health": s.enabled and ops,
		"presence": s.enabled and s.presence_enabled and ops,
		"map": s.enabled and gate,
		"manage": bool(roles & {"System Manager", "Security Head"}),
	}


def _scope(filters, company=None, farm=None, site_field="farm"):
	if farm:
		filters[site_field] = farm
	elif company:
		filters[site_field] = ["in", frappe.get_all("Farm", filters={"company": company}, pluck="name") or ["-"]]
	return filters


def _window(field, from_date, to_date, days=7):
	to = getdate(to_date) if to_date else getdate()
	frm = getdate(from_date) if from_date else add_days(to, -days + 1)
	return [field, "between", [f"{frm} 00:00:00", f"{to} 23:59:59"]]


def _camera_names(rows, field="camera"):
	names = {r.get(field) for r in rows if r.get(field)}
	if not names:
		return {}
	return dict(frappe.get_all("CCTV Camera", filters={"name": ["in", list(names)]}, fields=["name", "camera_name"], as_list=True))


# ------------------------------------------------------------------ alerts

@frappe.whitelist()
def alert_board(status=None, severity=None, alert_type=None, company=None, farm=None, from_date=None, to_date=None,
		search=None, start=0, page_length=50):
	require("alerts_enabled")
	base = [*_as_list(_scope({}, company, farm)), _window("event_time", from_date, to_date)]
	if severity:
		base.append(["severity", "=", severity])
	if alert_type:
		base.append(["alert_type", "=", alert_type])
	like = f"%{search}%" if search else None
	or_filters = [["plate", "like", like], ["person_name", "like", like], ["summary", "like", like], ["name", "like", like]] if like else None

	def names(extra):
		return frappe.get_list("CCTV Alert", filters=[*base, *extra], or_filters=or_filters, pluck="name", limit_page_length=0)

	counts = {st: len(names([["status", "=", st]])) for st in ("Open", "Escalated", "Acknowledged", "Resolved", "False Alarm")}
	if status == "Active":
		f = [*base, ["status", "in", ["Open", "Acknowledged", "Escalated"]]]
	elif status:
		f = [*base, ["status", "=", status]]
	else:
		f = base
	rows = frappe.get_list("CCTV Alert", filters=f, or_filters=or_filters,
		fields=["name", "alert_type", "severity", "status", "summary", "farm", "zone", "camera", "event_time", "plate", "person_name",
			"snapshot", "acknowledged_by", "escalation_level", "repeat_count", "vehicle_visit", "incident"],
		order_by="event_time desc", start=int(start), page_length=int(page_length))
	rank_status = {"Open": 0, "Escalated": 0, "Acknowledged": 1, "Resolved": 2, "False Alarm": 2}
	rank_sev = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
	rows.sort(key=lambda r: (rank_status.get(r.status, 3), rank_sev.get(r.severity, 5)))
	cams = _camera_names(rows)
	for r in rows:
		r.camera_name = cams.get(r.camera)
	return {"counts": counts, "total": len(names(f[len(base):])), "start": int(start), "rows": rows}


def _as_list(filters):
	out = []
	for k, v in filters.items():
		out.append([k, v[0], v[1]] if isinstance(v, list) else [k, "=", v])
	return out


@frappe.whitelist()
def alert_detail(name):
	require("alerts_enabled")
	doc = frappe.get_doc("CCTV Alert", name)
	if not frappe.has_permission("CCTV Alert", "read", doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	d = doc.as_dict()
	cams = [doc.camera] + [r.camera for r in doc.related_cameras]
	names = dict(frappe.get_all("CCTV Camera", filters={"name": ["in", [c for c in cams if c] or ["-"]]}, fields=["name", "camera_name"], as_list=True))
	d["camera_name"] = names.get(doc.camera)
	d["related"] = [{"camera": r.camera, "camera_name": names.get(r.camera), "reason": r.reason} for r in doc.related_cameras]
	d["can_act"] = frappe.has_permission("CCTV Alert", "write", doc)
	d["false_alarm_reasons"] = [o for o in (frappe.get_meta("CCTV Alert").get_field("false_alarm_reason").options or "").split("\n") if o]
	if doc.vehicle_visit:
		d["visit"] = frappe.db.get_value("CCTV Vehicle Visit", doc.vehicle_visit,
			["name", "plate", "party_name", "party_type", "entry_time", "exit_time", "status"], as_dict=True)
	return d


# ------------------------------------------------------------------ vehicles

@frappe.whitelist()
def visit_board(status=None, company=None, farm=None, from_date=None, to_date=None, search=None, start=0, page_length=50):
	require("anpr_enabled")
	f = _as_list(_scope({}, company, farm))
	on_site = status in (None, "", "On Site")
	if on_site:
		f.append(["status", "in", ["On Premises", "Overstayed"]])
	else:
		f.append(_window("entry_time", from_date, to_date))
		if status and status != "All":
			f.append(["status", "=", status])
	or_filters = [["plate", "like", f"%{search}%"], ["party_name", "like", f"%{search}%"]] if search else None
	rows = frappe.get_list("CCTV Vehicle Visit", filters=f, or_filters=or_filters,
		fields=["name", "plate", "party_type", "party_name", "source", "reference_doctype", "reference_name", "appointment", "farm",
			"status", "entry_time", "exit_time", "expected_exit", "total_minutes", "last_seen_time", "last_seen_camera", "last_seen_zone",
			"entry_camera", "entry_snapshot", "guard_confirmed", "flags_text", "colour", "vehicle_class"],
		order_by="entry_time desc", start=int(start), page_length=int(page_length))
	now = now_datetime()
	cams = _camera_names(rows, "last_seen_camera")
	for r in rows:
		r.minutes_inside = r.total_minutes if r.exit_time else (int(time_diff_in_seconds(now, r.entry_time) // 60) if r.entry_time else None)
		r.seen_minutes_ago = int(time_diff_in_seconds(now, r.last_seen_time) // 60) if r.last_seen_time else None
		r.last_seen_camera_name = cams.get(r.last_seen_camera)
		r.overdue = bool(r.expected_exit and not r.exit_time and get_datetime(r.expected_exit) < now)
	base = _as_list(_scope({}, company, farm))
	kpis = {
		"on_site": frappe.db.count("CCTV Vehicle Visit", {**_scope({}, company, farm), "status": ["in", ["On Premises", "Overstayed"]]}),
		"overstayed": frappe.db.count("CCTV Vehicle Visit", {**_scope({}, company, farm), "status": "Overstayed"}),
		"arrivals_today": len(frappe.get_list("CCTV Vehicle Visit", filters=[*base, ["entry_time", ">=", f"{getdate()} 00:00:00"]], pluck="name", limit_page_length=0)),
		"departures_today": len(frappe.get_list("CCTV Vehicle Visit", filters=[*base, ["exit_time", ">=", f"{getdate()} 00:00:00"]], pluck="name", limit_page_length=0)),
		"unconfirmed": frappe.db.count("CCTV Vehicle Visit", {**_scope({}, company, farm), "status": ["in", ["On Premises", "Overstayed"]], "guard_confirmed": 0}),
		"review_open": frappe.db.count("CCTV Review Item", {**_scope({}, company, farm), "status": ["in", ["Open", "Escalated"]]}),
	}
	total = len(frappe.get_list("CCTV Vehicle Visit", filters=f, or_filters=or_filters, pluck="name", limit_page_length=0))
	return {"kpis": kpis, "total": total, "start": int(start), "rows": rows}


@frappe.whitelist()
def visit_detail(name):
	require("anpr_enabled")
	doc = frappe.get_doc("CCTV Vehicle Visit", name)
	if not frappe.has_permission("CCTV Vehicle Visit", "read", doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	d = doc.as_dict()
	d["sightings"] = frappe.get_list("CCTV Vehicle Sighting", filters={"vehicle_visit": name},
		fields=["name", "sighting_time", "camera", "zone", "gate", "direction", "plate_read", "confidence", "plate_image", "vehicle_image"],
		order_by="sighting_time asc", limit_page_length=200)
	cams = _camera_names(d["sightings"])
	for s in d["sightings"]:
		s.camera_name = cams.get(s.camera)
	return d


@frappe.whitelist()
def review_board(company=None, farm=None, status="Open", start=0, page_length=50):
	require("anpr_enabled")
	f = _scope({}, company, farm)
	f["status"] = ["in", ["Open", "Escalated"]] if status in (None, "", "Open") else status
	rows = frappe.get_list("CCTV Review Item", filters=f,
		fields=["name", "reason", "status", "plate", "farm", "sighting", "vehicle_visit", "sla_due", "creation", "resolution", "resolved_by", "resolved_at"],
		order_by="creation desc", start=int(start), page_length=int(page_length))
	now = now_datetime()
	for r in rows:
		r.candidates = frappe.get_all("CCTV Review Candidate", filters={"parent": r.name, "parenttype": "CCTV Review Item"},
			fields=["reference_doctype", "reference_name", "label", "score"], order_by="score desc")
		if r.sighting:
			s = frappe.db.get_value("CCTV Vehicle Sighting", r.sighting,
				["plate_read", "confidence", "plate_image", "vehicle_image", "camera", "sighting_time", "direction", "colour"], as_dict=True) or {}
			r.update({"sighting_" + k: v for k, v in s.items()})
		r.late = bool(r.sla_due and get_datetime(r.sla_due) < now and r.status != "Resolved")
	counts = {st: frappe.db.count("CCTV Review Item", {**_scope({}, company, farm), "status": st}) for st in ("Open", "Escalated", "Resolved")}
	return {"counts": counts, "rows": rows}


@frappe.whitelist()
def search_link_targets(farm=None, txt=""):
	"""Records a guard may link an unmatched plate to: today's appointments at the
	site, open deliveries, stickers and known vehicles."""
	require("anpr_enabled")
	like = f"%{txt}%"
	today = getdate()
	out = []
	for r in frappe.get_list("Appointment", filters=[["scheduled_time", "between", [f"{add_days(today, -1)} 00:00:00", f"{add_days(today, 1)} 23:59:59"]],
			*([["custom_meet_with_farm", "=", farm]] if farm else [])],
			or_filters=[["customer_name", "like", like], ["custom_vehicles_number_plate", "like", like], ["name", "like", like]],
			fields=["name", "customer_name", "custom_vehicles_number_plate", "custom_visitor_type", "scheduled_time"], limit_page_length=15):
		out.append({"doctype": "Appointment", "name": r.name, "label": f"{r.customer_name} · {r.custom_visitor_type or 'Visitor'}",
			"plate": r.custom_vehicles_number_plate, "when": r.scheduled_time})
	for r in frappe.get_list("Gate Receiving Verification", filters={"gate_departure_time": ["is", "not set"], **({"farm": farm} if farm else {})},
			or_filters=[["supplier", "like", like], ["vehicle_no", "like", like]], fields=["name", "supplier", "vehicle_no"], limit_page_length=10):
		out.append({"doctype": "Gate Receiving Verification", "name": r.name, "label": f"{r.supplier} · delivery", "plate": r.vehicle_no})
	for r in frappe.get_list("Staff Vehicle Sticker", filters={"status": "Active"}, or_filters=[["plate_number", "like", like], ["employee", "like", like]],
			fields=["name", "plate_number", "employee"], limit_page_length=10):
		out.append({"doctype": "Staff Vehicle Sticker", "name": r.name, "label": "Staff · " + (frappe.db.get_value("Employee", r.employee, "employee_name") or r.employee or ""),
			"plate": r.plate_number})
	for r in frappe.get_list("CCTV Known Vehicle", filters={"status": "Active"}, or_filters=[["display_plate", "like", like], ["owner_label", "like", like]],
			fields=["name", "display_plate", "category", "owner_label"], limit_page_length=10):
		out.append({"doctype": "CCTV Known Vehicle", "name": r.name, "label": f"{r.category} · {r.owner_label or ''}", "plate": r.display_plate})
	return out


# ------------------------------------------------------------------ health

@frappe.whitelist()
def health_board(company=None, farm=None):
	require("enabled")
	if not set(frappe.get_roles()) & OPS_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	scope = _scope({}, company, farm)
	agents = frappe.get_all("CCTV Site Agent", filters=scope,
		fields=["name", "farm", "status", "last_heartbeat", "version", "queue_depth", "cpu_percent", "gpu_percent", "gateway_url"])
	servers = frappe.get_all("CCTV Server", filters=scope,
		fields=["name", "server_name", "farm", "brand", "model", "firmware", "status", "last_seen", "time_offset_seconds", "recording_mode", "observed_retention_days"])
	cameras = frappe.get_all("CCTV Camera", filters={**scope, "enabled": 1},
		fields=["name", "camera_name", "farm", "server", "zone", "role", "status", "last_frame_time", "codec", "resolution", "fps", "cap_anpr", "analytics_provider"],
		order_by="farm, camera_name")
	now = now_datetime()
	for a in agents:
		a.seconds_since = int(time_diff_in_seconds(now, a.last_heartbeat)) if a.last_heartbeat else None
	since = add_days(now, -1)
	backlog = frappe.db.count("CCTV Event", {**scope, "processed": 0, "received_at": [">=", since]})
	errors = frappe.db.count("CCTV Event", {**scope, "processing_error": ["is", "set"], "received_at": [">=", since]})
	return {
		"agents": agents, "servers": servers, "cameras": cameras,
		"summary": {
			"agents_online": sum(a.status == "Online" for a in agents), "agents": len(agents),
			"cameras_online": sum(c.status == "Online" for c in cameras), "cameras": len(cameras),
			"drifting": sum(abs(s.time_offset_seconds or 0) > 2 for s in servers),
			"unprocessed_24h": backlog, "failed_24h": errors,
		},
	}


# ------------------------------------------------------------------ site map

@frappe.whitelist()
def map_data(farm=None, company=None):
	"""Cameras (with status), zone outlines, the site boundary, vehicles at their
	last-seen camera and active person tracks - for the site map page."""
	require("enabled")
	if not set(frappe.get_roles()) & GATE_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	from upande_security.api.farm_geo import farm_ring
	from upande_security.api.zones import _read_attachment, _ring_from_geojson
	from upande_security.cctv.settings import is_on

	scope = _scope({}, company, farm)
	cams = frappe.get_list("CCTV Camera", filters={**scope, "enabled": 1},
		fields=["name", "camera_name", "farm", "zone", "role", "status", "latitude", "longitude", "gate"], limit_page_length=1000)
	placed = {c.name: c for c in cams if c.latitude and c.longitude}
	zones = []
	for z in frappe.get_all("Security Zone", filters={**scope, "active": 1}, fields=["name", "zone_name", "farm", "severity", "boundary_geojson"]):
		ring = _ring_from_geojson(_read_attachment(z.boundary_geojson))
		if ring:
			zones.append({"name": z.name, "label": z.zone_name, "severity": z.severity, "ring": ring})
	boundary = None
	if farm:
		try:
			boundary = farm_ring(farm)
		except Exception:
			boundary = None
	vehicles = []
	if is_on("anpr_enabled"):
		for v in frappe.get_list("CCTV Vehicle Visit", filters={**scope, "status": ["in", ["On Premises", "Overstayed"]]},
				fields=["name", "plate", "party_name", "party_type", "last_seen_camera", "last_seen_time", "status"], limit_page_length=500):
			c = placed.get(v.last_seen_camera)
			if c:
				vehicles.append({**v, "latitude": c.latitude, "longitude": c.longitude})
	tracks = []
	if is_on("presence_enabled") and set(frappe.get_roles()) & OPS_ROLES:
		for t in frappe.get_all("CCTV Track", filters={**scope, "status": "Active"},
				fields=["name", "label", "kind", "last_camera", "last_seen", "person_profile", "confidence"], limit=500):
			c = placed.get(t.last_camera)
			if c:
				tracks.append({**t, "latitude": c.latitude, "longitude": c.longitude})
	return {"cameras": cams, "unplaced": len(cams) - len(placed), "zones": zones, "boundary": boundary,
		"vehicles": vehicles, "tracks": tracks}
