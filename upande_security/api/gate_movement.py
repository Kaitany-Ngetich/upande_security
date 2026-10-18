# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt
"""Gate-level movement tracing.

Security Gate Config (child table on the Security Ops Settings single doc,
under `farm_gates`) records which physical gates each farm has. This module
is the one place that reads it, so a vehicle/visitor's entry and exit gate
can be captured and compared - a mismatch (entered through Gate A, left
through Gate B) is a real anomaly worth flagging, not just a data point.
"""

from datetime import timedelta

import frappe


def _roster_guard(user):
	"""(internal_guard, external_guard) for this login - Employee linked by
	user_id, then Security Guard by its User Account field, then by full name
	(shared gate logins are named after the guard)."""
	employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
	guard = frappe.db.get_value("Security Guard", {"user": user, "status": "Active"}, "name")
	if not guard:
		full_name = frappe.db.get_value("User", user, "full_name") or ""
		if full_name:
			guard = frappe.db.get_value(
				"Security Guard", {"full_name": full_name, "status": "Active"}, "name"
			)
	return employee, guard


def _covers(shift, now, grace_minutes=0):
	"""True if `now` falls inside the shift's hours, widened by grace_minutes
	either side. See _shift_window for shifts with no times or past midnight."""
	start, end = _shift_window(shift)
	grace = timedelta(minutes=grace_minutes)
	return start - grace <= now < end + grace


# A location change ends with the shift it was made in; one left running
# must not quietly carry over to the guard's next shift.
_LOCATION_CHANGE_HOURS = 14


def _active_location_change(user):
	"""The guard's Active Guard Location Change, or None. One older than
	_LOCATION_CHANGE_HOURS has lapsed and no longer counts."""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-_LOCATION_CHANGE_HOURS)
	rows = frappe.get_all(
		"Guard Location Change",
		filters={"guard_user": user, "status": "Active", "started_at": [">=", cutoff]},
		fields=["name", "farm", "gate", "reason", "started_at", "rostered_farm", "rostered_gate"],
		order_by="started_at desc",
		limit=1,
	)
	return rows[0] if rows else None


def guard_post(user=None):
	"""(farm, gate) where the calling guard is posted right now.

	A location change the guard made in the app (emergency cover) comes
	first; otherwise their Security Guard Shift Assignment - not the static
	farm on Security Guard, since guards are moved between blocks. Blocks
	are named "<Farm> - <Post>"; the post is returned as the gate. A shift
	covering the current time wins, else any shift dated today. (None, None)
	when the guard has neither."""
	user = user or frappe.session.user
	change = _active_location_change(user)
	if change:
		return change.farm, change.gate
	return rostered_post(user)


def rostered_post(user):
	"""(farm, gate) from the roster alone - see guard_post."""
	employee, guard = _roster_guard(user)
	or_filters = []
	if employee:
		or_filters.append(["internal_guard", "=", employee])
	if guard:
		or_filters.append(["external_guard", "=", guard])
	if not or_filters:
		return None, None
	now = frappe.utils.now_datetime()
	today = now.date()
	shifts = frappe.get_all(
		"Security Guard Shift Assignment",
		filters=[
			["status", "in", ["Scheduled", "Active"]],
			["start_date", "<=", today],
			# yesterday's night shift can still be running this morning
			["end_date", ">=", frappe.utils.add_days(today, -1)],
		],
		or_filters=or_filters,
		fields=["farm", "block", "start_date", "end_date", "start_time", "end_time"],
		order_by="start_date desc, start_time desc",
	)
	current = next((s for s in shifts if _covers(s, now)), None)
	if not current:
		current = next((s for s in shifts if _covers(s, now, _SHIFT_GRACE_MINUTES)), None)
	if not current:
		current = next((s for s in shifts if s.start_date <= today <= s.end_date), None)
	if not current:
		return None, None
	block = current.block or ""
	parts = block.split(" - ", 1)
	farm = current.farm or (parts[0] if len(parts) > 1 else None)
	gate = parts[1] if len(parts) > 1 else None
	return farm, gate


def requested_farm():
	"""The farm the app says this guard is at, for logins with no farm of
	their own (no Employee.custom_farm, no Security Guard farm). The app
	sends it as `checking_farm` with every request once the guard has
	chosen it. Only a real Farm counts. Callers must use it as a FALLBACK
	only - a linked farm always wins, so nobody can record under a farm
	they are not assigned to."""
	farm = (frappe.form_dict.get("checking_farm") or "").strip()
	if farm and frappe.db.exists("Farm", farm):
		return farm
	return None


