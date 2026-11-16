# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Endpoints for Security Dashboard v2 (/security-dashboard-v2, frontend/).

The dashboard does gate operations in place - approve, check in, check out,
walk in - without opening the doctype. It adds no business rules of its own:
every action goes through the same endpoint the guard app uses
(security_api / visit_review), so workflow, feature flags, badges, SMS and
watch-list tracking behave identically wherever the action starts.

What lives here is only what an office screen needs on top:

* ``bootstrap`` - who is looking and what they may do (scope pickers, flags);
* ``visitor_board`` - one bucket of visits, filtered and paged on the server
  (v1 pulled every Appointment ever into the browser), with the counts for
  every bucket and the actions open on each row;
* thin wrappers that keep a visit's own farm/company when someone checks it
  in from an office (the guard endpoint stamps the CALLER's post, which is
  right at a gate and wrong from HQ).

The wrappers share their names with the guard endpoints on purpose:
gate_movement.check_on_shift (before_request) refuses off-shift gate actions
by the method's last name segment, so ``...dashboard_v2.check_in_visitor`` is
held to exactly the same off-shift rule as ``...security_api.check_in_visitor``.
"""

import frappe
from frappe import _

from upande_security.api import security_api, visit_review
from upande_security.api.feature_flags import is_feature_enabled
from upande_security.api.terms import _relabel, get_terms
from upande_security.api.gate_movement import get_farm_gates, may_check_in_out

DOCTYPE = "Appointment"

# Which list a visit is in, judged the way v1 judged it (apptStatus): a check-out
# time means it has left, then a check-in time means it is on site - whatever
# the workflow says (a walk-in is created "Open" but already checked in) - and
# only then does the workflow state decide.
REVIEW_STATES = ("Pending Host Review", "Pending Secretary Review", "Redirected to Another Host")
EXPECTED_STATES = (
	"Open", "Approved by Host", "Approved by Secretary", "Rescheduled by Host", "Rescheduled by Secretary",
)
ON_SITE_STATES = ("Visitor Checked In",)
LEFT_STATES = ("Visitor Checked Out",)
REJECTED_STATES = ("Rejected by Host", "Rejected by Secretary")
BUCKETS = ("review", "expected", "on_site", "left", "rejected")
# Only these workflow actions are offered as review buttons ("Confirm Check In/Out"
# are gate actions, done through check_in_visitor / check_out_visitor).
REVIEW_ACTIONS = (
	"Approve Visit", "Approve on Behalf of Host", "Forward to Host", "Reschedule",
	"Redirect to Another Host", "Reject Visit",
)
# States check_in_visitor accepts while the approval workflow is on.
CHECK_IN_STATES = ("Open", "Approved by Host", "Approved by Secretary")
VISITOR_TYPES = ("Visitor", "Customer", "Contractor")
GATE_FEATURES = (
	"feature_contractor_checkin", "feature_gate_dispatch", "feature_gate_receiving",
	"feature_vehicle_gate_tracking", "feature_staff_checkin", "feature_carried_items",
	"feature_supplier_badges", "feature_watchlist", "feature_checkpoint_scanning", "feature_vehicle_stickers",
)

FIELDS = [
	"name", "customer_name", "customer_phone_number", "customer_organization", "custom_id_number",
	"custom_visitor_type", "custom_meet_with", "custom_meet_with_name", "custom_visit_purpose",
	"custom_company", "custom_farmunit", "scheduled_time", "workflow_state",
	"custom_check_in_time", "custom_check_out_time", "custom_entry_gate", "custom_exit_gate",
	"custom_mode_of_transport", "custom_vehicles_number_plate", "custom_number_of_passengers",
	"custom_visitor_badge", "custom_contractor_ref",
]


def _approval_on():
	return frappe.db.get_single_value("Security Ops Settings", "feature_visitor_approval_workflow") != 0


@frappe.whitelist()
def bootstrap():
	"""Scope pickers and capabilities for the signed-in user."""
	roles = set(frappe.get_roles())
	companies = frappe.get_list("Company", pluck="name", order_by="name asc", limit_page_length=0)
	farms = frappe.get_list("Farm", fields=["name", "company"], order_by="name asc", limit_page_length=0)
	return {
		"companies": companies,
		"farms": farms,
		"can_check_in_out": may_check_in_out(),
		"can_review": bool(roles & {"Visit Approver", "System Manager"})
		or bool(frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")),
		"approval_workflow": _approval_on(),
		"visitor_types": list(VISITOR_TYPES),
		# Which gate operations are switched on here (Security Ops Settings).
		"features": {k: is_feature_enabled(k) for k in GATE_FEATURES},
		# The watchlist is covert: its page is not even listed for anyone else.
		"can_watchlist": bool({"Security Head", "System Manager"} & roles),
		"can_setup": bool({"Security Head", "System Manager"} & roles),
		# What this organisation calls a site and an area (Security Ops Settings > Words Used).
		"terms": get_terms(),
		"can_settings": frappe.has_permission("Security Ops Settings", "read"),
	}


@frappe.whitelist()
def farm_gates(farm=None):
	return get_farm_gates(farm) if farm else []


def _base_filters(company=None, farm=None, visitor_type=None):
	filters = {}
	if farm:
		filters["custom_farmunit"] = farm
	elif company:
		filters["custom_company"] = company
	if visitor_type:
		types = frappe.parse_json(visitor_type) if str(visitor_type).startswith("[") else [visitor_type]
		types = [t for t in types if t in VISITOR_TYPES]
		if types:
			filters["custom_visitor_type"] = ["in", types]
	return filters


def _search_names(search, base):
	"""Names of the visits matching a search, or None when there is none. A
	separate, permission-aware query, so the bucket rules below can use the
	one OR group get_list allows."""
	search = (search or "").strip()
	if not search:
		return None
	like = f"%{search}%"
	return frappe.get_list(DOCTYPE, filters=base, or_filters=[
		["customer_name", "like", like], ["customer_phone_number", "like", like],
		["customer_organization", "like", like], ["custom_id_number", "like", like],
		["custom_vehicles_number_plate", "like", like], ["name", "like", like],
	], pluck="name", limit_page_length=5000) or ["__none__"]


def _bucket_query(bucket, from_date, to_date):
	"""(filters, or_filters) for one list. Who is on site right now ignores
	the date range - someone who came in last night is still inside."""
	day = ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]]
	not_in = [["custom_check_in_time", "is", "not set"], ["custom_check_out_time", "is", "not set"]]
	if bucket == "left":
		return [["custom_check_out_time", *day]], None
	if bucket == "on_site":
		return (
			[["custom_check_out_time", "is", "not set"], ["workflow_state", "not in", LEFT_STATES]],
			[["custom_check_in_time", "is", "set"], ["workflow_state", "in", ON_SITE_STATES]],
		)
	if bucket == "expected":
		return (
			not_in + [["scheduled_time", *day]],
			[["workflow_state", "in", EXPECTED_STATES], ["workflow_state", "is", "not set"]],
		)
	states = REVIEW_STATES if bucket == "review" else REJECTED_STATES
	return not_in + [["workflow_state", "in", states], ["scheduled_time", *day]], None


@frappe.whitelist()
def visitor_board(bucket="expected", from_date=None, to_date=None, company=None, farm=None,
		visitor_type=None, search=None, start=0, page_length=50):
	"""One bucket of visits, newest first, with every bucket's count for the
	same scope and search. Permission-aware (frappe.get_list), so a host who
	may only see their own visits sees only those."""
	if bucket not in BUCKETS:
		frappe.throw(_("Unknown list: {0}").format(bucket))
	today = frappe.utils.nowdate()
	from_date = str(frappe.utils.getdate(from_date or today))
	to_date = str(frappe.utils.getdate(to_date or from_date))
	start = max(0, frappe.utils.cint(start))
	page_length = min(max(1, frappe.utils.cint(page_length) or 50), 200)

	base = _base_filters(company, farm, visitor_type)
	names = _search_names(search, base)
	if names is not None:
		base["name"] = ["in", names]
	base_list = [[k, *(v if isinstance(v, list) else ["=", v])] for k, v in base.items()]

	def query(key):
		filters, or_filters = _bucket_query(key, from_date, to_date)
		return {"filters": base_list + filters, "or_filters": or_filters}

	counts = {key: len(frappe.get_list(DOCTYPE, **query(key), pluck="name", limit_page_length=0)) for key in BUCKETS}

	order = {
		"on_site": "custom_check_in_time desc",
		"left": "custom_check_out_time desc",
		"expected": "scheduled_time asc",
	}.get(bucket, "scheduled_time desc")
	rows = frappe.get_list(DOCTYPE, **query(bucket), fields=FIELDS, order_by=order,
		limit_start=start, limit_page_length=page_length)

	gate_ok = may_check_in_out()
	approval = _approval_on()
	me = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
	for r in rows:
		state = r.workflow_state or "Open"
		r.review_actions = (
			[a for a in visit_review.review_actions(r.name, me) if a in REVIEW_ACTIONS]
			if bucket == "review" else []
		)
		r.can_check_in = gate_ok and bucket == "expected" and (state in CHECK_IN_STATES or not approval)
		r.can_check_out = gate_ok and bucket == "on_site"

	return {
		"bucket": bucket,
		"from_date": from_date,
		"to_date": to_date,
		"counts": counts,
		"total": counts[bucket],
		"start": start,
		"rows": rows,
	}


def _keep_scope(name, before):
	"""Put a visit's own company/farm back if the guard endpoint re-stamped
	them from the caller's post."""
	now = frappe.db.get_value(DOCTYPE, name, ["custom_company", "custom_farmunit"], as_dict=True) or {}
	restore = {
		k: before[k] for k in ("custom_company", "custom_farmunit")
		if before.get(k) and now.get(k) != before[k]
	}
	if restore:
		frappe.db.set_value(DOCTYPE, name, restore, update_modified=False)
		frappe.db.commit()


