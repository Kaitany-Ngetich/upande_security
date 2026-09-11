from __future__ import annotations

import calendar

import frappe
from frappe import _
from frappe.utils import cint, getdate

# The monthly schedule grid + reliever auto-fill is scoped to the 5 core
# farm units that actually have a real, sourced reliever roster (backfilled
# from the April 2026 off-duty sheet's own grouping - each farm+shift-band
# block there is exactly one guard posted as "Reliever" covering up to 6
# others). The "OTHER ASSIGNMENTS"/placeholder guards from that same import
# have no reliable reliever data, so they're deliberately left out here
# rather than guessed at.
CORE_FARMS = ["Torongo", "Simotwo", "Kaptumbo", "Kapkolia", "Chepsito"]


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


@frappe.whitelist()
def get_shift_schedule(year: str | int, month: str | int, farm: str | None = None) -> dict:
	"""Everything the schedule grid needs for one month, in one call: the
	guard list (scoped to the core units, optionally narrowed to one farm)
	and, for every guard x day in that month, whether they're on, off, or
	off-but-covered-by-their-reliever.
	"""
	year = cint(year)
	month = cint(month)
	start, end, last_day = _month_bounds(year, month)

	farms = [farm] if farm else CORE_FARMS

	guards = frappe.get_all(
		"Security Guard",
		filters={"farm": ["in", farms], "status": "Active", "post": ["is", "set"]},
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
		return {"guards": [], "days": list(range(1, last_day + 1)), "statuses": {}, "month": month, "year": year}

	rows = frappe.get_all(
		"Security Guard Shift Assignment",
		filters={
			"security_guard": "External Guard",
			"external_guard": ["in", guard_ids],
			"start_date": ["between", [start, end]],
		},
		fields=["name", "external_guard", "start_date", "shift_type", "covering_for"],
	)

	# Own-shift rows, keyed by (guard, day-of-month).
	own = {}
	# Reliever cover rows, keyed by (covered_guard, day-of-month) -> reliever id.
	covers = {}
	for r in rows:
		day = getdate(r.start_date).day
		if r.covering_for:
			covers[(r.covering_for, day)] = r.external_guard
		else:
			own[(r.external_guard, day)] = r.shift_type

	statuses: dict = {}
	for g in guards:
		day_map = {}
		for day in range(1, last_day + 1):
			key = (g.name, day)
			if key in own:
				day_map[day] = {"state": "on", "shift_type": own[key]}
			elif key in covers:
				cover_guard = covers[key]
				day_map[day] = {
					"state": "off_covered",
					"covered_by": cover_guard,
					"covered_by_name": reliever_names.get(cover_guard) or cover_guard,
				}
			else:
				day_map[day] = {"state": "off_unfilled" if g.reliever else "off_no_reliever"}
		statuses[g.name] = day_map

	return {
		"guards": guards,
		"days": list(range(1, last_day + 1)),
		"statuses": statuses,
		"month": month,
		"year": year,
	}


@frappe.whitelist()
def toggle_guard_day(guard: str, date: str, mark_off: str | int | bool) -> dict:
	"""Flip one guard's one day between on/off, handling the reliever
	fill-in (or its removal) as part of the same call so the grid never
	shows a half-applied state.
	"""
	mark_off = cint(mark_off)
	if not frappe.db.exists("Security Guard", guard):
		frappe.throw(_("Security Guard {0} not found").format(guard))

	guard_doc = frappe.db.get_value("Security Guard", guard, ["farm", "reliever", "full_name"], as_dict=True)
	date_val = getdate(date)

	if mark_off:
		# Remove the guard's own shift for that day, if any.
		existing = frappe.db.exists(
			"Security Guard Shift Assignment",
			{"security_guard": "External Guard", "external_guard": guard, "start_date": date_val, "covering_for": ["is", "not set"]},
		)
		if existing:
			frappe.delete_doc("Security Guard Shift Assignment", existing, ignore_permissions=True, force=True)

		if not guard_doc.reliever:
			frappe.db.commit()
			return {"state": "off_no_reliever"}

		# "Busy" means already covering a *different* guard that day - not
		# whether the reliever has their own baseline shift record for it.
		# Being on standby to cover is the reliever's actual job; it's only
		# a real conflict when two of their assigned guards are off the
		# same day (the "fill first, flag the rest" case).
		reliever_busy = frappe.db.exists(
			"Security Guard Shift Assignment",
			{"external_guard": guard_doc.reliever, "start_date": date_val, "covering_for": ["is", "set"]},
		)
		if reliever_busy:
			frappe.db.commit()
			return {"state": "off_unfilled", "reason": _("Reliever already assigned elsewhere that day")}

		shift_type = _usual_shift_type(guard)
		t = frappe.db.get_value(
			"Shift Type", "Day Guard Shift" if shift_type == "Day" else "Night Guard Shift",
			["start_time", "end_time"], as_dict=True,
		)
		remark = _("Covering {0}'s off day").format(guard_doc.full_name)

		# If the reliever already has their own baseline shift that day
		# (e.g. from the original roster import), tag that same row rather
		# than inserting a second one for the same person/date.
		own_row = frappe.db.exists(
			"Security Guard Shift Assignment",
			{"external_guard": guard_doc.reliever, "start_date": date_val, "covering_for": ["is", "not set"]},
		)
		if own_row:
			frappe.db.set_value(
				"Security Guard Shift Assignment", own_row,
				{"covering_for": guard, "farm": guard_doc.farm, "remarks": remark},
				update_modified=False,
			)
		else:
			cover = frappe.new_doc("Security Guard Shift Assignment")
			cover.security_guard = "External Guard"
			cover.external_guard = guard_doc.reliever
			cover.farm = guard_doc.farm
			cover.shift_type = shift_type
			cover.start_date = date_val
			cover.end_date = date_val
			cover.start_time = t.start_time
			cover.end_time = t.end_time
			cover.covering_for = guard
			cover.remarks = remark
			cover.insert(ignore_permissions=True)
		frappe.db.commit()
		reliever_name = frappe.db.get_value("Security Guard", guard_doc.reliever, "full_name")
		return {"state": "off_covered", "covered_by": guard_doc.reliever, "covered_by_name": reliever_name}

	# Marking back ON: undo any reliever cover row for this guard/day. Clear
	# the covering_for tag rather than deleting the row outright - it may be
	# the reliever's own pre-existing baseline record that got tagged when
	# the off day was filled, and deleting it would wipe that out along
	# with the cover.
	cover_row = frappe.db.get_value(
		"Security Guard Shift Assignment",
		{"covering_for": guard, "start_date": date_val},
		["name", "external_guard"],
		as_dict=True,
	)
	if cover_row:
		reliever_home_farm = frappe.db.get_value("Security Guard", cover_row.external_guard, "farm")
		frappe.db.set_value(
			"Security Guard Shift Assignment", cover_row.name,
			{"covering_for": None, "farm": reliever_home_farm, "remarks": ""},
			update_modified=False,
		)

	already_on = frappe.db.exists(
		"Security Guard Shift Assignment",
		{"security_guard": "External Guard", "external_guard": guard, "start_date": date_val, "covering_for": ["is", "not set"]},
	)
	if not already_on:
		shift_type = _usual_shift_type(guard)
		t = frappe.db.get_value(
			"Shift Type", "Day Guard Shift" if shift_type == "Day" else "Night Guard Shift",
			["start_time", "end_time"], as_dict=True,
		)
		doc = frappe.new_doc("Security Guard Shift Assignment")
		doc.security_guard = "External Guard"
		doc.external_guard = guard
		doc.farm = guard_doc.farm
		doc.shift_type = shift_type
		doc.start_date = date_val
		doc.end_date = date_val
		doc.start_time = t.start_time
		doc.end_time = t.end_time
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
	return {"state": "on"}