@frappe.whitelist()
def list_gate_farms():
	"""Every farm with its active gates (main gate first; "Main Gate" when a
	farm has none configured) - feeds the app's farm picker for guards whose
	login is not linked to a farm."""
	return [
		{"farm": name, "gates": get_farm_gates(name)}
		for name in frappe.get_all("Farm", pluck="name", order_by="name asc")
	]


def resolve_gate(gate, farm):
	"""The gate a movement is recorded at: the guard's rostered post when it
	is one of this farm's gates, else what the guard picked, else the
	farm's main (or only) configured gate, else "Main Gate" - the same order
	the app's gate picker uses, so an older app build that sends no gate
	still records one."""
	gate = (gate or "").strip()
	gates = get_farm_gates(farm) if farm else []
	# The roster names the guard's post; at that farm it beats the picker,
	# which the app pre-selects to the main gate.
	roster_farm, roster_gate = guard_post()
	if roster_farm == farm and roster_gate:
		match = next((g for g in gates if g["gate_name"].lower() == roster_gate.lower()), None)
		if match:
			return match["gate_name"]
	# Only a gate this farm actually has - a stale pick from another farm, or
	# anything else the client sends, falls back to the default.
	if gate and any(g["gate_name"] == gate for g in gates):
		return gate
	return gates[0]["gate_name"] if gates else "Main Gate"


@frappe.whitelist()
def get_farm_gates(farm):
	"""Active gates configured for a farm, main gate first. Used by the
	mobile app to populate the "which gate?" picker at gate entry/exit -
	for a single-gate farm this is a one-item list (auto-flagged as the
	main gate by Security Ops Settings' own validate()), so the picker can
	just as easily be skipped and defaulted client-side.

	A farm with ZERO rows in Security Ops Settings gets a synthetic single
	"Main Gate" entry rather than an empty list - most farms only have one
	physical gate, and a single gate has nothing to disambiguate anyway, so
	requiring someone to add a row per farm just to get a non-blank value
	recorded would be pure busywork with no security benefit. The moment a
	farm gets real rows configured (e.g. Kapkolia's actual 3 gates), those
	take over automatically - this fallback only fires for a farm nobody
	has configured yet.
	"""
	if not farm:
		return []
	settings = frappe.get_single("Security Ops Settings")
	gates = [
		{"gate_name": row.gate_name, "is_main_gate": bool(row.is_main_gate)}
		for row in (settings.farm_gates or [])
		if row.farm == farm and row.active
	]
	if not gates:
		return [{"gate_name": "Main Gate", "is_main_gate": True}]
	gates.sort(key=lambda g: (not g["is_main_gate"], g["gate_name"]))
	return gates


def compute_gate_mismatch(entry_gate, exit_gate):
	"""True only when both ends are known and genuinely differ - a blank
	gate (guard skipped the picker, or the site predates this feature) is
	never treated as a mismatch, since that would just be noise.

	Kept here as the one shared definition, even though the two consumers
	(Appointment for visitors/contractors, Timesheet for the Company
	Vehicle gate-tracking flow - NOT Tractor Daily Task's custom_gate_*
	fields, which were only ever a design-doc spec and were never actually
	wired up) each set their own custom_gate_mismatch inline via
	frappe.db.set_value from a sandboxed Server Script, which can't import
	this module. This function documents the rule those scripts duplicate.
	"""
	return bool(entry_gate and exit_gate and entry_gate != exit_gate)


def _location(user):
	farm, gate = rostered_post(user)
	change = _active_location_change(user)
	if change:
		source, here, here_gate = "change", change.farm, change.gate
	elif farm:
		source, here, here_gate = "roster", farm, gate
	else:
		# Not rostered today: the farm on the guard's own record, if any.
		from upande_security.api.gate_vehicle import _resolve_checking_farm

		here = _resolve_checking_farm(user, linked_only=True)
		source, here_gate = ("record" if here else None), None
	return {
		"rostered": {"farm": farm, "gate": gate} if farm else None,
		"change": change,
		"farm": here,
		"gate": here_gate,
		"source": source,
	}


@frappe.whitelist()
def get_my_location():
	"""Where the gate app should say this guard is: the rostered post, and
	any active location change on top of it."""
	return _location(frappe.session.user)