@frappe.whitelist(methods=["POST"])
def check_in_visitor(name=None, entry_gate=None, transport=None, plate=None, colour=None, passengers=None):
	"""security_api.check_in_visitor, keeping the visit's own farm/company."""
	before = frappe.db.get_value(DOCTYPE, name, ["custom_company", "custom_farmunit"], as_dict=True) or {}
	kwargs = {"name": name, "entry_gate": entry_gate, "passengers": passengers}
	# The guard endpoint writes transport/plate/colour only when the request
	# carried them (it reads form_dict), so this passes exactly what came in.
	result = security_api.check_in_visitor(**kwargs, transport=transport, plate=plate, colour=colour)
	if isinstance(result, dict) and result.get("error"):
		return result
	_keep_scope(name, before)
	return {"ok": True, "name": name}


@frappe.whitelist(methods=["POST"])
def check_out_visitor(name=None, exit_gate=None):
	"""security_api.check_out_visitor, refusing a visit that has already left
	and recording the exit gate when one was picked."""
	visit = frappe.db.get_value(DOCTYPE, name, ["workflow_state", "custom_check_out_time"], as_dict=True)
	if visit is None:
		return {"error": _("Visit {0} not found.").format(name)}
	if visit.workflow_state in LEFT_STATES or visit.custom_check_out_time:
		return {"error": _("{0} has already checked out.").format(name)}
	if frappe.db.get_value(DOCTYPE, name, "custom_visitor_type") == "Contractor":
		# The contractor checkout also returns every crew badge to the pool.
		frappe.form_dict.appointment_name = name
		result = security_api.contractor_gate_checkout()
		# The guard endpoint stamps the time but leaves the workflow at
		# "Visitor Checked In"; visitor checkout moves it, so this does too.
		if isinstance(result, dict) and not result.get("error"):
			frappe.db.set_value(DOCTYPE, name, "workflow_state", "Visitor Checked Out", update_modified=False)
			frappe.db.commit()
	else:
		result = security_api.check_out_visitor(name=name)
	if isinstance(result, dict) and result.get("error"):
		return result
	exit_gate = (exit_gate or "").strip()
	if exit_gate:
		entry = frappe.db.get_value(DOCTYPE, name, "custom_entry_gate")
		frappe.db.set_value(DOCTYPE, name, {
			"custom_exit_gate": exit_gate,
			"custom_gate_mismatch": 1 if entry and entry != exit_gate else 0,
		}, update_modified=False)
		frappe.db.commit()
	return {"ok": True, "name": name}


@frappe.whitelist(methods=["POST"])
def create_walk_in(customer_name=None, phone=None, host=None, id_number=None, email=None, purpose=None,
		organization=None, transport=None, plate=None, colour=None, passengers=None, company=None, farm=None):
	"""security_api.create_walk_in; a farm or company picked on the dashboard
	replaces the one stamped from the caller's post."""
	result = security_api.create_walk_in(
		customer_name=customer_name, id_number=id_number, phone=phone, email=email, host=host,
		purpose=purpose, organization=organization, transport=transport, plate=plate, colour=colour,
		passengers=passengers,
	)
	if not isinstance(result, dict) or result.get("error") or not result.get("name"):
		return result if isinstance(result, dict) else {"error": _("The walk-in was not created.")}
	scope = {}
	if farm:
		scope = {"custom_farmunit": farm, "custom_company": frappe.db.get_value("Farm", farm, "company") or company}
	elif company:
		scope = {"custom_company": company}
	scope = {k: v for k, v in scope.items() if v}
	if scope and not result.get("duplicate_suppressed"):
		frappe.db.set_value(DOCTYPE, result["name"], scope, update_modified=False)
		frappe.db.commit()
	return {"ok": True, **result}


# --- gate logs (dispatch, receiving, vehicles) ----------------------------------------

GATE_LOGS = {
	"dispatch": {
		"doctype": "Gate Dispatch Verification",
		"date": "gate_exit_time",
		"farm": "farm",
		"fields": ["name", "reference_doctype", "reference_name", "farm", "vehicle_no", "driver_name",
			"items_summary", "gate_verification_status", "gate_verified_by", "gate", "gate_exit_time", "remarks"],
		"search": ["reference_name", "vehicle_no", "driver_name"],
	},
	"receiving": {
		"doctype": "Gate Receiving Verification",
		"date": "gate_arrival_time",
		"farm": "farm",
		"fields": ["name", "purchase_order", "supplier", "farm", "vehicle_no", "driver_name", "items_summary",
			"gate_verification_status", "gate_verified_by", "gate", "gate_arrival_time", "gate_departure_time",
			"purchase_receipt", "supplier_delivery_note", "no_receipt_reason", "remarks"],
		"search": ["purchase_order", "supplier", "vehicle_no", "driver_name"],
	},
	"vehicles": {
		"doctype": "Gate Vehicle Verification",
		"date": "creation",
		"farm": None,  # a leg has two farms; filtered on either below
		"fields": ["name", "vehicle_no", "asset", "task_description", "from_farm", "to_farm",
			"gate_exit_time", "exit_gate", "gate_exit_status", "gate_exit_verified_by",
			"gate_entry_time", "entry_gate", "gate_entry_status", "gate_entry_verified_by", "remarks"],
		"search": ["vehicle_no", "asset", "task_description"],
	},
}


