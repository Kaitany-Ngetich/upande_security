# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""The app's Reports > Patrols tab (security_api.security_report, tab
"patrols"): GPS points, distance, guards and routes for a date range, a By
Guard table, and a sample of points for the app's map.

WHICH POINTS
The Patrol Map's (fetchPatrolData), through patrol_rules: On Duty left out
(standing at a post is not patrolling), positions that do not parse or sit
outside -90..90 / -180..180 or at (0, 0) dropped, fixes worse than
MAX_ACCURACY_M dropped. With a farm, the map's farm rule (the same as
patrol_playback.farm_points): with Hide Patrol Points Outside Farm Boundary
on, every point inside the boundary grown by Boundary Tolerance whatever
farm it was saved under; otherwise points saved under the farm plus
untagged ones within ~110 m of it. Without a farm, every point - or, for a
user limited to some farms, the points saved under those farms.

WHO
The map's guard identity (_patrol_guard_identity): the internal guard, else
the external guard, else the account that sent the point, shown as
"Name (no guard link)". Distance is summed per guard id and patrol.

DISTANCE
A haversine sum over consecutive points of one guard's one patrol, counting
only the steps patrol_rules.step_counts accepts (no gap over MAX_GAP_S, no
speed over MAX_SPEED_KMH). With the boundary rule on, a step whose straight
line leaves the boundary is a trail break, as on the map, and is not
counted either.