@frappe.whitelist(methods=["POST"])
def change_location(farm, gate, reason):
	"""Emergency switch away from the rostered post - e.g. covering a gate
	nobody turned up for. Every scan after this records the chosen farm and
	gate until return_to_roster() or the change lapses.

	Never silent: each change is a Guard Location Change record (Security
	Head can read it, guards cannot) and every security recipient gets a
	notification, so someone covering for an absent colleague - or claiming
	to - is visible the moment it happens."""
	user = frappe.session.user
	farm = (farm or "").strip()
	gate = (gate or "").strip()
	reason = (reason or "").strip()
	if not frappe.db.exists("Farm", farm):
		return {"error": "Choose a valid farm."}
	if not any(g["gate_name"] == gate for g in get_farm_gates(farm)):
		return {"error": "Choose one of " + farm + "'s gates."}
	if len(reason) < 5:
		return {"error": "Give a reason for the change."}

	rostered_farm, rostered_gate = rostered_post(user)
	employee, guard = _roster_guard(user)
	_end_location_changes(user)
	doc = frappe.new_doc("Guard Location Change")
	doc.guard_user = user
	doc.guard_name = frappe.db.get_value("User", user, "full_name") or user
	doc.external_guard = guard
	doc.internal_guard = employee
	doc.status = "Active"
	doc.started_at = frappe.utils.now_datetime()
	doc.rostered_farm = rostered_farm
	doc.rostered_gate = rostered_gate
	doc.farm = farm
	doc.gate = gate
	doc.reason = reason
	doc.insert(ignore_permissions=True)
	_notify_location_change(doc)
	return _location(user)


@frappe.whitelist(methods=["POST"])
def return_to_roster():
	"""End the guard's location change; scans go back to the rostered post."""
	_end_location_changes(frappe.session.user)
	return _location(frappe.session.user)


def _end_location_changes(user):
	for name in frappe.get_all(
		"Guard Location Change", filters={"guard_user": user, "status": "Active"}, pluck="name"
	):
		frappe.db.set_value(
			"Guard Location Change", name, {"status": "Ended", "ended_at": frappe.utils.now_datetime()}
		)


def _notify_location_change(doc):
	"""Best-effort Notification Log to every security recipient - a failure
	here must not undo the change the guard needs to keep working."""
	from upande_security.utils.notifications import resolve_notification_users

	rostered = (doc.rostered_farm + " - " + (doc.rostered_gate or "?")) if doc.rostered_farm else "not rostered"
	subject = doc.guard_name + " moved to " + doc.farm + " - " + doc.gate
	detail = "Rostered: " + rostered + "<br>Reason: " + frappe.utils.escape_html(doc.reason)
	for recipient in resolve_notification_users("security"):
		try:
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"for_user": recipient,
					"subject": subject,
					"email_content": detail,
					"document_type": "Guard Location Change",
					"document_name": doc.name,
					"type": "Alert",
				}
			).insert(ignore_permissions=True)
		except Exception as e:
			frappe.log_error("_notify_location_change for " + doc.name, str(e))


# --- Off-shift account use -------------------------------------------------
# A guard's login used at the gate outside that guard's shift is most likely
# someone else on a borrowed account (e.g. a colleague whose shift ended).
# Gate actions from it are refused and reported to the security heads.

# Slack either side of a shift for handover and late relief.
_SHIFT_GRACE_MINUTES = 60

# Gate actions (last segment of the /api/method path) that need the login to
# be on shift. Lookups/searches stay open; so does change_location, which is
# how a guard called in off-roster declares it (and is itself reported).
GATE_ACTIONS = {
	"create_staff_attendance",
	"staff_gate_checkout",
	"gate_temp_exit",
	"check_in_visitor",
	"check_out_visitor",
	"create_walk_in",
	"create_walk_in_notify",
	"issue_visitor_badge",
	"contractor_gate_checkin",
	"contractor_gate_checkout",
	"scan_contractor_badge",
	"record_sticker_driver",
	"issue_contractor_badge",
	"verify_vehicle_task_at_gate",
	"verify_dispatch_at_gate",
	"verify_dispatch_at_gate_bulk",
	"verify_receiving_at_gate",
	"verify_receiving_at_gate_bulk",
}

_EXEMPT_ROLES = ("Security Head", "System Manager")