@frappe.whitelist()
def gate_log(kind, from_date=None, to_date=None, company=None, farm=None, status=None, search=None,
		start=0, page_length=50):
	"""What was checked at the gate, newest first, for one operation - paged and
	filtered on the server, permission-aware."""
	spec = GATE_LOGS.get(kind)
	if not spec:
		frappe.throw(_("Unknown gate log: {0}").format(kind))
	today = frappe.utils.nowdate()
	from_date = str(frappe.utils.getdate(from_date or today))
	to_date = str(frappe.utils.getdate(to_date or from_date))
	start = max(0, frappe.utils.cint(start))
	page_length = min(max(1, frappe.utils.cint(page_length) or 50), 200)
	dt = spec["doctype"]

	filters = [[spec["date"], "between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]]]
	if farm:
		farms = [farm]
	elif company:
		farms = frappe.get_all("Farm", {"company": company}, pluck="name") or ["__none__"]
	else:
		farms = None
	# Dispatch and receiving have one verdict per record; a vehicle leg has an
	# exit and an entry verdict, both shown on the row, so it is not filtered.
	if status and kind != "vehicles":
		filters.append(["gate_verification_status", "=", status])
	or_filters = None
	if farms is not None:
		if spec["farm"]:
			filters.append([spec["farm"], "in", farms])
		else:
			or_filters = [["from_farm", "in", farms], ["to_farm", "in", farms]]
	term = (search or "").strip()
	if term:
		names = frappe.get_list(dt, filters=filters, or_filters=[[f, "like", f"%{term}%"] for f in spec["search"]],
			pluck="name", limit_page_length=5000)
		filters.append(["name", "in", names or ["__none__"]])

	total = len(frappe.get_list(dt, filters=filters, or_filters=or_filters, pluck="name", limit_page_length=0))
	rows = frappe.get_list(dt, filters=filters, or_filters=or_filters, fields=spec["fields"],
		order_by=f"{spec['date']} desc", limit_start=start, limit_page_length=page_length)
	users = {u for r in rows for u in (r.get("gate_verified_by"), r.get("gate_exit_verified_by"), r.get("gate_entry_verified_by")) if u}
	names = dict(frappe.get_all("User", {"name": ["in", list(users) or ["-"]]}, ["name", "full_name"], as_list=True))
	for r in rows:
		for f in ("gate_verified_by", "gate_exit_verified_by", "gate_entry_verified_by"):
			if r.get(f):
				r[f + "_name"] = names.get(r[f]) or r[f]
	return {"kind": kind, "from_date": from_date, "to_date": to_date, "total": total, "start": start, "rows": rows}


# --- incidents ---------------------------------------------------------------------

INCIDENT = "Incident Report"
INCIDENT_STATUSES = ("Open", "In Progress", "Resolved", "Closed")
SEVERITIES = ("Low", "Medium", "High", "Critical")
DONE = ("Resolved", "Closed")
INCIDENT_FIELDS = [
	"name", "incident_datetime", "farm", "location", "nature_of_incident", "severity", "status",
	"reporter_name", "is_anonymous", "assigned_to", "description", "resolution_datetime",
	"attachment_1", "attachment_2", "attachment_3", "attachment_4",
]


def _manages_incidents():
	"""update_incident's own rule, read the same way it reads it (explicit Has
	Role rows, not frappe.get_roles), so the page never offers an edit that
	the endpoint then refuses."""
	roles = set(frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role"))
	return bool({"Security Head", "System Manager"} & roles)


@frappe.whitelist()
def incident_options():
	"""Pickers for the Incidents page: the categories (less the types the
	dashboard leaves out), statuses, severities, and whether the user may
	update incidents."""
	from upande_security.api.security_dashboard import hidden_incident_types, incident_categories

	hidden = set(hidden_incident_types())
	return {
		"categories": [c for c in incident_categories() if c.get("name") not in hidden],
		"statuses": list(INCIDENT_STATUSES),
		"severities": list(SEVERITIES),
		"can_manage": _manages_incidents(),
	}


@frappe.whitelist()
def incident_board(from_date=None, to_date=None, company=None, farm=None, status=None, severity=None,
		category=None, search=None, start=0, page_length=50):
	"""Incidents for a period: KPIs and breakdowns over everything that
	matches, plus one page of rows. Permission-aware (frappe.get_list, so a
	Security Head sees their own farms), and leaving out the types Security
	Ops Settings hides from reporting, as v1 and the emailed report do."""
	from upande_security.api.security_dashboard import _farms_of_company, _hide_incident_types

	today = frappe.utils.nowdate()
	from_date = str(frappe.utils.getdate(from_date or frappe.utils.add_days(today, -29)))
	to_date = str(frappe.utils.getdate(to_date or today))
	start = max(0, frappe.utils.cint(start))
	page_length = min(max(1, frappe.utils.cint(page_length) or 50), 200)

	filters = [["incident_datetime", "between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]]]
	_hide_incident_types(filters)
	if farm:
		filters.append(["farm", "=", farm])
	elif company:
		filters.append(["farm", "in", _farms_of_company(company) or ["__none__"]])
	if severity in SEVERITIES:
		filters.append(["severity", "=", severity])
	if category:
		filters.append(["nature_of_incident", "=", category])
	term = (search or "").strip()
	if term:
		like = f"%{term}%"
		names = frappe.get_list(INCIDENT, filters=filters, or_filters=[
			["name", "like", like], ["location", "like", like], ["description", "like", like],
			["reporter_name", "like", like],
		], pluck="name", limit_page_length=5000)
		filters.append(["name", "in", names or ["__none__"]])

	# Breakdowns ignore the status filter, so the status tabs keep their counts.
	light = frappe.get_list(INCIDENT, filters=filters, limit_page_length=0, fields=[
		"name", "status", "severity", "nature_of_incident", "location", "incident_datetime", "resolution_datetime",
	])
	by_status = {s: 0 for s in INCIDENT_STATUSES}
	by_category, by_location, by_day = {}, {}, {}
	critical_open = high_open = 0
	minutes = []
	for r in light:
		st = r.status or "Open"
		by_status[st] = by_status.get(st, 0) + 1
		by_category[r.nature_of_incident or "Other"] = by_category.get(r.nature_of_incident or "Other", 0) + 1
		if r.location:
			by_location[r.location] = by_location.get(r.location, 0) + 1
		if r.incident_datetime:
			day = str(frappe.utils.getdate(r.incident_datetime))
			by_day[day] = by_day.get(day, 0) + 1
		if st not in DONE:
			critical_open += r.severity == "Critical"
			high_open += r.severity == "High"
		if r.incident_datetime and r.resolution_datetime:
			m = (frappe.utils.get_datetime(r.resolution_datetime) - frappe.utils.get_datetime(r.incident_datetime)).total_seconds() / 60
			if m >= 0:
				minutes.append(m)

	# Every day of the range, so quiet days show as zero rather than vanish.
	days, d = [], frappe.utils.getdate(from_date)
	while d <= frappe.utils.getdate(to_date) and len(days) < 400:
		days.append({"day": str(d), "count": by_day.get(str(d), 0)})
		d = frappe.utils.add_days(d, 1)

	row_filters = list(filters)
	if status in INCIDENT_STATUSES:
		row_filters.append(["status", "=", status])
	elif status == "active":
		row_filters.append(["status", "not in", DONE])
	total = len(frappe.get_list(INCIDENT, filters=row_filters, pluck="name", limit_page_length=0))
	rows = frappe.get_list(INCIDENT, filters=row_filters, fields=INCIDENT_FIELDS,
		order_by="incident_datetime desc", limit_start=start, limit_page_length=page_length)
	for r in rows:
		r.description = (r.description or "")[:240]
		r.attachments = [r.pop(f) for f in ("attachment_1", "attachment_2", "attachment_3", "attachment_4") if r.get(f)]
		if r.is_anonymous:
			r.reporter_name = "Anonymous"

	return {
		"from_date": from_date,
		"to_date": to_date,
		"kpis": {
			"total": len(light),
			"active": sum(n for s, n in by_status.items() if s not in DONE),
			"critical_open": critical_open,
			"high_open": high_open,
			"in_progress": by_status.get("In Progress", 0),
			"resolved": by_status.get("Resolved", 0) + by_status.get("Closed", 0),
			"avg_resolution_minutes": round(sum(minutes) / len(minutes)) if minutes else None,
		},
		"by_status": by_status,
		"by_category": sorted(({"category": k, "count": v} for k, v in by_category.items()), key=lambda x: -x["count"]),
		"by_location": sorted(({"location": k, "count": v} for k, v in by_location.items()), key=lambda x: -x["count"])[:8],
		"over_time": days,
		"total": total,
		"start": start,
		"rows": rows,
	}


@frappe.whitelist(methods=["POST"])
def create_incident(farm=None, **kwargs):
	"""security_api.create_incident; a farm picked on the dashboard replaces
	the one worked out from the reporter's own post (an office reporter is
	not standing at the farm the incident happened on)."""
	kwargs.pop("cmd", None)
	allowed = {
		"incident_datetime", "location", "nature_of_incident", "severity", "description", "is_fatal",
		"activity_at_time_of_injury", "body_part_affected", "nature_of_injury", "injury_current_location",
		"notify", "anonymous", "attachment_1", "attachment_2", "attachment_3", "attachment_4",
	}
	result = security_api.create_incident(**{k: v for k, v in kwargs.items() if k in allowed})
	if not isinstance(result, dict) or result.get("error") or not result.get("name"):
		return result if isinstance(result, dict) else {"error": _("The incident was not saved.")}
	if farm and frappe.db.exists("Farm", farm):
		frappe.db.set_value(INCIDENT, result["name"], "farm", farm, update_modified=False)
		frappe.db.commit()
	return {"ok": True, **result}


@frappe.whitelist(methods=["POST"])
def update_incident(name=None, status=None, resolution=None, corrective_actions=None, assigned_to=None):
	"""security_api.update_incident (Security Head / System Manager), plus:
	the time an incident is first resolved or closed is recorded, so the
	average resolution time has something to measure; and the assignee can
	be set."""
	before = frappe.db.get_value(INCIDENT, name, ["status", "resolution_datetime"], as_dict=True) if name else None
	result = security_api.update_incident(name=name, status=status, resolution=resolution,
		corrective_actions=corrective_actions)
	if not isinstance(result, dict) or result.get("error"):
		return result
	updates = {}
	if status in DONE and before and not before.resolution_datetime:
		updates["resolution_datetime"] = frappe.utils.now_datetime()
	if assigned_to is not None and "assigned_to" in frappe.form_dict:
		if assigned_to and not frappe.db.exists("User", assigned_to):
			return {"error": _("User {0} not found.").format(assigned_to)}
		updates["assigned_to"] = assigned_to or None
	if updates:
		frappe.db.set_value(INCIDENT, name, updates)
		frappe.db.commit()
	return {"ok": True, **result}


@frappe.whitelist(methods=["POST"])
def attach_incident_photos(name, file_urls):
	"""Put photos uploaded for an incident (upload_file, private, attached to
	it) into its free Attachment 1-4 slots. Only files really attached to
	this incident are accepted, and only by its reporter or someone who may
	edit incidents. (Anonymous reports take no photos from the dashboard: a
	file always carries its uploader, which would name the reporter.)"""
	urls = frappe.parse_json(file_urls) if isinstance(file_urls, str) else (file_urls or [])
	doc = frappe.db.get_value(INCIDENT, name, ["name", "reported_by", "is_anonymous",
		"attachment_1", "attachment_2", "attachment_3", "attachment_4"], as_dict=True)
	if not doc:
		return {"error": _("Incident {0} not found.").format(name)}
	if doc.is_anonymous:
		return {"error": _("Photos are not added to anonymous reports from the dashboard.")}
	if not (doc.reported_by == frappe.session.user or _manages_incidents()
			or frappe.has_permission(INCIDENT, "write", name)):
		return {"error": _("You cannot add photos to this incident.")}
	attached = set(frappe.get_all("File", {"attached_to_doctype": INCIDENT, "attached_to_name": name}, pluck="file_url"))
	slots = [f"attachment_{i}" for i in range(1, 5) if not doc.get(f"attachment_{i}")]
	updates = {}
	for url in urls:
		if url in attached and slots:
			updates[slots.pop(0)] = url
	added = len(updates)  # set_value adds modified/modified_by to the dict it is given
	if updates:
		frappe.db.set_value(INCIDENT, name, updates)
		frappe.db.commit()
	return {"ok": True, "attached": added, "skipped": len(urls) - added}


@frappe.whitelist()
def incident_detail(name):
	"""security_api.get_incident_report - its access rules decide - plus what
	the dashboard's detail view also shows: farm, assignee, resolution,
	corrective actions and the photos."""
	result = security_api.get_incident_report(name=name)
	if not isinstance(result, dict) or result.get("error"):
		return result
	extra = frappe.db.get_value(INCIDENT, name, [
		"farm", "assigned_to", "resolution", "corrective_actions", "resolution_datetime", "remarks",
		"attachment_1", "attachment_2", "attachment_3", "attachment_4",
	], as_dict=True) or {}
	result.update({k: extra.get(k) for k in ("farm", "assigned_to", "resolution", "corrective_actions", "remarks")})
	result["resolution_datetime"] = str(extra.get("resolution_datetime") or "") or None
	result["attachments"] = [extra[f] for f in ("attachment_1", "attachment_2", "attachment_3", "attachment_4") if extra.get(f)]
	if result.get("is_anonymous"):
		result["reporter_name"] = "Anonymous"
	result["can_manage"] = _manages_incidents()
	return result


# --- patrols ------------------------------------------------------------------------

GPS = "Patrol GPS Log"
PATROL_REPORT = "Patrol Report"
LIVE_MINUTES = 15  # v1's rule: a patrol whose last fix today is this recent is live


def _patrol_scope(filters, company=None, farm=None):
	from upande_security.api.security_dashboard import _farms_of_company

	if farm:
		filters.append(["farm", "=", farm])
	elif company:
		filters.append(["farm", "in", _farms_of_company(company) or ["__none__"]])
	return filters


def _guard_names(rows):
	"""{(internal, external, owner): name} - the map's identity rule
	(security_dashboard._patrol_guard_identity), looked up in three queries."""
	emp = {r.internal_guard for r in rows if r.internal_guard}
	ext = {r.external_guard for r in rows if r.external_guard}
	own = {r.owner for r in rows if r.owner}
	emp = dict(frappe.get_all("Employee", {"name": ["in", list(emp) or ["-"]]}, ["name", "employee_name"], as_list=True))
	ext = dict(frappe.get_all("Security Guard", {"name": ["in", list(ext) or ["-"]]}, ["name", "full_name"], as_list=True))
	own = dict(frappe.get_all("User", {"name": ["in", list(own) or ["-"]]}, ["name", "full_name"], as_list=True))

	def name(r):
		if r.internal_guard:
			return emp.get(r.internal_guard) or r.internal_guard
		if r.external_guard:
			return ext.get(r.external_guard) or r.external_guard
		if r.owner and r.owner not in ("Administrator", "Guest"):
			return (own.get(r.owner) or r.owner) + " (no guard link)"
		return _("Unassigned")

	return name


@frappe.whitelist()
def patrol_board(from_date=None, to_date=None, company=None, farm=None, status=None, search=None,
		start=0, page_length=50):
	"""Patrols in a period - one row per guard per patrol, with its points,
	start, last fix and whether a report was filed - summed in the database
	(v1 pulled every GPS point of the range into Python; a live month is
	~1.5M). Permission-aware. On Duty points (standing at a post) are not
	patrolling and are left out, as everywhere else."""
	if not frappe.has_permission(GPS, "read"):
		frappe.throw(_("You do not have permission to view patrols."), frappe.PermissionError)
	today = frappe.utils.nowdate()
	from_date = str(frappe.utils.getdate(from_date or today))
	to_date = str(frappe.utils.getdate(to_date or from_date))
	if frappe.utils.date_diff(to_date, from_date) > 92:
		frappe.throw(_("Pick a period of three months or less."))
	start = max(0, frappe.utils.cint(start))
	page_length = min(max(1, frappe.utils.cint(page_length) or 50), 200)

	filters = [
		["captured_at", "between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]],
		["tracking_mode", "!=", "On Duty"],
	]
	_patrol_scope(filters, company, farm)
	groups = frappe.get_list(GPS, filters=filters, limit_page_length=0,
		group_by="patrol, internal_guard, external_guard, owner",
		fields=["patrol", "internal_guard", "external_guard", "owner",
			{"MAX": "farm", "as": "farm"}, {"COUNT": "name", "as": "points"},
			{"MIN": "captured_at", "as": "started"}, {"MAX": "captured_at", "as": "last_fix"}])

	name_of = _guard_names(groups)
	patrol_ids = [g.patrol for g in groups if g.patrol]
	reports = {}
	for r in frappe.get_all(PATROL_REPORT, {"patrol": ["in", patrol_ids or ["-"]]},
			["name", "patrol", "status", "report_type"], order_by="filed_at desc"):
		reports.setdefault(r.patrol, r)

	now = frappe.utils.now_datetime()
	rows = []
	for g in groups:
		last = frappe.utils.get_datetime(g.last_fix) if g.last_fix else None
		state = "Ended"
		if last and last.date() == now.date():
			state = "Active" if (now - last).total_seconds() <= LIVE_MINUTES * 60 else "Stale"
		started = frappe.utils.get_datetime(g.started) if g.started else None
		rep = reports.get(g.patrol)
		rows.append({
			"patrol": g.patrol or "",
			"guard": name_of(g),
			"farm": g.farm,
			"points": g.points,
			"started": str(started) if started else None,
			"last_fix": str(last) if last else None,
			"minutes": round((last - started).total_seconds() / 60) if last and started else 0,
			"state": state,
			"report": rep.name if rep else None,
			"report_status": rep.status if rep else None,
			"report_type": rep.report_type if rep else None,
		})

	counts = {"Active": 0, "Stale": 0, "Ended": 0}
	for r in rows:
		counts[r["state"]] += 1
	kpis = {
		"patrols": len(rows),
		"active": counts["Active"],
		"stale": counts["Stale"],
		"guards": len({r["guard"] for r in rows}),
		"points": sum(r["points"] for r in rows),
		"hours": round(sum(r["minutes"] for r in rows) / 60, 1),
		"with_report": sum(1 for r in rows if r["report"]),
		"without_report": sum(1 for r in rows if not r["report"] and r["state"] == "Ended"),
	}

	if status == "no_report":
		rows = [r for r in rows if not r["report"] and r["state"] == "Ended"]
	elif status in counts:
		rows = [r for r in rows if r["state"] == status]
	term = (search or "").strip().lower()
	if term:
		rows = [r for r in rows if term in (r["guard"] or "").lower() or term in r["patrol"].lower()
			or term in (r["farm"] or "").lower()]
	# Live first, then the most recent (two stable sorts).
	rows.sort(key=lambda r: r["last_fix"] or "", reverse=True)
	rows.sort(key=lambda r: {"Active": 0, "Stale": 1}.get(r["state"], 2))
	return {"from_date": from_date, "to_date": to_date, "kpis": kpis, "counts": counts,
		"total": len(rows), "start": start, "rows": rows[start:start + page_length]}


PATROL_REPORT_FIELDS = [
	"name", "patrol", "report_type", "farm", "personel", "internal_guard", "external_guard", "owner",
	"started_at", "ended_at", "points_logged", "filed_at", "observations", "severity", "nature_of_incident",
	"incident_report", "status", "reviewed_by", "reviewed_on", "supervisor_remarks",
	"attachment_1", "attachment_2", "attachment_3", "attachment_4",
]


def _reviews_patrols():
	return 1 in frappe.get_meta(PATROL_REPORT).get_permlevel_access("write")


@frappe.whitelist()
def patrol_reports(from_date=None, to_date=None, company=None, farm=None, status=None, report_type=None,
		search=None, start=0, page_length=50):
	"""Filed Patrol Reports, newest first, with a count per review status.
	Permission-aware (a Security Head sees their farms)."""
	today = frappe.utils.nowdate()
	from_date = str(frappe.utils.getdate(from_date or frappe.utils.add_days(today, -6)))
	to_date = str(frappe.utils.getdate(to_date or today))
	start = max(0, frappe.utils.cint(start))
	page_length = min(max(1, frappe.utils.cint(page_length) or 50), 200)

	filters = [["filed_at", "between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]]]
	_patrol_scope(filters, company, farm)
	if report_type in ("Routine", "Incident"):
		filters.append(["report_type", "=", report_type])
	term = (search or "").strip()
	if term:
		like = f"%{term}%"
		names = frappe.get_list(PATROL_REPORT, filters=filters, or_filters=[
			["name", "like", like], ["patrol", "like", like], ["observations", "like", like],
		], pluck="name", limit_page_length=5000)
		filters.append(["name", "in", names or ["__none__"]])

	counts = {s: 0 for s in ("Submitted", "Reviewed", "Flagged")}
	for r in frappe.get_list(PATROL_REPORT, filters=filters, group_by="status",
			fields=["status", {"COUNT": "name", "as": "n"}], limit_page_length=0):
		counts[r.status or "Submitted"] = counts.get(r.status or "Submitted", 0) + r.n

	row_filters = filters + ([["status", "=", status]] if status in counts else [])
	total = len(frappe.get_list(PATROL_REPORT, filters=row_filters, pluck="name", limit_page_length=0))
	rows = frappe.get_list(PATROL_REPORT, filters=row_filters, fields=PATROL_REPORT_FIELDS,
		order_by="filed_at desc", limit_start=start, limit_page_length=page_length)
	name_of = _guard_names(rows)
	reviewers = dict(frappe.get_all("User", {"name": ["in", [r.reviewed_by for r in rows if r.reviewed_by] or ["-"]]},
		["name", "full_name"], as_list=True))
	for r in rows:
		r.guard = name_of(r)
		r.reviewed_by_name = reviewers.get(r.reviewed_by) or r.reviewed_by
		r.attachments = [r.pop(f) for f in ("attachment_1", "attachment_2", "attachment_3", "attachment_4") if r.get(f)]
		for f in ("internal_guard", "external_guard", "owner"):
			r.pop(f, None)
	return {"from_date": from_date, "to_date": to_date, "counts": counts, "total": total, "start": start,
		"rows": rows, "can_review": _reviews_patrols()}


@frappe.whitelist(methods=["POST"])
def review_patrol_report(name, status, supervisor_remarks=None):
	"""Mark a patrol report Reviewed or Flagged (or back to Submitted). The
	review fields are permlevel 1 - Security Head and System Manager; the
	doctype stamps who reviewed it and when, and a Flagged report raises its
	Incident Report itself."""
	if status not in ("Submitted", "Reviewed", "Flagged"):
		return {"error": _("Status must be Submitted, Reviewed or Flagged.")}
	doc = frappe.get_doc(PATROL_REPORT, name)
	doc.check_permission("write")
	if 1 not in doc.get_permlevel_access("write"):
		return {"error": _("Only a Security Head or System Manager can review patrol reports.")}
	remarks = (supervisor_remarks or "").strip()
	if status == "Flagged" and not remarks and not doc.supervisor_remarks:
		return {"error": _("Say why the report is flagged.")}
	doc.status = status
	if supervisor_remarks is not None:
		doc.supervisor_remarks = remarks
	doc.save()
	frappe.db.commit()
	return {"ok": True, "name": doc.name, "status": doc.status, "reviewed_on": str(doc.reviewed_on or ""),
		"incident_report": doc.incident_report}


# --- scheduling ---------------------------------------------------------------------
# Shifts, the monthly schedule and rotation plans. Only External Guards are
# planned here: Internal Guards' shifts are mirrored from HR and the doctype
# refuses to create or re-time them (validate_internal_guard_shift_is_hr_owned).

SGSA = "Security Guard Shift Assignment"
PLAN = "Security Guard Rotation Plan"
SHIFT_TYPES = ("Day", "Night", "First", "Second", "Third")


def _planner():
	from upande_security.api.relievers import require_planner

	require_planner()


def _is_planner():
	try:
		_planner()
		return True
	except frappe.PermissionError:
		return False


@frappe.whitelist()
def scheduling_options():
	"""Shift types with their standard times, and whether the user plans."""
	from upande_security.api.shift_times import all_farm_times, standard_times

	times = {}
	for t in SHIFT_TYPES:
		start, end = standard_times(t)
		times[t] = {"start_time": _hhmm(start), "end_time": _hhmm(end)}
	# Farms with their own Standard Shift Times rows: only those shifts.
	farm_times = {
		farm: {
			t: {"start_time": _hhmm(se[0]), "end_time": _hhmm(se[1])}
			for t, se in shifts.items() if t in SHIFT_TYPES
		}
		for farm, shifts in all_farm_times().items()
	}
	return {"shift_types": list(SHIFT_TYPES), "times": times, "farm_times": farm_times, "can_plan": _is_planner()}


@frappe.whitelist(methods=["POST"])
def create_shift(external_guard, farm, shift_type, date, start_time=None, end_time=None, block=None, remarks=None):
	"""Book one shift for an External Guard. Times default to the shift type's
	standard times; a shift ending at or before its start runs past midnight
	and ends the next day. The doctype refuses overlaps and multi-day ranges."""
	from upande_security.api.shift_times import standard_times

	_planner()
	if shift_type not in SHIFT_TYPES:
		return {"error": _("Pick a shift type.")}
	if not frappe.db.exists("Security Guard", external_guard):
		return {"error": _("Security Guard {0} not found.").format(external_guard)}
	std_start, std_end = standard_times(shift_type, farm)
	start = frappe.utils.get_time(start_time or std_start)
	end = frappe.utils.get_time(end_time or std_end)
	day = frappe.utils.getdate(date)
	doc = frappe.new_doc(SGSA)
	doc.update({
		"security_guard": "External Guard",
		"external_guard": external_guard,
		"farm": farm,
		"block": block or None,
		"shift_type": shift_type,
		"start_date": day,
		# As "HH:MM:SS" text: the doctype's own date+time helper parses strings only.
		"start_time": start.strftime("%H:%M:%S"),
		"end_date": frappe.utils.add_days(day, 1) if end <= start else day,
		"end_time": end.strftime("%H:%M:%S"),
		"status": "Scheduled",
		"assigned_by": frappe.session.user,
		"remarks": (remarks or "").strip() or None,
	})
	doc.insert()
	frappe.db.commit()
	return {"ok": True, "name": doc.name, "status": doc.status}


@frappe.whitelist(methods=["POST"])
def cancel_shift(name, reason=None):
	"""Cancel a shift (it stays on record). HR-mirrored Internal Guard shifts
	are changed in HR, not here."""
	_planner()
	doc = frappe.get_doc(SGSA, name)
	if doc.security_guard == "Internal Guard":
		return {"error": _("This shift comes from HR. Change it in HR's Shift Assignment.")}
	if doc.status == "Cancelled":
		return {"error": _("{0} is already cancelled.").format(name)}
	doc.status = "Cancelled"
	reason = (reason or "").strip()
	if reason:
		doc.remarks = ((doc.remarks or "") + "\n" if doc.remarks else "") + _("Cancelled: {0}").format(reason)
	doc.save()
	frappe.db.commit()
	return {"ok": True, "name": doc.name}


def _hhmm(v):
	"""A Time field as "HH:MM" (the database hands back "6:00:00")."""
	return frappe.utils.get_time(v).strftime("%H:%M") if v else ""


PLAN_FIELDS = ["name", "external_guard", "status", "mode", "shift_type", "start_time", "end_time", "start_date",
	"end_date", "rotation_interval_days", "rotate_shifts", "shift_change_every_days", "remarks", "modified"]


@frappe.whitelist()
def rotation_plans(status=None, search=None, start=0, page_length=50):
	"""Rotation plans, newest first, with their guard, farms and day counts."""
	filters = []
	if status in ("Draft", "Applied", "Cancelled"):
		filters.append(["status", "=", status])
	term = (search or "").strip()
	if term:
		guards = frappe.get_all("Security Guard", {"full_name": ["like", f"%{term}%"]}, pluck="name")
		filters.append(["external_guard", "in", guards or ["__none__"]])
	start = max(0, frappe.utils.cint(start))
	total = len(frappe.get_list(PLAN, filters=filters, pluck="name", limit_page_length=0))
	rows = frappe.get_list(PLAN, filters=filters, fields=PLAN_FIELDS, order_by="modified desc",
		limit_start=start, limit_page_length=min(max(1, frappe.utils.cint(page_length) or 50), 200))
	names = dict(frappe.get_all("Security Guard", {"name": ["in", [r.external_guard for r in rows] or ["-"]]},
		["name", "full_name"], as_list=True))
	farms = {}
	for f in frappe.get_all("Security Guard Rotation Farm", {"parent": ["in", [r.name for r in rows] or ["-"]],
			"parenttype": PLAN}, ["parent", "farm"], order_by="idx asc"):
		farms.setdefault(f.parent, []).append(f.farm)
	for r in rows:
		r.guard_name = names.get(r.external_guard) or r.external_guard
		r.farms = farms.get(r.name, [])
		r.start_time = _hhmm(r.start_time)
		r.end_time = _hhmm(r.end_time)
	return {"total": total, "start": start, "rows": rows, "can_plan": _is_planner()}


@frappe.whitelist()
def rotation_plan(name):
	"""One plan with its farms, shift sequence and day-by-day preview."""
	doc = frappe.get_doc(PLAN, name)
	doc.check_permission("read")
	out = {f: doc.get(f) for f in PLAN_FIELDS}
	out["guard_name"] = frappe.db.get_value("Security Guard", doc.external_guard, "full_name") or doc.external_guard
	out["farms"] = [{"farm": r.farm, "block": r.block} for r in doc.rotation_farms]
	out["shift_sequence"] = [r.shift_type for r in doc.shift_sequence or []]
	out["preview"] = [{
		"name": r.name, "date": str(r.rotation_date), "farm": r.farm, "block": r.block, "is_off_day": r.is_off_day,
		"status": r.status, "shift_type": r.shift_type, "start_time": _hhmm(r.start_time),
		"end_time": _hhmm(r.end_time), "cover_guard": r.cover_guard, "cover_guard_name": r.cover_guard_name,
	} for r in doc.preview_rows]
	for k in ("start_time", "end_time"):
		out[k] = _hhmm(out[k])
	for k in ("start_date", "end_date", "modified"):
		out[k] = str(out[k] or "")
	out["can_plan"] = _is_planner()
	return out


@frappe.whitelist(methods=["POST"])
def save_rotation_plan(data):
	"""Create a Draft plan, or change one still in Draft. The doctype fills
	the times from the shift type and checks the farms, dates and interval."""
	_planner()
	data = frappe.parse_json(data) if isinstance(data, str) else frappe._dict(data or {})
	if data.get("name"):
		doc = frappe.get_doc(PLAN, data["name"])
		if doc.status != "Draft":
			return {"error": _("Only a Draft plan can be changed. Start a new plan for the rest of the period.")}
	else:
		doc = frappe.new_doc(PLAN)
		doc.status = "Draft"
	for f in ("external_guard", "mode", "shift_type", "start_date", "end_date", "rotation_interval_days",
			"rotate_shifts", "shift_change_every_days", "remarks", "start_time", "end_time"):
		if f in data:
			doc.set(f, data.get(f) or None)
	doc.mode = doc.mode or "Automatic"
	if "farms" in data:
		doc.set("rotation_farms", [{"farm": f.get("farm"), "block": f.get("block") or None}
			for f in (data.get("farms") or []) if f.get("farm")])
	if "shift_sequence" in data:
		doc.set("shift_sequence", [{"shift_type": t} for t in (data.get("shift_sequence") or []) if t in SHIFT_TYPES])
	doc.save()
	frappe.db.commit()
	return {"ok": True, "name": doc.name}


@frappe.whitelist(methods=["POST"])
def rotation_plan_action(name, action):
	"""Run a plan's own step: preview (rebuild the day-by-day rows), apply
	(book a Shift Assignment per day), preview_and_apply, or cancel a Draft."""
	_planner()
	doc = frappe.get_doc(PLAN, name)
	doc.check_permission("write")
	if action == "preview":
		result = doc.generate_preview()
	elif action == "apply":
		result = doc.apply_rotation()
	elif action == "preview_and_apply":
		result = doc.generate_and_apply()
	elif action == "cancel":
		if doc.status != "Draft":
			return {"error": _("An applied plan has booked shifts; cancel those shifts instead.")}
		doc.status = "Cancelled"
		doc.save()
		result = {"status": "Cancelled"}
	else:
		return {"error": _("Unknown action {0}.").format(action)}
	frappe.db.commit()
	return {"ok": True, **(result or {})}


# --- watchlist (covert: Security Head / System Manager only) -------------------------

WATCH = "Security Watchlist"
WATCH_FIELDS = ["name", "full_name", "person_type", "employee", "supplier", "id_number", "phone_number", "vehicle_plate",
	"status", "incident", "close_with_incident", "restrict_to_company", "reason", "added_by", "added_on",
	"activity_count", "last_activity_on", "closed_on", "closed_by", "closure_notes"]
WATCH_EDITABLE = ("full_name", "person_type", "employee", "supplier", "id_number", "phone_number", "vehicle_plate",
	"incident", "close_with_incident", "restrict_to_company", "reason", "status", "closure_notes")


def _require_watchlist():
	if not {"Security Head", "System Manager"} & set(frappe.get_roles()):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


@frappe.whitelist()
def watchlist_board(status="Active", search=None, start=0, page_length=50):
	"""Watched people with how often they have been seen, newest activity
	first, and the latest activity across everyone."""
	_require_watchlist()
	filters = [["status", "=", status]] if status in ("Active", "Inactive") else []
	term = (search or "").strip()
	or_filters = None
	if term:
		like = f"%{term}%"
		or_filters = [["full_name", "like", like], ["id_number", "like", like], ["phone_number", "like", like],
			["vehicle_plate", "like", like], ["employee", "like", like]]
	start = max(0, frappe.utils.cint(start))
	counts = {r.status: r.n for r in frappe.get_list(WATCH, fields=["status", {"COUNT": "name", "as": "n"}],
		group_by="status", limit_page_length=0)}
	total = len(frappe.get_list(WATCH, filters=filters, or_filters=or_filters, pluck="name", limit_page_length=0))
	rows = frappe.get_list(WATCH, filters=filters, or_filters=or_filters, fields=WATCH_FIELDS,
		order_by="last_activity_on desc, added_on desc", limit_start=start,
		limit_page_length=min(max(1, frappe.utils.cint(page_length) or 50), 200))
	recent = frappe.get_list("Watchlist Activity", fields=["name", "watchlist", "person", "activity_type", "occurred_at",
		"matched_on", "reference_doctype", "reference_name", "farm", "gate"], order_by="occurred_at desc", limit_page_length=15)
	return {"counts": {"Active": counts.get("Active", 0), "Inactive": counts.get("Inactive", 0)}, "total": total,
		"start": start, "rows": rows, "recent": recent}


@frappe.whitelist()
def watchlist_activity(watchlist, start=0, page_length=50):
	"""Everything logged against one watched person, newest first."""
	_require_watchlist()
	frappe.get_doc(WATCH, watchlist).check_permission("read")
	filters = {"watchlist": watchlist}
	return {
		"total": frappe.db.count("Watchlist Activity", filters),
		"rows": frappe.get_list("Watchlist Activity", filters=filters, fields=["name", "activity_type", "occurred_at",
			"matched_on", "reference_doctype", "reference_name", "farm", "gate", "handled_by", "details"],
			order_by="occurred_at desc", limit_start=max(0, frappe.utils.cint(start)),
			limit_page_length=min(max(1, frappe.utils.cint(page_length) or 50), 200)),
	}


@frappe.whitelist(methods=["POST"])
def save_watchlist_entry(data):
	"""Add someone to the watchlist or change an entry (incl. closing it with
	Inactive + closure notes). The doctype fills ID/phone/plate from an
	Employee and stamps who added or closed it."""
	_require_watchlist()
	data = frappe.parse_json(data) if isinstance(data, str) else frappe._dict(data or {})
	doc = frappe.get_doc(WATCH, data["name"]) if data.get("name") else frappe.new_doc(WATCH)
	if doc.is_new():
		doc.status = "Active"
	for f in WATCH_EDITABLE:
		if f in data:
			doc.set(f, data.get(f) if data.get(f) not in ("",) else None)
	doc.save()
	frappe.db.commit()
	return {"ok": True, "name": doc.name, "status": doc.status}


# --- checkpoints -------------------------------------------------------------------

CHECKPOINT = "Security Checkpoint"
SCAN_LOG = "Checkpoint Scan Log"


@frappe.whitelist()
def checkpoint_board(from_date=None, to_date=None, company=None, farm=None, result=None, search=None, start=0, page_length=50):
	"""Checkpoints with their position status and the period's scans per
	checkpoint (valid / refused, last valid), plus one page of the scan log."""
	if not frappe.has_permission(CHECKPOINT, "read"):
		frappe.throw(_("You do not have permission to view checkpoints."), frappe.PermissionError)
	today = frappe.utils.nowdate()
	from_date = str(frappe.utils.getdate(from_date or frappe.utils.add_days(today, -6)))
	to_date = str(frappe.utils.getdate(to_date or today))
	cp_filters = []
	if farm:
		cp_filters.append(["farm", "=", farm])
	elif company:
		cp_filters.append(["company", "=", company])
	checkpoints = frappe.get_list(CHECKPOINT, filters=cp_filters, limit_page_length=0, order_by="farm asc, checkpoint_name asc",
		fields=["name", "checkpoint_name", "location_hint", "company", "farm", "active", "latitude", "longitude",
			"radius_m", "position_accuracy_m", "position_set_at", "qr_image"])

	window = [["scanned_at", "between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]]]
	scope = [["farm", "=", farm]] if farm else [["company", "=", company]] if company else []
	per = {}
	if frappe.has_permission(SCAN_LOG, "read"):
		for r in frappe.get_list(SCAN_LOG, filters=window + scope, group_by="checkpoint, result", limit_page_length=0,
				fields=["checkpoint", "result", {"COUNT": "name", "as": "n"}, {"MAX": "scanned_at", "as": "last"}]):
			p = per.setdefault(r.checkpoint, {"valid": 0, "refused": 0, "last_valid": None})
			if r.result == "Valid":
				p["valid"] += r.n
				p["last_valid"] = str(r.last)
			else:
				p["refused"] += r.n
	for c in checkpoints:
		c.has_position = bool(c.latitude and c.longitude)
		c.update(per.get(c.name, {"valid": 0, "refused": 0, "last_valid": None}))
		for k in ("latitude", "longitude"):
			c.pop(k, None)

	log_filters = window + scope + ([["result", "=", result]] if result else [])
	term = (search or "").strip()
	if term:
		like = f"%{term}%"
		names = frappe.get_list(SCAN_LOG, filters=log_filters, or_filters=[["guard_name", "like", like],
			["checkpoint_name", "like", like], ["patrol", "like", like]], pluck="name", limit_page_length=5000)
		log_filters = log_filters + [["name", "in", names or ["__none__"]]]
	start = max(0, frappe.utils.cint(start))
	can_log = frappe.has_permission(SCAN_LOG, "read")
	total = len(frappe.get_list(SCAN_LOG, filters=log_filters, pluck="name", limit_page_length=0)) if can_log else 0
	scans = frappe.get_list(SCAN_LOG, filters=log_filters, order_by="scanned_at desc", limit_start=start,
		limit_page_length=min(max(1, frappe.utils.cint(page_length) or 50), 200),
		fields=["name", "checkpoint", "checkpoint_name", "result", "scanned_at", "guard_name", "farm", "patrol",
			"distance_m", "allowed_m", "gps_accuracy", "mocked"]) if can_log else []
	results = sorted({r for r in frappe.get_meta(SCAN_LOG).get_field("result").options.split("\n") if r})
	return {"from_date": from_date, "to_date": to_date, "checkpoints": checkpoints, "total": total, "start": start,
		"scans": scans, "results": results,
		"kpis": {
			"checkpoints": len(checkpoints),
			"active": sum(1 for c in checkpoints if c.active),
			"no_position": sum(1 for c in checkpoints if c.active and not c.has_position),
			"valid": sum(c.valid for c in checkpoints),
			"refused": sum(c.refused for c in checkpoints),
			"unvisited": sum(1 for c in checkpoints if c.active and c.has_position and not c.valid),
		}}


@frappe.whitelist(methods=["POST"])
def save_checkpoint(data):
	"""Add a checkpoint (its QR is made on insert) or change one. The position
	is set on site from the guard app, standing at the checkpoint."""
	if not {"Security Head", "System Manager"} & set(frappe.get_roles()):
		frappe.throw(_("Only a Security Head or System Manager sets up checkpoints."), frappe.PermissionError)
	data = frappe.parse_json(data) if isinstance(data, str) else frappe._dict(data or {})
	doc = frappe.get_doc(CHECKPOINT, data["name"]) if data.get("name") else frappe.new_doc(CHECKPOINT)
	for f in ("checkpoint_name", "location_hint", "farm", "active", "radius_m"):
		if f in data:
			doc.set(f, data.get(f))
	if doc.farm and not doc.company:
		doc.company = frappe.db.get_value("Farm", doc.farm, "company")
	if "company" in data and data.get("company"):
		doc.company = data["company"]
	doc.save()
	frappe.db.commit()
	return {"ok": True, "name": doc.name, "qr_image": doc.qr_image}


# --- staff vehicle stickers ---------------------------------------------------------

STICKER = "Staff Vehicle Sticker"
STICKER_STATUSES = ("Unassigned", "Active", "Suspended", "Lost")


@frappe.whitelist()
def sticker_board(company=None, status=None, search=None, start=0, page_length=50):
	"""Issued stickers with their holder, newest first, and a count per status."""
	if not frappe.has_permission(STICKER, "read"):
		frappe.throw(_("You do not have permission to view vehicle stickers."), frappe.PermissionError)
	filters = [["company", "=", company]] if company else []
	counts = {s: 0 for s in STICKER_STATUSES}
	for r in frappe.get_list(STICKER, filters=filters, fields=["status", {"COUNT": "name", "as": "n"}],
			group_by="status", limit_page_length=0):
		counts[r.status] = r.n
	if status in STICKER_STATUSES:
		filters.append(["status", "=", status])
	term = (search or "").strip()
	if term:
		like = f"%{term}%"
		emps = frappe.get_all("Employee", {"employee_name": ["like", like]}, pluck="name", limit=200)
		names = frappe.get_list(STICKER, filters=filters, or_filters=[["plate_number", "like", like], ["name", "like", like],
			["employee", "like", like], ["employee", "in", emps or ["__none__"]]], pluck="name", limit_page_length=5000)
		filters.append(["name", "in", names or ["__none__"]])
	start = max(0, frappe.utils.cint(start))
	total = len(frappe.get_list(STICKER, filters=filters, pluck="name", limit_page_length=0))
	rows = frappe.get_list(STICKER, filters=filters, order_by="creation desc", limit_start=start,
		limit_page_length=min(max(1, frappe.utils.cint(page_length) or 50), 200),
		fields=["name", "sticker_number", "company", "employee", "vehicle_type", "plate_number", "color", "status", "qr_image", "creation"])
	emp = dict(frappe.get_all("Employee", {"name": ["in", [r.employee for r in rows if r.employee] or ["-"]]},
		["name", "employee_name"], as_list=True))
	for r in rows:
		r.employee_name = emp.get(r.employee) or r.employee
	return {"counts": counts, "total": total, "start": start, "rows": rows,
		"can_manage": frappe.has_permission(STICKER, "write")}


@frappe.whitelist(methods=["POST"])
def set_sticker_status(name, status):
	"""Suspend, report lost, or reactivate a sticker (only Active ones scan in at the gate)."""
	if status not in STICKER_STATUSES:
		return {"error": _("Unknown status {0}.").format(status)}
	doc = frappe.get_doc(STICKER, name)
	doc.check_permission("write")
	doc.status = status
	doc.save()
	frappe.db.commit()
	return {"ok": True, "name": doc.name, "status": doc.status}


# --- shared paging helper ----------------------------------------------------------

def _page(doctype, filters, fields, order_by, start=0, page_length=50, or_filters=None):
	start = max(0, frappe.utils.cint(start))
	total = len(frappe.get_list(doctype, filters=filters, or_filters=or_filters, pluck="name", limit_page_length=0))
	rows = frappe.get_list(doctype, filters=filters, or_filters=or_filters, fields=fields, order_by=order_by,
		limit_start=start, limit_page_length=min(max(1, frappe.utils.cint(page_length) or 50), 200))
	return total, start, rows


def _window(field, from_date, to_date, default_days):
	today = frappe.utils.nowdate()
	from_date = str(frappe.utils.getdate(from_date or frappe.utils.add_days(today, -(default_days - 1))))
	to_date = str(frappe.utils.getdate(to_date or today))
	return from_date, to_date, [field, "between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]]


def _farm_scope(filters, company=None, farm=None, company_field="company"):
	if farm:
		filters.append(["farm", "=", farm])
	elif company:
		filters.append([company_field, "=", company])


def _search_filter(doctype, filters, fields, search):
	term = (search or "").strip()
	if not term:
		return filters
	like = f"%{term}%"
	names = frappe.get_list(doctype, filters=filters, or_filters=[[f, "like", like] for f in fields],
		pluck="name", limit_page_length=5000)
	return filters + [["name", "in", names or ["__none__"]]]


def _group_counts(doctype, filters, field):
	return {(r.get(field) or ""): r.n for r in frappe.get_list(doctype, filters=filters, group_by=field,
		fields=[field, {"COUNT": "name", "as": "n"}], limit_page_length=0)}


# --- access alerts (Unauthorized Access Attempt) -------------------------------------

UAA = "Unauthorized Access Attempt"


@frappe.whitelist()
def access_alerts(from_date=None, to_date=None, company=None, farm=None, attempt_type=None, severity=None,
		search=None, start=0, page_length=50):
	"""Security alerts raised by the gate, patrol and checkpoint checks, newest first."""
	if not frappe.has_permission(UAA, "read"):
		frappe.throw(_("You do not have permission to view access alerts."), frappe.PermissionError)
	from_date, to_date, win = _window("attempt_time", from_date, to_date, 7)
	base = [win]
	_farm_scope(base, company, farm)
	base = _search_filter(UAA, base, ["reference", "detail", "person_name", "attempted_by"], search)
	by_type = _group_counts(UAA, base, "attempt_type")
	by_sev = _group_counts(UAA, base, "severity")
	filters = list(base)
	if attempt_type:
		filters.append(["attempt_type", "=", attempt_type])
	if severity:
		filters.append(["severity", "=", severity])
	total, start, rows = _page(UAA, filters, ["name", "attempt_type", "reference", "company", "farm", "attempt_time",
		"detail", "attempted_by", "zone", "person_name", "severity", "latitude", "longitude"], "attempt_time desc", start, page_length)
	users = dict(frappe.get_all("User", {"name": ["in", [r.attempted_by for r in rows if r.attempted_by] or ["-"]]},
		["name", "full_name"], as_list=True))
	for r in rows:
		r.attempted_by_name = users.get(r.attempted_by) or r.attempted_by
	types = [t for t in (frappe.get_meta(UAA).get_field("attempt_type").options or "").split("\n") if t]
	return {"from_date": from_date, "to_date": to_date, "by_type": by_type, "by_severity": by_sev,
		"total_all": sum(by_type.values()), "types": types, "total": total, "start": start, "rows": rows}


# --- personal items carried through the gate ------------------------------------------

RPI = "Registered Personal Item"
EXIT_STATES = ("Inside", "Left with owner", "Not seen leaving", "Left with document")


@frappe.whitelist()
def personal_items(from_date=None, to_date=None, company=None, farm=None, exit_status=None, party_type=None,
		search=None, start=0, page_length=50):
	"""Items declared at the gate - who brought what, and whether it left."""
	if not frappe.has_permission(RPI, "read"):
		frappe.throw(_("You do not have permission to view personal items."), frappe.PermissionError)
	from_date, to_date, win = _window("entry_time", from_date, to_date, 30)
	base = [win]
	_farm_scope(base, company, farm)
	if party_type:
		base.append(["party_type", "=", party_type])
	base = _search_filter(RPI, base, ["carried_by", "item", "serial_notes", "reference_name", "supporting_document"], search)
	counts = {s: 0 for s in EXIT_STATES}
	counts.update(_group_counts(RPI, base, "exit_status"))
	filters = base + ([["exit_status", "=", exit_status]] if exit_status in EXIT_STATES else [])
	total, start, rows = _page(RPI, filters, ["name", "party_type", "carried_by", "employee", "supplier", "reference_doctype",
		"reference_name", "farm", "company", "item", "qty", "serial_notes", "declared_at", "entry_time", "recorded_by",
		"exit_status", "exit_time", "exit_checked_by", "supporting_document", "supporting_document_file"],
		"entry_time desc", start, page_length)
	return {"from_date": from_date, "to_date": to_date, "counts": counts, "total": total, "start": start, "rows": rows,
		"can_edit": frappe.has_permission(RPI, "write")}


@frappe.whitelist(methods=["POST"])
def set_item_exit(name, exit_status, note=None):
	"""Settle an item afterwards: it did leave with its owner (or with a
	document), or is still inside. Who settled it and when is recorded."""
	if exit_status not in EXIT_STATES:
		return {"error": _("Unknown exit status {0}.").format(exit_status)}
	doc = frappe.get_doc(RPI, name)
	doc.check_permission("write")
	doc.exit_status = exit_status
	if exit_status == "Inside":
		doc.exit_time = doc.exit_checked_by = None
	else:
		doc.exit_time = doc.exit_time or frappe.utils.now_datetime()
		doc.exit_checked_by = frappe.session.user
	note = (note or "").strip()
	if note:
		doc.serial_notes = ((doc.serial_notes or "") + " · " if doc.serial_notes else "") + note
	doc.save()
	frappe.db.commit()
	return {"ok": True, "name": doc.name, "exit_status": doc.exit_status}


# --- gate badges ------------------------------------------------------------------

BADGE = "Gate Badge"
BADGE_STATUSES = ("Available", "Issued", "Held at Other Farm", "Lost")


@frappe.whitelist()
def badge_board(badge_type=None, status=None, company=None, farm=None, search=None, start=0, page_length=100):
	"""Every visitor, supplier and contractor badge: who holds it, for what."""
	if not frappe.has_permission(BADGE, "read"):
		frappe.throw(_("You do not have permission to view badges."), frappe.PermissionError)
	base = []
	if badge_type in ("Visitor", "Supplier", "Contractor"):
		base.append(["badge_type", "=", badge_type])
	if company:
		base.append(["company", "=", company])
	if farm:
		base.append(["farm", "=", farm])
	term = (search or "").strip()
	if term:
		like = f"%{term}%"
		or_f = [["holder_name", "like", like], ["holder_id_number", "like", like], ["current_appointment", "like", like],
			["supplier", "like", like]]
		if term.isdigit():
			or_f.append(["badge_number", "=", int(term)])
		names = frappe.get_list(BADGE, filters=base, or_filters=or_f, pluck="name", limit_page_length=5000)
		base = base + [["name", "in", names or ["__none__"]]]
	counts = {s: 0 for s in BADGE_STATUSES}
	counts.update(_group_counts(BADGE, base, "status"))
	filters = base + ([["status", "=", status]] if status in BADGE_STATUSES else [])
	total, start, rows = _page(BADGE, filters, ["name", "badge_type", "badge_number", "company", "farm", "status", "held_at_farm",
		"current_appointment", "current_receiving", "supplier", "holder_name", "valid_until", "issued_at", "issued_by", "qr_image"],
		"badge_type asc, company asc, farm asc, badge_number asc", start, page_length)
	return {"counts": counts, "total": total, "start": start, "rows": rows,
		"can_manage": bool({"Security Head", "System Manager"} & set(frappe.get_roles()))}


@frappe.whitelist(methods=["POST"])
def set_badge_status(name, status):
	"""Report a badge lost, or put it back in its stock (Available clears its
	holder - the badge's own rule)."""
	if not {"Security Head", "System Manager"} & set(frappe.get_roles()):
		frappe.throw(_("Only a Security Head manages badges."), frappe.PermissionError)
	if status not in ("Available", "Lost"):
		return {"error": _("A badge can be marked Available or Lost here; issuing happens at the gate.")}
	doc = frappe.get_doc(BADGE, name)
	doc.status = status
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "name": doc.name, "status": doc.status}


# --- guards and their devices ---------------------------------------------------------

GUARD = "Security Guard"
DEVICE = "Guard Device Token"


@frappe.whitelist()
def guard_board(company=None, farm=None, status="Active", search=None, start=0, page_length=100):
	"""The external guard register, with each guard's shifts this week, last
	biometric punch and app device."""
	if not frappe.has_permission(GUARD, "read"):
		frappe.throw(_("You do not have permission to view guards."), frappe.PermissionError)
	base = []
	if company:
		base.append(["company", "=", company])
	if farm:
		base.append(["farm", "=", farm])
	base = _search_filter(GUARD, base, ["full_name", "name", "post", "phone_number"], search)
	counts = _group_counts(GUARD, base, "status")
	filters = base + ([["status", "=", status]] if status else [])
	total, start, rows = _page(GUARD, filters, ["name", "full_name", "status", "company", "farm", "post", "reliever",
		"designation", "phone_number", "date_of_joining", "user"], "farm asc, post asc, full_name asc", start, page_length)
	ids = [r.name for r in rows] or ["-"]
	names = dict(frappe.get_all(GUARD, {"name": ["in", [r.reliever for r in rows if r.reliever] or ["-"]]}, ["name", "full_name"], as_list=True))
	monday = frappe.utils.get_first_day_of_week(frappe.utils.nowdate())
	shifts = {r.external_guard: r.n for r in frappe.get_all("Security Guard Shift Assignment",
		filters={"external_guard": ["in", ids], "start_date": [">=", monday], "status": ["!=", "Cancelled"]},
		fields=["external_guard", {"COUNT": "name", "as": "n"}], group_by="external_guard")}
	punch = {r.security_guard: r.last for r in frappe.get_all("Security Checkin", filters={"security_guard": ["in", ids]},
		fields=["security_guard", {"MAX": "time", "as": "last"}], group_by="security_guard")} if frappe.db.table_exists("Security Checkin") else {}
	devices = {}
	for d in frappe.get_all(DEVICE, filters={"external_guard": ["in", ids]}, order_by="modified desc",
			fields=["external_guard", "app_version", "platform", "last_app_open", "modified"]):
		devices.setdefault(d.external_guard, d)
	for r in rows:
		r.reliever_name = names.get(r.reliever)
		r.shifts_this_week = shifts.get(r.name, 0)
		r.last_punch = str(punch.get(r.name) or "") or None
		dev = devices.get(r.name)
		r.app_version = dev.app_version if dev else None
		r.app_last_open = str(dev.last_app_open or dev.modified) if dev else None
	return {"counts": counts, "total": total, "start": start, "rows": rows, "can_edit": frappe.has_permission(GUARD, "write")}


@frappe.whitelist(methods=["POST"])
def save_guard(name, post=None, farm=None, reliever=None, status=None):
	"""Change a guard's posting: farm, post, designated reliever, status."""
	doc = frappe.get_doc(GUARD, name)
	doc.check_permission("write")
	for f, v in (("post", post), ("farm", farm), ("reliever", reliever), ("status", status)):
		if f in frappe.form_dict or v is not None:
			doc.set(f, v or None)
	if doc.reliever == doc.name:
		return {"error": _("A guard cannot be their own reliever.")}
	doc.save()
	frappe.db.commit()
	return {"ok": True, "name": doc.name}


@frappe.whitelist()
def device_board(search=None, start=0, page_length=100):
	"""Guard phones: who uses which, app version and when it was last opened."""
	if not frappe.has_permission(DEVICE, "read"):
		frappe.throw(_("You do not have permission to view guard devices."), frappe.PermissionError)
	filters = _search_filter(DEVICE, [], ["guard_name", "login_user", "device_model", "app_version"], search)
	total, start, rows = _page(DEVICE, filters, ["name", "login_user", "guard_name", "guard_type", "internal_guard",
		"external_guard", "platform", "app_version", "runtime_version", "update_status", "update_channel", "device_model",
		"os_version", "last_app_open", "last_seen_lat", "last_seen_lng", "updated_at", "modified"],
		"last_app_open desc, modified desc", start, page_length)
	versions = {}
	for r in frappe.get_all(DEVICE, fields=["app_version"]):
		versions[r.app_version or "?"] = versions.get(r.app_version or "?", 0) + 1
	return {"total": total, "start": start, "rows": rows, "versions": versions}


# --- settings (Security Ops Settings, the whole doctype) -------------------------------
# The page is drawn from the doctype's own definition, so a field added to
# Security Ops Settings shows up in v2 with no frontend change. Saving goes
# through the doctype's validate() and permissions like a Desk save.

SETTINGS = "Security Ops Settings"
_LAYOUT = ("Section Break", "Column Break", "Tab Break")
_NOT_EDITABLE = _LAYOUT + ("HTML", "Button", "Heading", "Image", "Fold")
_META_KEYS = ("fieldname", "fieldtype", "label", "options", "description", "default", "reqd", "read_only",
	"depends_on", "collapsible", "in_list_view", "hidden", "bold")


# The Words Used section talks about the words themselves: never relabel it.
_TERMS_FIELDS = {"terminology_section", "use_custom_words", "site_label", "site_label_plural",
	"terminology_column", "area_label", "area_label_plural"}


def _field_meta(df, terms):
	out = {k: df.get(k) for k in _META_KEYS}
	# Required only under a condition: that condition is the field's own
	# depends_on here, so while it shows it is required.
	if df.get("mandatory_depends_on"):
		out["reqd"] = 1
	if df.fieldname in _TERMS_FIELDS:
		return out
	out["label"] = _relabel(out["label"] or "", terms) if out["label"] else out["label"]
	if out["description"]:
		out["description"] = _relabel(out["description"], terms)
	return out


@frappe.whitelist()
def settings_form():
	"""Security Ops Settings for the v2 Settings page: its layout, each child
	table's columns, the current values, and whether the user may save."""
	if not frappe.has_permission(SETTINGS, "read"):
		frappe.throw(_("You do not have permission to view the security settings."), frappe.PermissionError)
	terms = get_terms()
	meta = frappe.get_meta(SETTINGS)
	doc = frappe.get_single(SETTINGS)
	fields = [_field_meta(df, terms) for df in meta.fields if not df.hidden]
	children = {}
	values = {}
	for df in meta.fields:
		if df.fieldtype in ("Table", "Table MultiSelect"):
			cmeta = frappe.get_meta(df.options)
			children[df.options] = [_field_meta(c, terms) for c in cmeta.fields if not c.hidden]
			keep = {c.fieldname for c in cmeta.fields if c.fieldtype not in _NOT_EDITABLE}
			values[df.fieldname] = [{"name": r.name, **{k: r.get(k) for k in keep}} for r in doc.get(df.fieldname) or []]
		elif df.fieldtype not in _NOT_EDITABLE:
			v = doc.get(df.fieldname)
			values[df.fieldname] = str(v) if df.fieldtype in ("Time", "Date", "Datetime") and v is not None else v
	return {"fields": fields, "children": children, "values": values, "modified": str(doc.modified),
		"can_write": frappe.has_permission(SETTINGS, "write"), "terms": terms}


@frappe.whitelist(methods=["POST"])
def save_settings(values, modified=None):
	"""Save the fields the page sends (child tables are sent whole). Refused
	when someone else saved the settings after this page loaded them."""
	if not frappe.has_permission(SETTINGS, "write"):
		frappe.throw(_("You do not have permission to change the security settings."), frappe.PermissionError)
	values = frappe.parse_json(values) if isinstance(values, str) else (values or {})
	doc = frappe.get_single(SETTINGS)
	if modified and str(doc.modified) != str(modified):
		return {"error": _("Someone else saved these settings while you were editing. Reload to see their changes, then make yours again.")}
	meta = doc.meta
	for df in meta.fields:
		if df.fieldname not in values or df.fieldtype in _NOT_EDITABLE or df.read_only:
			continue
		if df.fieldtype in ("Table", "Table MultiSelect"):
			cmeta = frappe.get_meta(df.options)
			keep = {c.fieldname for c in cmeta.fields if c.fieldtype not in _NOT_EDITABLE}
			rows = []
			for r in values[df.fieldname] or []:
				row = {k: v for k, v in r.items() if k in keep}
				if r.get("name") and not str(r["name"]).startswith("new-"):
					row["name"] = r["name"]
				rows.append(row)
			doc.set(df.fieldname, rows)
		else:
			doc.set(df.fieldname, values[df.fieldname])
	doc.save()
	frappe.db.commit()
	return {"ok": True, "modified": str(doc.modified), "terms": get_terms()}
