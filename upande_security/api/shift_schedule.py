from __future__ import annotations

import calendar

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate

from upande_security.api.guard_off_days import add_guard_off_day, remove_guard_off_day

# The monthly schedule grid + reliever auto-fill covers every farm that has
# active guards with a post set: a guard with no post has no place on the
# roster grid, so that is what scopes it, not a list of farm names.

# Maps this doctype's own shift_type values to the HRMS Shift Type master
# record that actually holds the clock times. Day/Night are the original
# farm-wide 12h split; First/Second/Third are Chepsito's real 8h roster
# (MICROSA's own September 2026 roster, imported directly - see
# import_chepsito_september_roster.py). A plain "Day" if/else here used to
# silently resolve anything that wasn't literally "Day" to Night's hours -
# harmless while only two values existed, a real bug waiting to happen now
# that there are five.
SHIFT_TYPE_MASTER = {
	"Day": "Day Guard Shift",
	"Night": "Night Guard Shift",
	"First": "First Guard Shift",
	"Second": "Second Guard Shift",
	"Third": "Third Guard Shift",
}


def _shift_hours(shift_type, start_time=None, end_time=None):
	"""(start_time, end_time) for a shift: the given times if both are set
	(a Rotation Plan preview row carries its own), else the standard times
	in Security Ops Settings, else the HR Shift Type master. Throws a plain
	message instead of crashing when none of them has times."""
	from frappe.utils import to_timedelta

	from upande_security.api.shift_times import standard_times

	if not (start_time and end_time):
		start_time, end_time = standard_times(shift_type)
	if not (start_time and end_time) and SHIFT_TYPE_MASTER.get(shift_type):
		t = frappe.db.get_value(
			"Shift Type", SHIFT_TYPE_MASTER[shift_type], ["start_time", "end_time"], as_dict=True
		)
		if t:
			start_time, end_time = t.start_time, t.end_time
	if not (start_time and end_time):
		frappe.throw(
			_("No start and end time for the {0} shift. Set them under Security Ops Settings > Standard Shift Times.").format(
				shift_type
			)
		)
	return frappe._dict(start_time=to_timedelta(start_time), end_time=to_timedelta(end_time))


def _month_bounds(year: int, month: int) -> tuple[str, str, int]:
	last_day = calendar.monthrange(year, month)[1]
	start = f"{year:04d}-{month:02d}-01"
	end = f"{year:04d}-{month:02d}-{last_day:02d}"
	return start, end, last_day


def _usual_shift_type(guard: str) -> str:
	"""A guard's most common shift_type on file, so re-instating an off day
	(or a reliever's cover shift) picks a realistic Day/Night value instead
	of a fixed guess. Falls back to "Day" for a guard with no history at all.
	"""
	rows = frappe.db.sql(
		"""
		SELECT shift_type, COUNT(*) AS c
		FROM `tabSecurity Guard Shift Assignment`
		WHERE external_guard = %s AND security_guard = 'External Guard'
		GROUP BY shift_type
		ORDER BY c DESC
		LIMIT 1
		""",
		(guard,),
		as_dict=True,
	)
	return rows[0].shift_type if rows else "Day"


NO_COVER = ("", "none", "null")


def _cover_remark(full_name):
	"""Remark on a Shift Assignment created only to cover full_name's day off;
	release_cover() deletes rows carrying it."""
	return _("Covering {0}'s off day").format(full_name)


def release_cover(guard, date_val, guard_full_name):
	"""Undo the cover of guard's day off on date_val. A row created only for
	the cover is deleted; a reliever's own shift that was tagged as the cover
	(the designated-reliever path) keeps existing and is just untagged."""
	rows = frappe.get_all(
		"Security Guard Shift Assignment",
		filters={"covering_for": guard, "start_date": date_val},
		fields=["name", "external_guard", "remarks"],
	)
	for row in rows:
		if (row.remarks or "") == _cover_remark(guard_full_name):
			frappe.delete_doc("Security Guard Shift Assignment", row.name, ignore_permissions=True, force=True)
			continue
		reliever_home_farm = frappe.db.get_value("Security Guard", row.external_guard, "farm")
		frappe.db.set_value(
			"Security Guard Shift Assignment", row.name,
			{"covering_for": None, "farm": reliever_home_farm, "remarks": ""},
			update_modified=False,
		)


def _covered(cover_guard, reason=None):
	out = {
		"state": "off_covered",
		"covered_by": cover_guard,
		"covered_by_name": frappe.db.get_value("Security Guard", cover_guard, "full_name"),
	}
	if reason:
		out["reason"] = reason
	return out