COST
Every figure is worked out in the database, one calendar day at a time, by
one query per day that returns a row per (guard, patrol) - tens of rows,
not tens of thousands of points. The same query packs an evenly spaced
sample of the day's points (at most DRAW_LIMIT) into those rows for the
map. A settled day is cached for a month, so 30 days is 28 cache reads and
two queries; the nightly job (warm_report_days) fills the all-farms days.
"""

import hashlib
import json

import frappe
from frappe import _
from shapely.geometry import mapping

from upande_security.api.feature_flags import is_feature_enabled
from upande_security.api.patrol_rules import (
	POINT_WHERE_SQL,
	RULES_VERSION,
	STEP_COUNTS_SQL,
	sql_params,
	step_sql,
)

#: Most points sent to the app's map for one request, thinned evenly over
#: the range so a long range still shows whole routes.
DRAW_LIMIT = 3000
#: Longest range the report answers. The app asks for Today, 7 or 30 days.
MAX_DAYS = 31

_TTL_TODAY_S = 60
_TTL_RECENT_S = 300
_TTL_SETTLED_S = 31 * 86400

# The map's guard identity, in SQL (see security_dashboard._patrol_guard_identity).
_NO_OWNER = "('', 'Administrator', 'Guest')"
GUARD_ID_SQL = (
	"coalesce(nullif(internal_guard, ''), nullif(external_guard, ''),"
	f" if(ifnull(owner, '') in {_NO_OWNER}, 'Unassigned', owner))"
)
GUARD_KIND_SQL = (
	"case when ifnull(internal_guard, '') != '' then 'Internal Guard'"
	" when ifnull(external_guard, '') != '' then 'External Guard'"
	f" when ifnull(owner, '') not in {_NO_OWNER} then 'User' else '' end"
)


def patrols_report(from_date, to_date, farm=None):
	"""{points, metres, guards: {id: {...}}, routes, draw, boundaries, farms}
	for whole days from_date..to_date - see the module docstring.

	Permission: read on Patrol GPS Log; with `farm`, read on that Farm;
	without, only farms the user may read (their points, outlines and the
	farm list)."""
	if not frappe.has_permission("Patrol GPS Log", ptype="read"):
		frappe.throw(_("You do not have permission to view Patrol GPS Logs."), frappe.PermissionError)

	first, last = frappe.utils.getdate(from_date), frappe.utils.getdate(to_date)
	if last < first:
		first, last = last, first
	if frappe.utils.date_diff(last, first) + 1 > MAX_DAYS:
		frappe.throw(_("Pick a range of {0} days or less for patrols.").format(MAX_DAYS))

	# get_list, so User Permissions on Farm apply. No read on Farm at all
	# is no farm.
	allowed = (
		frappe.get_list("Farm", pluck="name", order_by="name asc", limit_page_length=0)
		if frappe.has_permission("Farm", ptype="read") else []
	)
	if farm:
		if not frappe.db.exists("Farm", farm) or not frappe.has_permission("Farm", ptype="read", doc=farm):
			frappe.throw(_("You do not have permission to view {0}.").format(farm), frappe.PermissionError)
		scope = _farm_scope(farm)
		outline_farms = [farm]
	else:
		# A user limited to some farms sees the points saved under them; an
		# unlimited one every point, untagged ones included, as the map does.
		limited = len(allowed) < frappe.db.count("Farm")
		scope = _saved_scope(allowed) if limited else {"kind": "all", "key": "all"}
		outline_farms = allowed

	# A role that may only read its own Patrol GPS Logs (Security Guard,
	# Employee: "if owner") gets only the points it sent.
	from frappe.permissions import get_role_permissions

	perms = get_role_permissions("Patrol GPS Log")
	if (perms.get("if_owner") or {}).get("read") is not None:
		scope = {**scope, "owner": frappe.session.user, "key": scope["key"] + "-own-" + _digest(frappe.session.user)}

	days = []
	day = first
	while day <= last:
		days.append(_day(day, scope))
		day = frappe.utils.add_days(day, 1)

	out = _combine(days)
	out["boundaries"] = boundaries(outline_farms)
	out["farms"] = allowed
	return out


def _combine(days):
	"""Totals, per-guard figures and the map sample from a list of days."""
	guards, routes = {}, set()
	points, metres = 0, 0.0
	for d in days:
		for g, kind, patrol, n, m, last_at in d["rows"]:
			points += n
			metres += m
			st = guards.get(g)
			if st is None:
				st = guards[g] = {"kind": kind, "points": 0, "metres": 0.0, "patrols": set(), "last": ""}
			st["points"] += n
			st["metres"] += m
			if patrol:
				st["patrols"].add(patrol)
				routes.add(patrol)
			st["last"] = max(st["last"], last_at or "")

	# Each day's sample is even within the day; take from each day in
	# proportion to its points so the whole range is evenly thinned.
	draw = []
	total = sum(d["n"] for d in days)
	for d in days:
		if not d["n"] or not d["sample"]:
			continue
		want = d["n"] if total <= DRAW_LIMIT else max(1, round(DRAW_LIMIT * d["n"] / total))
		draw += _evenly(d["sample"], want)
	# Rounding per day can land a point or two over.
	draw = _evenly(draw, DRAW_LIMIT)

	return {"points": points, "metres": metres, "guards": guards, "routes": len(routes), "draw": draw}


def _evenly(items, want):
	if len(items) <= want:
		return list(items)
	step = len(items) / want
	return [items[int(i * step)] for i in range(want)]


def guard_names(guards):
	"""{id: display name} for {id: {"kind": ...}}, as the map shows them -
	a point with no guard link reads "Name (no guard link)"."""
	by_kind = {}
	for gid, st in guards.items():
		by_kind.setdefault(st["kind"], []).append(gid)
	names = {}
	for kind, doctype, field in (
		("Internal Guard", "Employee", "employee_name"),
		("External Guard", "Security Guard", "full_name"),
		("User", "User", "full_name"),
	):
		ids = by_kind.get(kind)
		if ids:
			names.update(dict(frappe.get_all(
				doctype, filters={"name": ["in", ids]}, fields=["name", field], as_list=True
			)))
	out = {}
	for gid, st in guards.items():
		if st["kind"] == "User":
			out[gid] = (names.get(gid) or gid) + " (no guard link)"
		elif st["kind"]:
			out[gid] = names.get(gid) or gid
		else:
			out[gid] = _("Unassigned")
	return out


# --- scopes --------------------------------------------------------------


def _digest(text, length=16):
	return hashlib.sha1(text.encode()).hexdigest()[:length]


def _saved_scope(farms):
	farms = sorted(farms)
	return {"kind": "saved", "farms": farms, "key": "saved-" + _digest(json.dumps(farms))}


def _farm_scope(farm):
	"""One farm, by the map's rule. Keyed on the farm's geometry, Boundary
	Tolerance and the boundary flag, so changing any of them is seen at once."""
	from upande_security.api.patrol_coverage import _coverage_settings
	from upande_security.api.patrol_ranking import _farm_geo

	width, height = _coverage_settings()[:2]
	tol = frappe.db.get_single_value("Security Ops Settings", "coverage_boundary_tolerance_m")
	tol = 5 if tol is None else max(0, int(tol))
	geo = _farm_geo(farm, width, height, tol)
	boundary_on = bool(is_feature_enabled("feature_patrol_boundary_filter"))
	if boundary_on and not geo.get("on"):
		boundary_on = False  # no usable boundary: the map falls back too
	return {
		"kind": "farm",
		"farm": farm,
		"boundary_on": boundary_on,
		"area": geo.get("on") if boundary_on else geo.get("off"),
		"key": "farm-" + _digest(json.dumps([farm, geo["key"], boundary_on])),
	}


# --- one day -----------------------------------------------------------


def _day_key(day, scope):
	return f"upande_security:patrol_report_day:{RULES_VERSION}:{scope['key']}:{day}"


def _day(day, scope):
	"""{"rows": [[guard id, kind, patrol, points, metres, last at]], "n":
	points, "sample": [[lat, lng, at, guard id, patrol]]} for one day."""
	day = frappe.utils.getdate(day)
	key = _day_key(day, scope)
	cached = frappe.cache.get_value(key)
	if cached is not None:
		return cached
	out = day_figures(f"{day} 00:00:00", f"{day} 23:59:59.999999", scope)
	age = (frappe.utils.getdate() - day).days
	ttl = _TTL_SETTLED_S if age >= 2 else (_TTL_RECENT_S if age == 1 else _TTL_TODAY_S)
	frappe.cache.set_value(key, out, expires_in_sec=ttl)
	return out


def _force(name):
	if frappe.db.db_type == "mariadb" and frappe.db.has_index("tabPatrol GPS Log", name):
		return f" force index ({name})"
	return ""


def _branches(scope, params):
	"""SELECTs whose union is the scope's points in the window."""
	cols = (
		f"name, {GUARD_ID_SQL} as g, {GUARD_KIND_SQL} as kind, ifnull(patrol, '') as patrol,"
		" captured_at, latitude + 0 as lat, longitude + 0 as lng"
	)
	base = [
		"captured_at between %(start)s and %(end)s",
		"ifnull(tracking_mode, 'Patrol') != 'On Duty'",
	] + POINT_WHERE_SQL
	table = "`tabPatrol GPS Log`"
	if scope.get("owner"):
		params["owner"] = scope["owner"]
		base.append("owner = %(owner)s")

	if scope["kind"] == "all":
		return [f"select {cols} from {table}{_force('captured_at_coverage_mode')} where {' and '.join(base)}"]
	if scope["kind"] == "saved":
		if not scope["farms"]:
			return []
		params["farms"] = tuple(scope["farms"])
		return [f"select {cols} from {table}{_force('farm_captured_at')} where farm in %(farms)s and {' and '.join(base)}"]

	area = scope["area"]
	branches = []
	in_area = None
	if area:
		x0, y0, x1, y1 = area["bbox"]
		params.update({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "wkt": area["wkt"]})
		# The box is answered from the covering index; only points in it are
		# read from the table and tested against the exact outline.
		in_area = (
			"latitude + 0 between %(y0)s and %(y1)s and longitude + 0 between %(x0)s and %(x1)s"
			" and st_contains(st_geomfromtext(%(wkt)s), point(longitude + 0, latitude + 0))"
		)
	if scope["boundary_on"]:
		branches.append(
			f"select {cols} from {table}{_force('captured_at_coverage_mode')}"
			f" where {' and '.join(base)} and {in_area}"
		)
		return branches
	params["farm"] = scope["farm"]
	branches.append(f"select {cols} from {table}{_force('farm_captured_at')} where farm = %(farm)s and {' and '.join(base)}")
	if in_area:
		branches.append(
			f"select {cols} from {table}{_force('captured_at_coverage_mode')}"
			f" where {' and '.join(base)} and ifnull(farm, '') = '' and {in_area}"
		)
	return branches


