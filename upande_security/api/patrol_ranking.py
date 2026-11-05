# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Guard ranking for the Security Dashboard's Patrols tab.

For every guard who patrolled a farm in a period: distance walked, how much
of the farm their GPS points reached, time spent patrolling, number of
patrols and checkpoint scans - and a score that ranks the guards of one farm
against each other.

WHERE THE WORK HAPPENS
A month across every farm is ~1.5M GPS points on live. None of them come
back to Python. One query per farm, through the (farm, captured_at) index,
walks that farm's points once and returns one row per (guard, coverage
cell) the guard touched: the segment distance and time summed into it by a
window function (LAG over each patrol), and the number of patrols started.
That is a few thousand small rows at most, however long the period. The
grid itself is patrol_coverage's own (same cell size from Security Ops
Settings, same clipping to the boundary), computed once per farm and cached.

WHICH POINTS COUNT
- Saved under the farm (the guard's rostered farm), On Duty excluded -
  standing at a post is not patrolling.
- The map's point rule (patrol_rules): positions that do not parse, sit
  outside -90..90 / -180..180 or at (0, 0) dropped; fixes worse than
  MAX_ACCURACY_M dropped, as the map and coverage do.
- With Hide Patrol Points Outside Farm Boundary on, only points inside the
  boundary's box grown by Boundary Tolerance (a box, not the exact outline,
  so it stays an index-friendly range test; coverage itself only counts
  cells inside the boundary).
- A step between two fixes of the same patrol counts towards distance and
  time only when the fixes are at most MAX_GAP_S apart and the implied
  speed is at most MAX_SPEED_KMH: longer gaps are the phone asleep, faster
  steps are GPS jumps. Neither is patrolling. The same step rule
  (patrol_rules) sums the Patrol Map's and the app report's distance.
