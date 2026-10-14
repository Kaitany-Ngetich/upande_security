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


def _covers(shift, now):
	"""True if `now` falls inside the shift's own hours. A shift with no
	times covers its whole date; one ending before it starts runs past
	midnight into the next day."""
	if not shift.start_time or not shift.end_time:
		return shift.start_date <= now.date() <= shift.end_date
	start = frappe.utils.get_datetime(str(shift.start_date) + " " + str(shift.start_time))
	end = frappe.utils.get_datetime(str(shift.end_date) + " " + str(shift.end_time))
	if end <= start:
		end = end + timedelta(days=1)
	return start <= now < end


def guard_post(user=None):
	"""(farm, gate) where the calling guard is rostered right now, from their
	Security Guard Shift Assignment - not the static farm on Security Guard,
	since guards are moved between blocks. Blocks are named "<Farm> - <Post>";
	the post is returned as the gate. A shift covering the current time wins,
	else any shift dated today. (None, None) when the guard is not rostered."""
	user = user or frappe.session.user
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