def assign_cover(guard, guard_doc, date_val, cover_guard=None, shift_type=None, start_time=None, end_time=None):
	"""Cover guard's day off on date_val (already marked off) and return the
	day's state for the grid.

	cover_guard None: the guard's designated reliever, as the grid always
	did - their own shift that day is tagged as the cover, and they only
	count as busy when already covering someone else. cover_guard "" or
	"none": no cover. Any other value: that guard, checked free again here
	(no overlapping shift, not covering anyone else that day); a cover row
	is created for them. A cover already in place for someone else is
	replaced, but only once the new pick has been checked.
	"""
	from upande_security.api.relievers import check_cover_available, cover_window

	date_val = getdate(date_val)
	uncovered_state = "off_unfilled" if guard_doc.reliever else "off_no_reliever"
	designated = cover_guard is None
	if not designated and str(cover_guard).strip().lower() in NO_COVER:
		release_cover(guard, date_val, guard_doc.full_name)
		return {"state": uncovered_state, "reason": _("Left without cover")}

	chosen = guard_doc.reliever if designated else str(cover_guard).strip()
	if not chosen:
		return {"state": "off_no_reliever"}

	current = frappe.db.get_value(
		"Security Guard Shift Assignment",
		{"covering_for": guard, "start_date": date_val},
		["name", "external_guard"],
		as_dict=True,
	)
	if current and current.external_guard == chosen:
		return _covered(chosen)

	shift_type = shift_type or _usual_shift_type(guard)
	t = _shift_hours(shift_type, start_time, end_time)

	if designated:
		# "Busy" means already covering a *different* guard that day - not
		# whether the reliever has their own baseline shift record for it.
		# Being on standby to cover is the reliever's actual job; it's only
		# a real conflict when two of their assigned guards are off the
		# same day (the "fill first, flag the rest" case).
		reliever_busy = frappe.db.exists(
			"Security Guard Shift Assignment",
			{"external_guard": chosen, "start_date": date_val, "covering_for": ["is", "set"]},
		)
		if reliever_busy:
			return {"state": "off_unfilled", "reason": _("Reliever already assigned elsewhere that day")}
	else:
		reason = check_cover_available(chosen, guard, date_val, cover_window(date_val, t.start_time, t.end_time))
		if reason:
			if current:
				return _covered(current.external_guard, reason=reason)
			return {"state": "off_unfilled", "reason": reason}

	if current:
		release_cover(guard, date_val, guard_doc.full_name)

	# Overnight shift (e.g. Night: 18:00 -> 06:00) ends the calendar day
	# AFTER it starts - otherwise the record's own end sits before its
	# start on the same day, and derive_status() jumps straight from
	# Scheduled to Ended without ever reading Active for the actual
	# overnight window. Mirrors sync_shifts_from_hr_roster()'s same rule.
	cover_end_date = add_days(date_val, 1) if t.end_time <= t.start_time else date_val

	# The designated reliever's own baseline shift that day (e.g. from the
	# original roster import) is tagged rather than a second row inserted
	# for the same person/date. A picked guard is free by then, so any
	# shift of theirs that day is a different one and a new row is right.
	own_row = None
	if designated:
		own_row = frappe.db.exists(
			"Security Guard Shift Assignment",
			{"external_guard": chosen, "start_date": date_val, "covering_for": ["is", "not set"]},
		)
	if own_row:
		# Also correct end_date here, in case this baseline row predates
		# the overnight-rollover fix and still has the old same-day shape.
		frappe.db.set_value(
			"Security Guard Shift Assignment", own_row,
			{
				"covering_for": guard,
				"farm": guard_doc.farm,
				"remarks": _("Covering {0}'s off day on their own shift").format(guard_doc.full_name),
				"end_date": cover_end_date,
			},
			update_modified=False,
		)
	else:
		cover = frappe.new_doc("Security Guard Shift Assignment")
		cover.security_guard = "External Guard"
		cover.external_guard = chosen
		cover.farm = guard_doc.farm
		cover.shift_type = shift_type
		cover.start_date = date_val
		cover.end_date = cover_end_date
		cover.start_time = t.start_time
		cover.end_time = t.end_time
		cover.covering_for = guard
		cover.remarks = _cover_remark(guard_doc.full_name)
		cover.insert(ignore_permissions=True)
	return _covered(chosen)