def _shift_window(shift):
	"""(start, end) datetimes of a shift; one ending before it starts runs
	past midnight. A shift with no times spans its whole dates."""
	start_time = shift.start_time or "00:00:00"
	end_time = shift.end_time or "23:59:59"
	start = frappe.utils.get_datetime(str(shift.start_date) + " " + str(start_time))
	end = frappe.utils.get_datetime(str(shift.end_date) + " " + str(end_time))
	if end <= start:
		end = end + timedelta(days=1)
	return start, end


def off_shift_reason(user):
	"""Why this login may not act at the gate right now, or None if it may.

	Only applies to logins matched to a rostered guard (any shift within a
	week either way); everyone else - security heads, admins, logins not on
	the roster - is never blocked. An active location change also allows it.
	"""
	if not user or user in ("Guest", "Administrator"):
		return None
	if any(role in _EXEMPT_ROLES for role in frappe.get_roles(user)):
		return None
	employee, guard = _roster_guard(user)
	or_filters = []
	if employee:
		or_filters.append(["internal_guard", "=", employee])
	if guard:
		or_filters.append(["external_guard", "=", guard])
	if not or_filters:
		return None
	if _active_location_change(user):
		return None
	today = frappe.utils.getdate()
	shifts = frappe.get_all(
		"Security Guard Shift Assignment",
		filters=[
			["status", "in", ["Scheduled", "Active"]],
			["start_date", "<=", frappe.utils.add_days(today, 7)],
			["end_date", ">=", frappe.utils.add_days(today, -7)],
		],
		or_filters=or_filters,
		fields=["start_date", "end_date", "start_time", "end_time"],
	)
	if not shifts:
		return None
	now = frappe.utils.now_datetime()
	grace = timedelta(minutes=_SHIFT_GRACE_MINUTES)
	ended, upcoming = None, None
	for shift in shifts:
		if _covers(shift, now, _SHIFT_GRACE_MINUTES):
			return None
		start, end = _shift_window(shift)
		if end + grace <= now and (not ended or end > ended):
			ended = end
		if now < start - grace and (not upcoming or start < upcoming):
			upcoming = start
	if ended and ended.date() >= today - timedelta(days=1):
		reason = "This account's shift ended at " + ended.strftime("%H:%M")
	elif upcoming and upcoming.date() == today:
		reason = "This account's shift starts at " + upcoming.strftime("%H:%M")
	else:
		reason = "This account is not on shift today"
	return reason


def check_on_shift():
	"""before_request hook: refuse gate actions from a login that is off
	shift (see off_shift_reason), after reporting the attempt."""
	request = getattr(frappe.local, "request", None)
	path = request.path if request else ""
	if "/method/" not in path:
		return
	action = path.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
	if action not in GATE_ACTIONS:
		return
	user = frappe.session.user
	reason = off_shift_reason(user)
	if not reason:
		return
	_report_off_shift(user, action, reason)
	frappe.throw(
		reason + ". Log in with your own account, or use Change location if you have been called in to cover.",
		title="Off shift",
	)


def _report_off_shift(user, action, reason):
	"""Unauthorized Access Attempt + notification to the security heads -
	always, not only when feature_security_alerts is on. Repeats from the
	same login within 15 minutes are one attempt, not a flood."""
	try:
		recent = frappe.db.exists(
			"Unauthorized Access Attempt",
			{
				"attempt_type": "Off-Shift Account Use",
				"attempted_by": user,
				"attempt_time": [">=", frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-15)],
			},
		)
		if recent:
			return
		from upande_security.api.security_alerts import _notify_unauthorized_access

		full_name = frappe.db.get_value("User", user, "full_name") or user
		attempt = frappe.new_doc("Unauthorized Access Attempt")
		attempt.attempt_type = "Off-Shift Account Use"
		attempt.reference = full_name
		attempt.farm = rostered_post(user)[0]
		attempt.detail = (
			full_name + "'s account was used at the gate (" + action + ") outside their shift. "
			+ reason + "."
		)
		attempt.attempted_by = user
		attempt.attempt_time = frappe.utils.now_datetime()
		attempt.flags.ignore_links = True
		attempt.insert(ignore_permissions=True)
		_notify_unauthorized_access(attempt)
		# The request is about to fail and roll back; keep the report.
		frappe.db.commit()
	except Exception as e:
		frappe.log_error("off-shift report: " + str(user), str(e))