"""

import datetime
import hashlib
import json
import math

import frappe
from frappe import _

from upande_security.api.feature_flags import is_feature_enabled
from upande_security.api.patrol_coverage import (
	MAX_ACCURACY_M,
	_build_cells,
	_coverage_settings,
	_load_farm_polygon,
)
from upande_security.api.patrol_rules import (
	MAX_GAP_S,
	MAX_SPEED_KMH,
	POINT_WHERE_SQL,
	RULES_VERSION,
	STEP_COUNTS_SQL,
	sql_params,
	step_sql,
)

# Share of the score each measure carries. Every measure is first scaled
# against the best guard on the same farm in the same period (best = 1), so
# a small farm's guards are not ranked down for walking less than a big
# farm's. Without checkpoint scans on a farm in the period their share goes
# to the other two (NO_SCAN_WEIGHTS); without a usable boundary coverage
# cannot be measured and distance carries the score with scans.
# "safety" is the guard's scored incidents per shift on the farm (fewer is
# better): full marks for none, zero for the farm's worst rate.
WEIGHTS = {"coverage": 0.4, "distance": 0.25, "scans": 0.15, "safety": 0.2}
NO_SCAN_WEIGHTS = {"coverage": 0.5, "distance": 0.3, "scans": 0.0, "safety": 0.2}
NO_COVERAGE_WEIGHTS = {"coverage": 0.0, "distance": 0.5, "scans": 0.3, "safety": 0.2}
DISTANCE_ONLY = {"coverage": 0.0, "distance": 0.8, "scans": 0.0, "safety": 0.2}
# Incident types left out of the safety score: alerts, health and conduct
# matters rather than a lapse in site security. They are still listed.
UNSCORED_INCIDENT_TYPES = ("SOS", "Near Miss", "Medical Emergency", "Accident", "Violation of Company Policy")

PERIODS = ("today", "yesterday", "this_week", "last_week", "this_month", "last_month", "custom")
DEFAULT_DAY_START = datetime.time(6, 0)

# Each day's figures are kept once worked out. A day more than two days
# back is settled (a phone that was offline has uploaded by then) and is
# kept for a month; today and yesterday for a few minutes.
_TTL_RECENT_S = 300
_TTL_SETTLED_S = 31 * 86400


def day_start():
	"""When a security day starts - Security Ops Settings > Security Day
	Starts At, 06:00 unless a site changes it. Every period runs from this
	time to the same time, so a night shift is one day, not two halves."""
	value = frappe.db.get_single_value("Security Ops Settings", "security_day_starts_at")
	try:
		return frappe.utils.get_time(value) if value else DEFAULT_DAY_START
	except Exception:
		return DEFAULT_DAY_START


def security_today(now=None):
	"""The security day it is now: before the day start, still yesterday."""
	now = now or frappe.utils.now_datetime()
	d = now.date()
	return d - datetime.timedelta(days=1) if now.time() < day_start() else d


def resolve_period(period=None, from_date=None, to_date=None, today=None):
	"""(first day, last day) of the named period, in security days. Weeks
	start on Monday."""
	today = today or security_today()
	if period == "custom" and from_date and to_date:
		a, b = frappe.utils.getdate(from_date), frappe.utils.getdate(to_date)
		return (a, b) if a <= b else (b, a)
	if period == "today":
		return today, today
	if period == "yesterday":
		y = frappe.utils.add_days(today, -1)
		return y, y
	monday = frappe.utils.add_days(today, -today.weekday())
	if period == "last_week":
		return frappe.utils.add_days(monday, -7), frappe.utils.add_days(monday, -1)
	first = today.replace(day=1)
	if period == "this_month":
		return first, today
	if period == "last_month":
		last = frappe.utils.add_days(first, -1)
		return last.replace(day=1), last
	return monday, today


def resolve_window(period=None, from_date=None, to_date=None):
	"""(first day, last day, start, end): the period's security days and the
	moments they run between - first day at the day start up to the day
	after the last at the day start, or now if that is still to come."""
	first, last = resolve_period(period, from_date, to_date)
	t = day_start()
	start = datetime.datetime.combine(first, t)
	end = datetime.datetime.combine(frappe.utils.add_days(last, 1), t)
	return first, last, start, min(end, frappe.utils.now_datetime().replace(microsecond=0))


def window_label(start, end):
	"""4 Nov 2026 06:00 to 5 Nov 2026 06:00 (or "to now")."""
	fmt = lambda d: frappe.utils.format_datetime(d, "d MMM yyyy HH:mm")
	now = frappe.utils.now_datetime()
	return fmt(start) + " to " + ("now" if (now - end).total_seconds() < 120 else fmt(end))


def _merge(st, d):
	"""Add one piece of a guard's figures (a cached day, or a part day
	worked out live) to their running total."""
	st["points"] += d["points"]
	st["metres"] += d["metres"]
	st["seconds"] += d["seconds"]
	st["patrol_ids"].update(d["patrols"] if "patrols" in d and not isinstance(d["patrols"], int) else d.get("patrol_ids") or ())
	st["cells"].update(d["cells"])
	for key, pick in (("first", min), ("last", max)):
		v = str(d[key]) if d.get(key) else None
		st[key] = pick(filter(None, [st[key], v]), default=None)


def _window_stats(ctx, start, end, in_scope):
	"""{(farm, guard): stats} for start <= time < end. Whole calendar days
	inside the window come from the day cache; the part days at either end
	are worked out live."""
	stats = {}
	d = start.date()
	while datetime.datetime.combine(d, datetime.time.min) < end:
		day_from = datetime.datetime.combine(d, datetime.time.min)
		day_to = day_from + datetime.timedelta(days=1)
		a, b = max(start, day_from), min(end, day_to)
		if a == day_from and b == day_to:
			pieces = ((tuple(k.split("\x1f", 1)), v) for k, v in _day_stats(d, ctx).items())
		elif a < b:
			pieces = _guard_stats(ctx["geos"], str(a), str(b - datetime.timedelta(seconds=1)), ctx["boundary_on"]).items()
		else:
			pieces = ()
		for (f, gid), piece in pieces:
			if f not in in_scope:
				continue
			st = stats.get((f, gid))
			if st is None:
				st = stats[(f, gid)] = _empty_stats(piece["kind"])
			_merge(st, piece)
		d = d + datetime.timedelta(days=1)
	return stats


@frappe.whitelist()
def get_guard_ranking(period="this_week", from_date=None, to_date=None, farm=None, company=None):
	"""Per-guard patrol metrics and ranking for a period, per farm.

	`farm` narrows to one farm; otherwise `company`'s farms, otherwise every
	farm the user may read. Guards are ranked within each farm."""
	if not frappe.has_permission("Patrol GPS Log", ptype="read"):
		frappe.throw(_("You do not have permission to view Patrol GPS Logs."), frappe.PermissionError)

	period = period if period in PERIODS else "this_week"
	first, last, start, end = resolve_window(period, from_date, to_date)
	if frappe.utils.date_diff(last, first) > 92:
		frappe.throw(_("Pick a period of three months or less."))

	filters = {}
	if farm:
		filters["name"] = farm
	elif company:
		filters["company"] = company
	# get_list, so a user limited to some farms only ranks those.
	farms = frappe.get_list("Farm", filters=filters, pluck="name", order_by="name asc", limit_page_length=0)
	in_scope = set(farms)

	ctx = _context()
	geos = ctx["geos"]
	has_scans = frappe.db.table_exists("Checkpoint Scan Log")

	stats = _window_stats(ctx, start, end, in_scope)
	for st in stats.values():
		st["patrols"] = len(st["patrol_ids"])

	if has_scans and farms:
		for (f, gid), sc in _scans(farms, str(start), str(end - datetime.timedelta(seconds=1))).items():
			st = stats.get((f, gid))
			if st is None:
				st = stats[(f, gid)] = _empty_stats(sc["kind"])
			st["scans"] = sc["scans"]
			st["valid_scans"] = sc["valid"]

	# Incidents during each guard's shifts: context next to the patrol
	# figures (not part of the score). A guard on duty when something
	# happened is listed even with no patrol points.
	shift_inc = _shift_incidents(farms, start, end) if farms else {}
	for (f, gid), si in shift_inc.items():
		if (f, gid) not in stats and si["incidents"]:
			st = stats[(f, gid)] = _empty_stats(si["kind"])
			st["patrols"] = 0

	rows, farm_info = [], []
	for geo in geos:
		f = geo["farm"]
		if f not in in_scope:
			continue
		guards = {gid: st for (ff, gid), st in stats.items() if ff == f}
		if not guards:
			continue
		ranked, weights, farm_cov = _rank(f, guards, geo["grid"], shift_inc)
		# Area in hectares: the farm's from its boundary, each guard's (and
		# the farm's covered part) as their coverage share of it, so the
		# hectares always agree with the percentages beside them.
		farm_ha = _farm_hectares(geo) if geo["grid"] else None
		for r in ranked:
			r["area_ha"] = round(farm_ha * r["coverage_pct"] / 100, 2) if farm_ha and r["coverage_pct"] is not None else None
		rows += ranked
		farm_info.append({
			"farm": f,
			"guards": len(ranked),
			"cells": geo["grid"]["cells"] if geo["grid"] else None,
			"coverage_pct": farm_cov,
			"weights": weights,
			# Totals for the farm. Distance, time, patrols and scans add up
			# across guards; area does not (two guards in the same cell cover
			# it once), so covered_ha is everyone's cells together.
			"area_ha": round(farm_ha, 2) if farm_ha else None,
			"covered_ha": round(farm_ha * farm_cov / 100, 2) if farm_ha and farm_cov is not None else None,
			"distance_km": round(sum(r["distance_km"] for r in ranked), 2),
			"patrol_hours": round(sum(r["patrol_hours"] for r in ranked), 2),
			"patrols": sum(r["patrols"] for r in ranked),
			"scans": sum(r["scans"] for r in ranked),
			"valid_scans": sum(r["valid_scans"] for r in ranked),
		})

	names = _guard_names([(r["kind"], r["guard"]) for r in rows])
	for r in rows:
		r["name"] = names.get(r["guard"]) or r["guard"]
		si = shift_inc.get((r["farm"], r["guard"])) or {}
		inc = si.get("incidents") or []
		r["shifts"] = si.get("shifts", 0)
		r["incidents"] = len(inc)
		r["incidents_scored"] = sum(1 for i in inc if i["scored"])
		r["incidents_serious"] = sum(1 for i in inc if i["scored"] and i["severity"] in SERIOUS_SEVERITIES)
		r["incident_list"] = inc[:20]

	return {
		"period": period,
		"from_date": str(first),
		"to_date": str(last),
		"start": str(start),
		"end": str(end),
		"window_label": window_label(start, end),
		"day_start": day_start().strftime("%H:%M"),
		"cell_width_m": ctx["width"],
		"cell_height_m": ctx["height"],
		"weights": WEIGHTS,
		"no_scan_weights": NO_SCAN_WEIGHTS,
		"max_gap_s": MAX_GAP_S,
		"max_speed_kmh": MAX_SPEED_KMH,
		"checkpoints": has_scans,
		"incidents_in_score": True,
		"unscored_incident_types": list(UNSCORED_INCIDENT_TYPES),
		"farms": farm_info,
		"rows": rows,
	}


def _digest(text, length):
	"""Stable short hash for cache keys - not frappe.generate_hash, which
	ignores its text and returns a random string."""
	return hashlib.sha1(text.encode()).hexdigest()[:length]


def _empty_stats(kind):
	return {"kind": kind, "points": 0, "metres": 0.0, "seconds": 0, "patrols": 0, "patrol_ids": set(),
			"cells": set(), "first": None, "last": None, "scans": 0, "valid_scans": 0}


def _context():
	"""Settings and farm boundaries every day's figures depend on, and a
	short hash of them that keys the day cache - change a boundary, the
	cell size, the tolerance or the boundary flag and every day is worked
	out afresh.

	Which farm a point belongs to depends on every farm's boundary (where
	two overlap the smaller takes it), so days are worked out for all farms
	and narrowed to the scope afterwards - which also lets one cached day
	serve every scope and every user."""
	width, height = _coverage_settings()[:2]
	boundary_on = is_feature_enabled("feature_patrol_boundary_filter")
	tol = frappe.db.get_single_value("Security Ops Settings", "coverage_boundary_tolerance_m")
	tol = 5 if tol is None else max(0, int(tol))
	geos = [_farm_geo(f, width, height, tol) for f in frappe.get_all("Farm", pluck="name", order_by="name asc")]
	config = _digest(json.dumps(
		[[g["farm"], g["key"]] for g in geos] + [boundary_on, MAX_ACCURACY_M, MAX_GAP_S, MAX_SPEED_KMH, RULES_VERSION]
	), 12)
	return {"width": width, "height": height, "boundary_on": boundary_on, "geos": geos, "config": config}


def warm_ranking_days():
	"""Nightly (hooks: daily_long): work out the settled days of the last
	six weeks that are not cached yet, so This/Last week and This/Last
	month only ever read today and yesterday live. After a deploy or a
	boundary change the first run fills all of them; later runs add one."""
	ctx = _context()
	today = frappe.utils.getdate()
	for back in range(42, 1, -1):
		day = frappe.utils.add_days(today, -back)
		if frappe.cache.get_value(_day_key(day, ctx)) is None:
			_day_stats(day, ctx)


def _day_key(day, ctx):
	return f"upande_security:ranking_day:{ctx['config']}:{frappe.utils.getdate(day)}"


def _day_stats(day, ctx):
	"""{"farm\\x1fguard": {kind, points, metres, seconds, patrols, cells,
	first, last}} for one calendar day, every farm - from the cache when
	this day was worked out before under the same boundaries and settings.

	A period is put together from days so the expensive part is paid once
	per day, not once per request: "This month" re-read every day of the
	month on every click otherwise. Patrols are kept as ids, not counts, so
	a night patrol across midnight is still one patrol; the one step that
	crosses midnight is the only thing lost by the split."""
	day = frappe.utils.getdate(day)
	key = _day_key(day, ctx)
	cached = frappe.cache.get_value(key)
	if cached is not None:
		return cached
	raw = _guard_stats(ctx["geos"], f"{day} 00:00:00", f"{day} 23:59:59", ctx["boundary_on"])
	out = {
		f + "\x1f" + g: {
			"kind": s["kind"],
			"points": s["points"],
			"metres": round(s["metres"], 1),
			"seconds": s["seconds"],
			"patrols": sorted(s["patrol_ids"]),
			"cells": sorted(s["cells"]),
			"first": str(s["first"]) if s["first"] else None,
			"last": str(s["last"]) if s["last"] else None,
		}
		for (f, g), s in raw.items()
	}
	settled = (frappe.utils.getdate() - day).days >= 2
	frappe.cache.set_value(key, out, expires_in_sec=_TTL_SETTLED_S if settled else _TTL_RECENT_S)
	return out


def _farm_geo(farm, width, height, tol_m):
	"""What the queries need to know about a farm's boundary, built once and
	cached until the farm, the cell size or the tolerance changes:

	- grid: the coverage grid's cell keys and how to bin a point into them
	  (patrol_coverage._build_cells), or None without a usable boundary or
	  when the farm is too large for a grid;
	- on / off: the area points are picked from, as WKT plus its bounding
	  box - "on" is the boundary grown by Boundary Tolerance (the Hide Patrol
	  Points Outside Farm Boundary rule), "off" the boundary grown by ~110 m
	  (where the map still takes untagged points). Simplified to ~1 m so the
	  database's point-in-polygon test stays cheap.
	"""
	modified = frappe.db.get_value("Farm", farm, "modified")
	key = "upande_security:ranking_geo:" + _digest(
		json.dumps([farm, str(modified), width, height, tol_m]), 20
	)
	cached = frappe.cache.get_value(key)
	if cached:
		return cached
	geo = {"farm": farm, "key": key, "grid": None, "on": None, "off": None, "area": 0}
	try:
		poly = _load_farm_polygon(farm)
	except Exception:
		poly = None
	if poly is not None:
		geo["area"] = poly.area

		def area(shape_):
			shape_ = shape_.simplify(0.00001, preserve_topology=True)
			return {"wkt": shape_.wkt, "bbox": list(shape_.bounds)}

		geo["on"] = area(poly.buffer(tol_m / 111320.0) if tol_m else poly)
		geo["off"] = area(poly.buffer(0.001))
		cells, g = _build_cells(poly, width, height)
		if cells:
			geo["grid"] = {
				**g,
				"cells": len(cells),
				# "i-j" strings: the cache holds JSON-like data, no tuples.
				"keys": sorted(f"{i}-{j}" for i, j in cells),
			}
	frappe.cache.set_value(key, geo, expires_in_sec=7 * 86400)
	return geo


_GUARD_SQL = (
	"case when personel = 'Internal Guard' and ifnull(internal_guard, '') != '' then internal_guard"
	" when ifnull(external_guard, '') != '' then external_guard end"
)
_KIND_SQL = (
	"case when personel = 'Internal Guard' and ifnull(internal_guard, '') != '' then 'Internal Guard'"
	" when ifnull(external_guard, '') != '' then 'External Guard' end"
)
_POINT_WHERE = [
	"captured_at between %(start)s and %(end)s",
	"ifnull(tracking_mode, 'Patrol') != 'On Duty'",
] + POINT_WHERE_SQL


def _guard_stats(geos, start, end, boundary_on):
	"""{(farm, guard id): stats} for every farm in `geos`, from one query.

	Which farm a point counts for follows the Patrol Map (fetchPatrolData /
	patrol_playback.farm_points):
	- boundary flag on: the farm whose boundary (grown by the tolerance)
	  holds the point, whatever farm it was saved under; a farm with no
	  boundary keeps the points saved under it;
	- flag off: the farm the point was saved under, plus untagged points
	  within ~110 m of a farm's boundary.
	Where farms' areas overlap, the smaller farm takes the point.

	The located points are read in one pass over the window through the
	captured_at covering index - the bounding boxes and the accuracy and
	mode tests are answered from the index, so only points inside a farm
	are read from the table. Saved-farm points come through
	(farm, captured_at). See the module docstring for the rest."""
	params = {"start": start, "end": end, **sql_params()}
	shaped = sorted((g for g in geos if g.get("on" if boundary_on else "off")), key=lambda g: g["area"])
	if boundary_on:
		saved_farms = [g["farm"] for g in geos if not g.get("on")]
	else:
		saved_farms = [g["farm"] for g in geos]

	cols = (
		f"{_GUARD_SQL} as g, {_KIND_SQL} as kind, ifnull(patrol, '') as patrol,"
		" captured_at, latitude + 0 as lat, longitude + 0 as lng"
	)
	branches = []
	if shaped:
		boxes, cases = [], []
		for n, g in enumerate(shaped):
			a = g["on" if boundary_on else "off"]
			x0, y0, x1, y1 = a["bbox"]
			params.update({f"x0_{n}": x0, f"y0_{n}": y0, f"x1_{n}": x1, f"y1_{n}": y1, f"wkt_{n}": a["wkt"], f"farm_{n}": g["farm"]})
			box = (
				f"(latitude + 0 between %(y0_{n})s and %(y1_{n})s"
				f" and longitude + 0 between %(x0_{n})s and %(x1_{n})s)"
			)
			boxes.append(box)
			cases.append(
				f"when {box} and st_contains(st_geomfromtext(%(wkt_{n})s), point(longitude + 0, latitude + 0))"
				f" then %(farm_{n})s"
			)
		where = list(_POINT_WHERE) + ["(" + " or ".join(boxes) + ")"]
		if not boundary_on:
			where.append("ifnull(farm, '') = ''")
		force = _force_index("captured_at_coverage_mode")
		branches.append(
			f"select * from (select case {' '.join(cases)} end as farm_hit, {cols}"
			f" from `tabPatrol GPS Log`{force} where {' and '.join(where)}) located"
			" where farm_hit is not null"
		)
	if saved_farms:
		params["saved_farms"] = tuple(saved_farms)
		where = list(_POINT_WHERE) + ["farm in %(saved_farms)s"]
		force = _force_index("farm_captured_at")
		branches.append(f"select farm as farm_hit, {cols} from `tabPatrol GPS Log`{force} where {' and '.join(where)}")
	if not branches:
		return {}

	cell_cases = []
	for n, g in enumerate(geos):
		grid = g.get("grid")
		if not grid:
			continue
		params.update({f"cf_{n}": g["farm"], f"mx_{n}": grid["minx"], f"my_{n}": grid["miny"], f"dx_{n}": grid["dx"], f"dy_{n}": grid["dy"]})
		cell_cases.append(
			f"when %(cf_{n})s then concat(floor((lng - %(mx_{n})s) / %(dx_{n})s), '-', floor((lat - %(my_{n})s) / %(dy_{n})s))"
		)
	cell_sql = f"case farm_hit {' '.join(cell_cases)} end" if cell_cases else "null"

	step_secs, step_metres = step_sql("w")
	# Innermost: the points with the farm each counts for. Middle: each fix
	# with the step from the previous fix of the same guard's same patrol on
	# the same farm. Outer: summed per (farm, guard, cell) - a step is
	# credited to the cell it ends in, and a partition's first fix (no
	# previous step) marks one patrol.
	sql = f"""
		select farm_hit, g, kind, cell,
			count(*) as points,
			sum(if(ok, metres, 0)) as metres,
			sum(if(ok, secs, 0)) as seconds,
			group_concat(distinct patrol separator '\\n') as patrols,
			min(captured_at) as first_at,
			max(captured_at) as last_at
		from (
			select farm_hit, g, kind, patrol, cell, captured_at, metres, secs,
				{STEP_COUNTS_SQL} as ok
			from (
				select farm_hit, g, kind, patrol, captured_at, {cell_sql} as cell,
					{step_secs} as secs,
					{step_metres} as metres
				from ({' union all '.join(branches)}) p
				where g is not null
				window w as (partition by farm_hit, g, patrol order by captured_at)
			) s
		) t
		group by farm_hit, g, kind, cell
	"""
	keys = {g["farm"]: set(g["grid"]["keys"]) for g in geos if g.get("grid")}
	out = {}
	for r in frappe.db.sql(sql, params, as_dict=True):
		k = (r.farm_hit, r.g)
		s = out.get(k)
		if s is None:
			s = out[k] = _empty_stats(r.kind)
		s["points"] += int(r.points or 0)
		s["metres"] += float(r.metres or 0)
		s["seconds"] += int(r.seconds or 0)
		s["patrol_ids"].update(p for p in (r.patrols or "").split("\n") if p)
		if r.cell and r.cell in keys.get(r.farm_hit, ()):
			s["cells"].add(r.cell)
		if r.first_at and (s["first"] is None or r.first_at < s["first"]):
			s["first"] = r.first_at
		if r.last_at and (s["last"] is None or r.last_at > s["last"]):
			s["last"] = r.last_at
	return out


def _force_index(name):
	if frappe.db.db_type == "mariadb" and frappe.db.has_index("tabPatrol GPS Log", name):
		return f" force index ({name})"
	return ""


def _scans(farms, start, end):
	"""{(farm, guard id): {kind, scans, valid}} from Checkpoint Scan Log."""
	rows = frappe.db.sql(
		f"""select farm, {_GUARD_SQL} as g, {_KIND_SQL} as kind, count(*) as scans,
			sum(result = 'Valid') as valid
		from `tabCheckpoint Scan Log`
		where farm in %(farms)s and scanned_at between %(start)s and %(end)s
		group by farm, g, kind""",
		{"farms": tuple(farms), "start": start, "end": end},
		as_dict=True,
	)
	return {
		(r.farm, r.g): {"kind": r.kind, "scans": int(r.scans or 0), "valid": int(r.valid or 0)}
		for r in rows if r.g
	}


SERIOUS_SEVERITIES = ("High", "Critical")
# Longest real shift; older rows spanning several days are not one shift.
_MAX_SHIFT_HOURS = 24


def _shift_incidents(farms, start, end):
	"""{(farm, guard id): {kind, shifts, incidents: [{name, nature, severity,
	at}]}} - shifts that started in start <= time < end at the farm, and the
	farm's incidents in that window whose time falls inside one of that
	guard's shifts (overnight shifts included, start inclusive, end
	exclusive)."""
	first, last = start.date(), end.date()
	from upande_security.api.gate_movement import _shift_window
	from upande_security.api.security_dashboard import hidden_incident_types

	shifts = frappe.get_all(
		"Security Guard Shift Assignment",
		filters={
			"farm": ["in", list(farms)],
			"start_date": ["between", [frappe.utils.add_days(first, -1), last]],
			"docstatus": ["<", 2],
			"status": ["!=", "Cancelled"],
		},
		fields=["farm", "security_guard", "internal_guard", "external_guard",
			"start_date", "end_date", "start_time", "end_time"],
		limit_page_length=0,
	)
	inc_filters = {
		"farm": ["in", list(farms)],
		"incident_datetime": ["between", [str(start), str(end - datetime.timedelta(seconds=1))]],
	}
	hidden = hidden_incident_types()
	if hidden:
		inc_filters["nature_of_incident"] = ["not in", hidden]
	incidents = frappe.get_all(
		"Incident Report",
		filters=inc_filters,
		fields=["name", "farm", "incident_datetime", "nature_of_incident", "severity"],
		order_by="incident_datetime asc",
		limit_page_length=0,
	)
	by_farm = {}
	for inc in incidents:
		by_farm.setdefault(inc.farm, []).append(inc)

	out = {}
	for sh in shifts:
		if sh.security_guard == "Internal Guard" and sh.internal_guard:
			gid, kind = sh.internal_guard, "Internal Guard"
		elif sh.external_guard:
			gid, kind = sh.external_guard, "External Guard"
		else:
			continue
		try:
			sh_start, sh_end = _shift_window(sh)
		except Exception:
			continue
		if (sh_end - sh_start).total_seconds() > _MAX_SHIFT_HOURS * 3600:
			continue
		entry = out.setdefault((sh.farm, gid), {"kind": kind, "shifts": 0, "incidents": [], "_seen": set()})
		if start <= sh_start < end:
			entry["shifts"] += 1
		for inc in by_farm.get(sh.farm, []):
			at = frappe.utils.get_datetime(inc.incident_datetime)
			if sh_start <= at < sh_end and inc.name not in entry["_seen"]:
				entry["_seen"].add(inc.name)
				entry["incidents"].append({
					"name": inc.name,
					"nature": inc.nature_of_incident or "",
					"severity": inc.severity or "",
					"at": str(inc.incident_datetime),
					"scored": (inc.nature_of_incident or "") not in UNSCORED_INCIDENT_TYPES,
				})
	for entry in out.values():
		entry.pop("_seen", None)
		entry["incidents"].sort(key=lambda i: i["at"])
	return out


def _rank(farm, guards, grid, shift_inc=None):
	"""Score and rank one farm's guards. Returns (rows, weights, farm
	coverage %) - farm coverage being every guard's cells together.
	Safety: scored incidents per shift, against the farm's worst rate."""
	shift_inc = shift_inc or {}

	def inc_rate(gid):
		si = shift_inc.get((farm, gid)) or {}
		n = sum(1 for i in (si.get("incidents") or []) if i["scored"])
		return (n / si["shifts"]) if n and si.get("shifts") else float(n)
	total_cells = grid["cells"] if grid else 0
	any_scans = any(s["valid_scans"] for s in guards.values())
	if total_cells:
		weights = WEIGHTS if any_scans else NO_SCAN_WEIGHTS
	else:
		weights = NO_COVERAGE_WEIGHTS if any_scans else DISTANCE_ONLY

	best_cov = max((len(s["cells"]) for s in guards.values()), default=0)
	best_m = max((s["metres"] for s in guards.values()), default=0)
	best_scans = max((s["valid_scans"] for s in guards.values()), default=0)
	worst_rate = max((inc_rate(g) for g in guards), default=0)

	def share(v, best):
		return (v / best) if best else 0.0

	rows = []
	for gid, s in guards.items():
		n = len(s["cells"])
		score = 100 * (
			weights["coverage"] * share(n, best_cov)
			+ weights["distance"] * share(s["metres"], best_m)
			+ weights["scans"] * share(s["valid_scans"], best_scans)
			+ weights["safety"] * (1 - share(inc_rate(gid), worst_rate))
		)
		rows.append({
			"farm": farm,
			"guard": gid,
			"kind": s["kind"],
			"distance_km": round(s["metres"] / 1000, 2),
			"cells": n,
			"coverage_pct": round(100 * n / total_cells, 1) if total_cells else None,
			"patrol_hours": round(s["seconds"] / 3600, 2),
			"patrols": s["patrols"],
			"points": s["points"],
			"scans": s["scans"],
			"valid_scans": s["valid_scans"],
			"first_at": str(s["first"]) if s["first"] else None,
			"last_at": str(s["last"]) if s["last"] else None,
			"score": round(score, 1),
		})
	rows.sort(key=lambda r: (-r["score"], -r["distance_km"], r["guard"]))
	for i, r in enumerate(rows, 1):
		r["rank"] = i

	all_cells = set()
	for s in guards.values():
		all_cells |= s["cells"]
	farm_cov = round(100 * len(all_cells) / total_cells, 1) if total_cells else None
	return rows, weights, farm_cov


def _farm_hectares(geo):
	"""The farm boundary's area in hectares. geo["area"] is in square
	degrees; at farm scale an equirectangular projection at the farm's
	latitude is accurate to well under 1%."""
	bbox = (geo.get("on") or {}).get("bbox")
	if not geo.get("area") or not bbox:
		return None
	lat = math.radians((bbox[1] + bbox[3]) / 2)
	return geo["area"] * 111320 * math.cos(lat) * 110540 / 10000


def _guard_names(pairs):
	"""{id: display name} in two queries, not one per guard."""
	emp = [g for k, g in pairs if k == "Internal Guard"]
	ext = [g for k, g in pairs if k != "Internal Guard"]
	names = {}
	if emp:
		names.update(dict(frappe.get_all(
			"Employee", filters={"name": ["in", emp]}, fields=["name", "employee_name"], as_list=True
		)))
	if ext:
		names.update(dict(frappe.get_all(
			"Security Guard", filters={"name": ["in", ext]}, fields=["name", "full_name"], as_list=True
		)))
	return names