@frappe.whitelist()
def get_shift_schedule(year: str | int, month: str | int, farm: str | None = None) -> dict:
	"""Everything the schedule grid needs for one month, in one call: the
	guard list (every rostered farm, optionally narrowed to one farm), the
	farms to choose from
	and, for every guard x day in that month, whether they're on, off, or
	off-but-covered-by-their-reliever.
	"""
	year = cint(year)
	month = cint(month)
	start, end, last_day = _month_bounds(year, month)

	rostered = {"status": "Active", "post": ["is", "set"], "farm": ["is", "set"]}
	farms = sorted(set(frappe.get_all("Security Guard", filters=rostered, pluck="farm")))

	guards = frappe.get_all(
		"Security Guard",
		filters={**rostered, "farm": farm} if farm else rostered,
		fields=["name", "full_name", "farm", "post", "reliever"],
		order_by="farm asc, post asc, full_name asc",
	)
	reliever_names = {}
	reliever_ids = {g.reliever for g in guards if g.reliever}
	if reliever_ids:
		reliever_names = dict(
			frappe.db.sql(
				"SELECT name, full_name FROM `tabSecurity Guard` WHERE name IN %(ids)s",
				{"ids": tuple(reliever_ids)},
			)
		)
	for g in guards:
		g["reliever_name"] = reliever_names.get(g.reliever) if g.reliever else None

	guard_ids = [g.name for g in guards]
	if not guard_ids:
		return {"guards": [], "farms": farms, "days": list(range(1, last_day + 1)), "statuses": {}, "month": month, "year": year}

	# A reliever legitimately covers guards posted on a DIFFERENT farm - the
	# roster data has real examples of this. Filtering rows
	# to guard_ids alone (this view's own farm scope) would silently drop a
	# cover row whenever its reliever's own farm falls outside that scope,
	# making a covered guard falsely read "off_unfilled" the moment a Head
	# narrows the grid to one farm. covering_for is the guard actually being
	# rendered here, so it's the field that must be in guard_ids - the cover
	# row's own external_guard (the reliever) doesn't have to be.
	guard_ids_set = tuple(guard_ids)
	rows = frappe.db.sql(
		"""
		SELECT name, external_guard, start_date, shift_type, covering_for
		FROM `tabSecurity Guard Shift Assignment`
		WHERE security_guard = 'External Guard'
		  AND start_date BETWEEN %(start)s AND %(end)s
		  AND (external_guard IN %(guard_ids)s OR covering_for IN %(guard_ids)s)
		""",
		{"start": start, "end": end, "guard_ids": guard_ids_set},
		as_dict=True,
	)

	# Security Guard Off Days is autonamed field:external_guard, so its child
	# rows' own "parent" IS the guard's id directly - no join needed. This is
	# a separate, guard-owned off-day list (also what Rotation Plan's
	# generate_preview() skips) - cross-referencing it here so the grid marks
	# a guard's OFFICIALLY configured off days distinctly from a day that's
	# merely unstaffed. External Guard only, same as everything else this
	# endpoint touches - Internal Guards have no Security Guard Off Days
	# record at all (HR owns their leave/rostering).
	off_day_rows = frappe.get_all(
		"Security Guard Off Day",
		filters={"parent": ["in", guard_ids], "off_date": ["between", [start, end]]},
		fields=["parent", "off_date"],
	)
	configured_off_days = {(r.parent, getdate(r.off_date).day) for r in off_day_rows}

	# Own-shift rows, keyed by (guard, day-of-month).
	own = {}
	# Reliever cover rows, keyed by (covered_guard, day-of-month) -> reliever id.
	covers = {}
	for r in rows:
		day = getdate(r.start_date).day
		# A cover row is a genuine, physical shift for its own external_guard
		# (the reliever) too - if that reliever also happens to be one of
		# the guards this view is showing, their own cell for that day
		# should read "on" (they're working, covering someone), not fall
		# through to "off" for lack of a plain own-duty row.
		own[(r.external_guard, day)] = r.shift_type
		if r.covering_for:
			covers[(r.covering_for, day)] = r.external_guard

	# A cover can be any guard picked from suggest_relievers, not only a
	# designated reliever, so their names are looked up here too.
	missing = {c for c in covers.values() if c not in reliever_names}
	if missing:
		reliever_names.update(
			frappe.db.sql(
				"SELECT name, full_name FROM `tabSecurity Guard` WHERE name IN %(ids)s",
				{"ids": tuple(missing)},
			)
		)

	statuses: dict = {}
	for g in guards:
		day_map = {}
		for day in range(1, last_day + 1):
			key = (g.name, day)
			is_off_day = key in configured_off_days
			if key in own:
				day_map[day] = {"state": "on", "shift_type": own[key], "is_off_day": is_off_day}
			elif key in covers:
				cover_guard = covers[key]
				day_map[day] = {
					"state": "off_covered",
					"covered_by": cover_guard,
					"covered_by_name": reliever_names.get(cover_guard) or cover_guard,
					"is_off_day": is_off_day,
				}
			else:
				day_map[day] = {
					"state": "off_unfilled" if g.reliever else "off_no_reliever",
					"is_off_day": is_off_day,
				}
		statuses[g.name] = day_map

	return {
		"guards": guards,
		"farms": farms,
		"days": list(range(1, last_day + 1)),
		"statuses": statuses,
		"month": month,
		"year": year,
	}