def day_figures(start, end, scope):
	"""One query: a row per (guard, patrol) with its points, walked metres
	and last point, plus that group's share of an even sample of the
	window's points packed as text (lat,lng,at;...) - the sample rides
	along so the points are read once."""
	params = {"start": start, "end": end, "limit": DRAW_LIMIT, **sql_params()}
	branches = _branches(scope, params)
	if not branches:
		return {"rows": [], "n": 0, "sample": []}

	secs, metres = step_sql("w")
	ok = STEP_COUNTS_SQL
	if scope["kind"] == "farm" and scope["boundary_on"]:
		# A trail break, as on the map: the straight line from the previous
		# point runs outside the boundary.
		ok += (
			" and st_contains(st_geomfromtext(%(wkt)s),"
			" linestring(point(plng, plat), point(lng, lat)))"
		)
	sql = f"""
		select g, kind, patrol,
			count(*) as points,
			sum(if({ok}, metres, 0)) as metres,
			max(captured_at) as last_at,
			group_concat(
				if(mod(rn - 1, ceil(n / %(limit)s)) = 0, concat_ws(',', round(lat, 7), round(lng, 7), left(captured_at, 19)), null)
				order by captured_at separator ';'
			) as sample
		from (
			select g, kind, patrol, captured_at, lat, lng,
				lag(lat) over w as plat, lag(lng) over w as plng,
				{secs} as secs, {metres} as metres,
				row_number() over (order by captured_at, name) as rn,
				count(*) over () as n
			from ({' union all '.join(branches)}) p
			window w as (partition by g, patrol order by captured_at, name)
		) s
		group by g, kind, patrol
	"""
	# The sample of a busy guard's patrol is long text; the default cap
	# (1 MB on MariaDB, 1 KB on some MySQL) would cut it silently.
	frappe.db.sql("set session group_concat_max_len = 16777216")
	rows, sample, n = [], [], 0
	for r in frappe.db.sql(sql, params, as_dict=True):
		count = int(r.points or 0)
		n += count
		rows.append([r.g, r.kind or "", r.patrol or "", count, round(float(r.metres or 0), 1), str(r.last_at) if r.last_at else None])
		for item in (r.sample or "").split(";"):
			if not item:
				continue
			lat, lng, at = item.split(",", 2)
			sample.append([float(lat), float(lng), at, r.g, r.patrol or ""])
	sample.sort(key=lambda p: p[2])
	return {"rows": rows, "n": n, "sample": sample}


