# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Who can cover a guard's day off.

suggest_relievers() lists the guards who could take an off guard's shift on
one date, ranked by how well they know that farm and shift, and says why. It
is what the Shift Schedule grid and the Rotation Plan show when a planner
marks a day off; toggle_guard_day(cover_guard=...) then books the chosen one
and checks again that they are still free.

Only External Guards are candidates: a cover is a Security Guard Shift
Assignment with external_guard set, and Internal Guards' shifts come from HR.
"""

import datetime
import json

import frappe
from frappe import _
from frappe.utils import add_days, getdate, to_timedelta

from upande_security.api.gate_movement import _shift_window

PLANNER_ROLES = ("Security Head", "System Manager")
HISTORY_DAYS = 60
DEFAULT_LIMIT = 25


def require_planner():
	"""Security Head, System Manager, or anyone who can write Shift Assignments."""
	if set(PLANNER_ROLES) & set(frappe.get_roles()):
		return
	if frappe.has_permission("Security Guard Shift Assignment", "write"):
		return
	frappe.throw(_("You are not allowed to plan relief cover."), frappe.PermissionError)


def cover_window(date_val, start_time, end_time):
	"""(start, end) datetimes of a shift starting on date_val; an end at or
	before the start runs past midnight."""
	day = datetime.datetime.combine(getdate(date_val), datetime.time())
	start = day + to_timedelta(start_time)
	end = day + to_timedelta(end_time)
	if end <= start:
		end += datetime.timedelta(days=1)
	return start, end


def _hhmm(t):
	"""08:00 from a timedelta or time string."""
	secs = int(to_timedelta(t).total_seconds()) % 86400
	return "%02d:%02d" % (secs // 3600, (secs % 3600) // 60)


def _parse_list(value):
	if not value:
		return []
	if isinstance(value, (list, tuple, set)):
		return [v for v in value if v]
	value = str(value).strip()
	if value.startswith("["):
		return [v for v in json.loads(value) if v]
	return [v.strip() for v in value.split(",") if v.strip()]


def busy_reasons(candidates, off_guard, date_val, window):
	"""{candidate: why they can't cover} for the candidates who are busy.

	Busy means a Shift Assignment (not Cancelled) whose window overlaps the
	cover window - the day before and after are read too, for overnight
	shifts, including rows that store a 22:00-06:00 shift with end_date equal
	to start_date - or already covering another guard that day. A row that
	already covers off_guard on this date is this very cover, not a clash.
	Shifts that only touch (one ends at 06:00, the other starts at 06:00) are
	a handover, not a clash.
	"""
	if not candidates:
		return {}
	date_val = getdate(date_val)
	rows = frappe.db.sql(
		"""
		SELECT external_guard, farm, shift_type, start_date, start_time, end_date, end_time, covering_for
		FROM `tabSecurity Guard Shift Assignment`
		WHERE security_guard = 'External Guard'
		  AND external_guard IN %(guards)s
		  AND start_date BETWEEN %(from)s AND %(to)s
		  AND status != 'Cancelled'
		  AND docstatus < 2
		""",
		{"guards": tuple(candidates), "from": add_days(date_val, -1), "to": add_days(date_val, 1)},
		as_dict=True,
	)
	covered_names = {}
	cover_ids = {r.covering_for for r in rows if r.covering_for}
	if cover_ids:
		covered_names = dict(
			frappe.db.sql(
				"SELECT name, full_name FROM `tabSecurity Guard` WHERE name IN %(ids)s", {"ids": tuple(cover_ids)}
			)
		)

	busy = {}
	start, end = window
	for r in sorted(rows, key=lambda r: (r.start_date != date_val, r.start_date)):
		if r.external_guard in busy:
			continue
		same_day = getdate(r.start_date) == date_val
		if r.covering_for == off_guard and same_day:
			continue
		if r.covering_for and same_day:
			busy[r.external_guard] = _("Already covering {0} that day").format(
				covered_names.get(r.covering_for) or r.covering_for
			)
			continue
		r_start, r_end = _shift_window(r)
		if r_start < end and r_end > start:
			what = _("covering {0}").format(covered_names.get(r.covering_for) or r.covering_for) if r.covering_for else _("own shift")
			busy[r.external_guard] = _("On {0} {1} shift {2} {3}-{4} ({5})").format(
				r.farm or "", r.shift_type or "", frappe.utils.formatdate(r.start_date, "dd MMM"),
				_hhmm(r.start_time or "00:00:00"), _hhmm(r.end_time or "23:59:59"), what,
			).replace("  ", " ")
	return busy


def check_cover_available(cover_guard, off_guard, date_val, window):
	"""Why cover_guard can't cover off_guard on date_val, or None if they can."""
	guard = frappe.db.get_value("Security Guard", cover_guard, ["status", "full_name"], as_dict=True)
	if not guard:
		return _("Security Guard {0} not found").format(cover_guard)
	if cover_guard == off_guard:
		return _("A guard cannot cover their own day off")
	if guard.status != "Active":
		return _("{0} is not an active guard").format(guard.full_name or cover_guard)
	busy = busy_reasons([cover_guard], off_guard, date_val, window)
	if cover_guard in busy:
		return _("{0} is no longer free: {1}").format(guard.full_name or cover_guard, busy[cover_guard])
	return None


def _history(candidates, farm, date_val):
	"""{guard: {"farm_shifts", "by_shift": {shift_type: n}, "last_at_farm"}} at
	this farm. The 60 days run up to the cover date, or to today for a date
	still ahead - a shift not yet worked is not experience."""
	if not candidates or not farm:
		return {}
	until = min(getdate(date_val), getdate())
	since = add_days(until, -HISTORY_DAYS)
	rows = frappe.db.sql(
		"""
		SELECT external_guard, shift_type,
			SUM(start_date >= %(since)s) AS recent,
			MAX(start_date) AS last_date
		FROM `tabSecurity Guard Shift Assignment`
		WHERE farm = %(farm)s
		  AND start_date < %(until)s
		  AND security_guard = 'External Guard'
		  AND external_guard IN %(guards)s
		  AND status != 'Cancelled'
		  AND docstatus < 2
		GROUP BY external_guard, shift_type
		""",
		{"farm": farm, "since": since, "until": until, "guards": tuple(candidates)},
		as_dict=True,
	)
	out = {}
	for r in rows:
		h = out.setdefault(r.external_guard, {"farm_shifts": 0, "by_shift": {}, "last_at_farm": None})
		recent = int(r.recent or 0)
		h["farm_shifts"] += recent
		if recent:
			h["by_shift"][r.shift_type] = h["by_shift"].get(r.shift_type, 0) + recent
		if r.last_date and (not h["last_at_farm"] or r.last_date > h["last_at_farm"]):
			h["last_at_farm"] = r.last_date
	return out


def _on_off_day(candidates, date_val):
	if not candidates:
		return set()
	return set(
		frappe.db.sql_list(
			"""
			SELECT d.external_guard
			FROM `tabSecurity Guard Off Day` od
			JOIN `tabSecurity Guard Off Days` d ON d.name = od.parent
			WHERE od.parenttype = 'Security Guard Off Days'
			  AND od.off_date = %(date)s
			  AND d.external_guard IN %(guards)s
			""",
			{"date": getdate(date_val), "guards": tuple(candidates)},
		)
	)


def _reason(c, farm, shift_type, off_guard_name):
	parts = []
	if c["designated"]:
		parts.append(_("Designated reliever for {0}").format(off_guard_name))
	same = c["shift_type_shifts"]
	if same:
		parts.append(_("Worked {0} {1} shift {2}x in the last {3} days").format(farm, shift_type, same, HISTORY_DAYS))
		others = c["farm_shifts"] - same
		if others:
			parts.append(_("{0} other shift(s) there").format(others))
	elif c["farm_shifts"]:
		parts.append(
			_("Worked {0} {1}x in the last {2} days, none on {3} shift").format(farm, c["farm_shifts"], HISTORY_DAYS, shift_type)
		)
	elif c["last_at_farm"]:
		parts.append(_("Last worked at {0} on {1}").format(farm, frappe.utils.formatdate(c["last_at_farm"])))
	else:
		parts.append(_("No shifts at {0} on record; based at {1}").format(farm, c["home_farm"] or _("no farm")))
	if c["on_off_day"]:
		parts.append(_("on their own day off"))
	return "; ".join(parts)


def rank_relievers(guard, date, farm=None, shift_type=None, start_time=None, end_time=None, exclude=None):
	"""Every candidate for covering `guard` on `date`, best first (no limit).
	See suggest_relievers() for the shape and the ranking rules."""
	from upande_security.api.shift_schedule import _shift_hours, _usual_shift_type

	date_val = getdate(date)
	off = frappe.db.get_value("Security Guard", guard, ["name", "full_name", "farm", "company", "reliever"], as_dict=True)
	if not off:
		frappe.throw(_("Security Guard {0} not found").format(guard))
	farm = farm or off.farm
	shift_type = shift_type or _usual_shift_type(guard)
	t = _shift_hours(shift_type, start_time, end_time)
	window = cover_window(date_val, t.start_time, t.end_time)

	company = off.company or (frappe.db.get_value("Farm", farm, "company") if farm else None)
	filters = {"status": "Active", "name": ["!=", guard]}
	if company:
		filters["company"] = company
	excluded = set(_parse_list(exclude))
	guards = [
		g
		for g in frappe.get_all("Security Guard", filters=filters, fields=["name", "full_name", "farm"])
		if g.name not in excluded
	]
	ids = [g.name for g in guards]

	busy = busy_reasons(ids, guard, date_val, window)
	history = _history(ids, farm, date_val)
	off_days = _on_off_day(ids, date_val)

	out = []
	for g in guards:
		h = history.get(g.name) or {"farm_shifts": 0, "by_shift": {}, "last_at_farm": None}
		c = {
			"guard": g.name,
			"full_name": g.full_name or g.name,
			"home_farm": g.farm,
			"designated": 1 if off.reliever == g.name else 0,
			"available": 0 if g.name in busy else 1,
			"busy_reason": busy.get(g.name),
			"on_off_day": 1 if g.name in off_days else 0,
			"farm_shifts": h["farm_shifts"],
			"shift_type_shifts": h["by_shift"].get(shift_type, 0),
			"last_at_farm": h["last_at_farm"],
		}
		c["reason"] = _reason(c, farm, shift_type, off.full_name or guard)
		out.append(c)

	out.sort(
		key=lambda c: (
			-c["available"],
			-c["designated"],
			c["on_off_day"],
			-c["farm_shifts"],
			-c["shift_type_shifts"],
			-(c["last_at_farm"].toordinal() if c["last_at_farm"] else 0),
			c["home_farm"] != farm,
			c["full_name"],
		)
	)
	return frappe._dict(
		guard=guard,
		guard_name=off.full_name,
		date=str(date_val),
		farm=farm,
		shift_type=shift_type,
		start_time=_hhmm(t.start_time),
		end_time=_hhmm(t.end_time),
		window=window,
		designated_reliever=off.reliever,
		suggestions=out,
		counts={
			"candidates": len(out),
			"available": sum(c["available"] for c in out),
			"busy": sum(1 - c["available"] for c in out),
			"available_on_off_day": sum(1 for c in out if c["available"] and c["on_off_day"]),
		},
	)


@frappe.whitelist()
def suggest_relievers(guard, date, farm=None, shift_type=None, start_time=None, end_time=None, exclude=None, limit=None):
	"""Guards who could cover `guard`'s `shift_type` shift at `farm` on `date`.

	Candidates are the active External Guards of the off guard's company (the
	farm's when the guard has none), minus the off guard and `exclude` (a
	list, JSON list or comma-separated ids). Available first; within that:
	the off guard's designated reliever, then a guard on their own day off
	last, then shifts worked at this farm in the last 60 days, then shifts of
	this same shift type there, then most recent shift there, then guards
	based at this farm (some farms' shifts carry no farm). A guard on their
	own day off can still be picked - it is only labelled.

	Returns the cover shift, `counts` and up to `limit` (default 25)
	`suggestions`, each {guard, full_name, home_farm, designated, available,
	busy_reason, on_off_day, farm_shifts, shift_type_shifts, last_at_farm,
	reason}.
	"""
	require_planner()
	result = rank_relievers(guard, date, farm, shift_type, start_time, end_time, exclude)
	result.pop("window", None)
	limit = frappe.utils.cint(limit) or DEFAULT_LIMIT
	result["suggestions"] = result["suggestions"][:limit]
	return result