@frappe.whitelist()
def toggle_guard_day(
	guard: str,
	date: str,
	mark_off: str | int | bool,
	farm: str | None = None,
	shift_type: str | None = None,
	start_time: str | None = None,
	end_time: str | None = None,
	create_shift: str | int | bool = 1,
	cover_guard: str | None = None,
) -> dict:
	"""Flip one guard's one day between on/off, handling the reliever
	fill-in (or its removal) as part of the same call so the grid never
	shows a half-applied state.

	farm overrides the guard's own home farm for the Shift Assignment(s)
	this call creates/updates - the Shift Schedule grid never passes it (a
	guard's own home farm is always right there), but a Rotation Plan can
	rotate a guard across multiple farms on different days, so
	toggle_preview_row_off_day() on Security Guard Rotation Plan passes the
	specific day's own farm instead of falling back to wherever the guard
	is normally posted.

	shift_type / start_time / end_time give the shift to put back when a day
	is marked on again (a rotation's preview row knows that day's shift);
	without them the guard's usual shift and its standard times are used.
	create_shift=0 marks the day on without creating a Shift Assignment -
	for a Draft rotation plan, whose Apply step creates it.

	cover_guard picks who covers the day off (from suggest_relievers); ""
	or "none" leaves it without cover. Not passed, the guard's designated
	reliever covers it, as before. A picked guard who is no longer free
	returns state "off_unfilled" with the reason.
	"""
	from upande_security.api.relievers import require_planner

	# Marking days off and booking covers is planning work: refuse logins
	# that cannot write Shift Assignments (guards).
	require_planner()
	mark_off = cint(mark_off)
	if not frappe.db.exists("Security Guard", guard):
		frappe.throw(_("Security Guard {0} not found").format(guard))

	guard_doc = frappe.db.get_value("Security Guard", guard, ["farm", "reliever", "full_name"], as_dict=True)
	if farm:
		guard_doc.farm = farm
	date_val = getdate(date)

	if mark_off:
		# Remove the guard's own shift for that day, if any.
		existing = frappe.db.exists(
			"Security Guard Shift Assignment",
			{"security_guard": "External Guard", "external_guard": guard, "start_date": date_val, "covering_for": ["is", "not set"]},
		)
		if existing:
			frappe.delete_doc("Security Guard Shift Assignment", existing, ignore_permissions=True, force=True)

		# Record this as one of the guard's own configured off days - the
		# same list Rotation Plan's generate_preview() already skips - so a
		# day marked off here is an "official" off day everywhere else on
		# this guard, not just a gap in this one month's grid.
		add_guard_off_day(guard, date_val, remarks=_("Marked off via Shift Schedule"))

		result = assign_cover(guard, guard_doc, date_val, cover_guard, shift_type, start_time, end_time)
		frappe.db.commit()
		return result

	# Marking back ON: this day is no longer one of the guard's configured
	# off days either - undo the same list add_guard_off_day() made above.
	remove_guard_off_day(guard, date_val)

	# Undo any reliever cover for this guard/day (see release_cover).
	release_cover(guard, date_val, guard_doc.full_name)

	already_on = frappe.db.exists(
		"Security Guard Shift Assignment",
		{"security_guard": "External Guard", "external_guard": guard, "start_date": date_val, "covering_for": ["is", "not set"]},
	)
	if not already_on and cint(create_shift):
		shift_type = shift_type or _usual_shift_type(guard)
		t = _shift_hours(shift_type, start_time, end_time)
		doc = frappe.new_doc("Security Guard Shift Assignment")
		doc.security_guard = "External Guard"
		doc.external_guard = guard
		doc.farm = guard_doc.farm
		doc.shift_type = shift_type
		doc.start_date = date_val
		doc.end_date = add_days(date_val, 1) if t.end_time <= t.start_time else date_val
		doc.start_time = t.start_time
		doc.end_time = t.end_time
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
	return {"state": "on"}
