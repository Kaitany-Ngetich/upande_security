# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Replay where guards were over a window of time.

The patrol map answers "where did people go today". This answers "where was
everyone at 02:14 last night", which is the question you actually have once
an incident has a timestamp on it.

WHY A DATETIME RANGE AND NOT A DATE
A night shift is the case this exists for, and a night shift is two dates:
20 Oct 21:00 to 21 Oct 06:00. fetchPatrolData and get_patrol_coverage_grid
both take a single `date`, so neither can express that window at all.

COVERAGE STARTS EMPTY
get_patrol_coverage_grid now takes the same window, and builds the surface
only from points inside it. At the first frame the map is blank and fills
as the replay runs. Showing the day's existing coverage underneath would
hide the very gap you are replaying to find.

COST
Reads go through the captured_at covering index (see
patrol_gps_log.on_doctype_update), so a night's window is a short range
scan rather than a walk of the whole table. The row cap below exists for
the other direction: someone asking for a month would otherwise pull
hundreds of thousands of points into one response.
"""

import frappe
from frappe import _

from upande_security.api.feature_flags import is_feature_enabled

#: A 12-hour night across a handful of guards is a few thousand points.
#: Past this the answer stops being a replay and starts being a data dump,
#: so it is thinned rather than truncated - a truncated replay would end
#: early and look like the guards went home.
MAX_POINTS = 12000

#: Longest replay window accepted, in hours (7 days).
MAX_WINDOW_HOURS = 24 * 7


def _guard_label(row):
	if row.get("personel") == "Internal Guard" and row.get("internal_guard"):
		return "Internal Guard", row["internal_guard"]
	if row.get("external_guard"):
		return "External Guard", row["external_guard"]
	return None, None


@frappe.whitelist()
def get_patrol_playback(farm, from_datetime, to_datetime, guard=None, include_on_duty=1):
	"""Points for every guard at `farm` between the two datetimes, grouped
	by guard and ordered in time.

	`include_on_duty` defaults ON here, unlike coverage: a replay wants to
	know where a guard stood as much as where they walked.
	"""
	if not is_feature_enabled("feature_patrol_coverage_grid"):
		# Same flag the live map's grid uses - playback is the same feature
		# seen over time, so it should not be separately switchable.
		return {"enabled": False}

	if not frappe.has_permission("Patrol GPS Log", ptype="read"):
		frappe.throw(_("You do not have permission to view Patrol GPS Logs."), frappe.PermissionError)
	if not frappe.has_permission("Farm", ptype="read", doc=farm):
		frappe.throw(_("You do not have permission to view {0}.").format(farm), frappe.PermissionError)

	try:
		start = frappe.utils.get_datetime(from_datetime)
		end = frappe.utils.get_datetime(to_datetime)
	except Exception:
		return {"error": _("Could not read the from/to times.")}
	if end <= start:
		return {"error": _("The end of the window must be after its start.")}
	# A replay is for an evening, not a season. Past this the response stops
	# being something you can watch and becomes a very slow data export -
	# 40 days at the fastest speed is still sixteen minutes of staring.
	if frappe.utils.time_diff_in_hours(end, start) > MAX_WINDOW_HOURS:
		return {
			"error": _("Pick a window of {0} days or less - this one is {1:.0f} days.").format(
				int(MAX_WINDOW_HOURS / 24), frappe.utils.time_diff_in_hours(end, start) / 24
			)
		}

	conditions = ["farm = %(farm)s", "captured_at between %(start)s and %(end)s"]
	params = {"farm": farm, "start": start, "end": end}
	if not frappe.utils.cint(include_on_duty):
		conditions.append("ifnull(tracking_mode, 'Patrol') != 'On Duty'")
	if guard:
		# One guard, whichever kind they are - the caller passes the id, not
		# the kind, because the map's guard picker only knows the label.
		conditions.append("(internal_guard = %(guard)s or external_guard = %(guard)s)")
		params["guard"] = guard

	# Index choice matters more here than anywhere else in this module.
	# This query is "one farm, one time range". Forcing the captured_at
	# covering index makes MariaDB walk every point in the window and
	# discard the other farms' rows - 449,502 rows examined for a 40-day
	# window on a farm holding 2,162 of them, which times the request out.
	# farm_captured_at turns that into a seek. Only fall back to the
	# captured_at index when no farm narrows the query.
	force = ""
	if frappe.db.db_type == "mariadb":
		if farm and frappe.db.has_index("tabPatrol GPS Log", "farm_captured_at"):
			force = " force index (farm_captured_at)"
		elif not farm:
			for index in ("captured_at_coverage_mode", "captured_at_coverage", "captured_at_index"):
				if frappe.db.has_index("tabPatrol GPS Log", index):
					force = " force index (" + index + ")"
					break

	rows = frappe.db.sql(
		"select captured_at, latitude, longitude, gps_accuracy, personel,"
		" internal_guard, external_guard, patrol, tracking_mode"
		" from `tabPatrol GPS Log`" + force + " where " + " and ".join(conditions)
		+ " order by captured_at asc",
		params,
		as_dict=True,
	)

	# Thin evenly rather than cut: a replay that stops early reads as "the
	# guards left", which is exactly the wrong conclusion to hand someone
	# investigating an incident.
	stride = 1
	if len(rows) > MAX_POINTS:
		stride = (len(rows) // MAX_POINTS) + 1
		rows = rows[::stride]

	guards = {}
	for r in rows:
		kind, gid = _guard_label(r)
		if not gid:
			continue
		try:
			lat = float(r.latitude)
			lng = float(r.longitude)
		except (TypeError, ValueError):
			continue
		g = guards.setdefault(
			gid,
			{"guard": gid, "kind": kind, "name": _display_name(kind, gid), "points": []},
		)
		g["points"].append(
			{
				"t": str(r.captured_at),
				"lat": lat,
				"lng": lng,
				"accuracy": r.gps_accuracy,
				"patrol": r.patrol,
				"mode": r.tracking_mode or "Patrol",
			}
		)

	return {
		"enabled": True,
		"farm": farm,
		"from_datetime": str(start),
		"to_datetime": str(end),
		"guards": sorted(guards.values(), key=lambda g: g["name"] or ""),
		"total_points": sum(len(g["points"]) for g in guards.values()),
		"thinned_every": stride if stride > 1 else None,
	}


def _display_name(kind, gid):
	if kind == "Internal Guard":
		return frappe.db.get_value("Employee", gid, "employee_name") or gid
	return frappe.db.get_value("Security Guard", gid, "full_name") or gid


@frappe.whitelist()
def get_playback_guards(farm, from_datetime, to_datetime):
	"""Just the guards who have any point in the window - to fill the
	picker without pulling every position first."""
	if not frappe.has_permission("Patrol GPS Log", ptype="read"):
		frappe.throw(_("You do not have permission to view Patrol GPS Logs."), frappe.PermissionError)
	try:
		start = frappe.utils.get_datetime(from_datetime)
		end = frappe.utils.get_datetime(to_datetime)
	except Exception:
		return []
	rows = frappe.db.sql(
		"select distinct personel, internal_guard, external_guard"
		" from `tabPatrol GPS Log`"
		" where farm = %s and captured_at between %s and %s",
		(farm, start, end),
		as_dict=True,
	)
	out = []
	for r in rows:
		kind, gid = _guard_label(r)
		if gid:
			out.append({"guard": gid, "kind": kind, "name": _display_name(kind, gid)})
	return sorted(out, key=lambda g: g["name"] or "")


@frappe.whitelist()
def get_playback_extent(farm=None):
	"""Oldest and newest position on record, so the page can offer a window
	that actually contains something.

	Defaulting to "last night" is the right instinct and the wrong default
	on a site whose tracking only started today: the user picks a sensible
	looking range, gets an empty replay, and reasonably concludes the page
	is broken.
	"""
	if not frappe.has_permission("Patrol GPS Log", ptype="read"):
		frappe.throw(_("You do not have permission to view Patrol GPS Logs."), frappe.PermissionError)
	conditions, params = [], {}
	if farm:
		conditions.append("farm = %(farm)s")
		params["farm"] = farm
	where = (" where " + " and ".join(conditions)) if conditions else ""
	row = frappe.db.sql(
		"select min(captured_at) as first_at, max(captured_at) as last_at,"
		" count(*) as points from `tabPatrol GPS Log`" + where,
		params,
		as_dict=True,
	)
	r = row[0] if row else {}
	return {
		"farm": farm,
		"first_at": str(r.get("first_at")) if r.get("first_at") else None,
		"last_at": str(r.get("last_at")) if r.get("last_at") else None,
		"points": r.get("points") or 0,
	}