def warm_report_days():
	"""Nightly (hooks: daily_long): the all-farms figures of the settled days
	of the last MAX_DAYS days, so the app's 7 and 30 day reports only work
	out today and yesterday live."""
	today = frappe.utils.getdate()
	scope = {"kind": "all", "key": "all"}
	for back in range(MAX_DAYS, 1, -1):
		day = frappe.utils.add_days(today, -back)
		if frappe.cache.get_value(_day_key(day, scope)) is None:
			_day(day, scope)


# --- outlines ----------------------------------------------------------


def boundaries(farms):
	"""[{farm, geojson}] for the farms with a usable boundary - from a cache
	keyed on each farm's `modified`, so outlines are parsed and simplified
	once per change, not on every request."""
	if not farms:
		return []
	modified = dict(frappe.get_all(
		"Farm", filters={"name": ["in", list(farms)]}, fields=["name", "modified"], as_list=True
	))
	out = []
	for f in farms:
		if f not in modified:
			continue
		key = "upande_security:farm_outline:" + _digest(json.dumps([f, str(modified[f])]), 20)
		geo = frappe.cache.get_value(key)
		if geo is None:
			geo = _outline(f) or {}
			frappe.cache.set_value(key, geo, expires_in_sec=7 * 86400)
		if geo:
			out.append({"farm": f, "geojson": geo})
	return out


def _outline(farm):
	from upande_security.api.patrol_coverage import _load_farm_polygon

	try:
		poly = _load_farm_polygon(farm)
	except Exception:
		return None
	if poly is None:
		return None
	return mapping(poly.simplify(0.00002, preserve_topology=True))

