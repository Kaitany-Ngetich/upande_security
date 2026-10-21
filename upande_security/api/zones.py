# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Restricted sections inside a farm, and who is found in them.

A farm has one boundary, and `tasks.check_patrol_geofence_and_gaps` already
flags a guard whose last ping falls OUTSIDE it. This is the inverse and the
finer grain: a guard who is inside the farm but inside a section they do
not belong in - a fuel yard, a chemical store, a block they have no reason
to be on.

WHY THIS CAN WORK NOW
On-duty tracking (Patrol GPS Log.tracking_mode = "On Duty") means a guard's
position is logged through their whole shift, not only while walking a
patrol. Before that a breach was only visible if it happened mid-patrol,
which is exactly when a guard is least likely to be somewhere they should
not be.

WHAT IS AND IS NOT COVERED
Guards only, and only outdoors. Staff, contractors and visitors carry no
app, so they produce no position - catching them needs door readers or gate
scans, which give crossings rather than continuous position. And GPS does
not work inside a closed building: an insulated store is the worst case for
it. Outdoor sections are reliable; an indoor room needs a different sensor
and is deliberately out of scope here.

DECIDING A BREACH
`Security Zone.default_access` is the policy, the rules are exceptions, and
the first matching rule wins - so a specific Allow above a blanket Deny is
how an exception is carved out. A zone with no boundary is skipped entirely
rather than treated as matching everywhere.

NOISE
The same guard standing in the same zone is one alert per
`zone_breach_grace_minutes` (default 55), not one per run. This check runs
every 15 minutes; without that window a guard posted beside a fuel yard
would raise four alerts an hour and the alerts would stop being read. Same
reasoning, and the same window, as _recent_alert_exists in tasks.py.
"""

import json

import frappe

ATTEMPT_TYPE = "Restricted Zone Entry"
_DEFAULT_GRACE_MINUTES = 55


def _ring_from_geojson(raw):
	"""Outer ring as [(lng, lat), ...] from a GeoJSON string, or None.

	Accepts the shapes Frappe's Attach/Geolocation fields actually produce:
	a FeatureCollection, a bare Feature, or a bare geometry. Polygon and the
	first polygon of a MultiPolygon are both handled; anything else (a
	LineString someone drew by mistake) returns None so the zone is skipped
	rather than silently matching nothing.
	"""
	if not raw:
		return None
	try:
		parsed = json.loads(raw) if isinstance(raw, str) else raw
	except Exception:
		return None

	geometry = None
	if isinstance(parsed, dict):
		if parsed.get("type") == "FeatureCollection":
			features = parsed.get("features") or []
			if features:
				geometry = (features[0] or {}).get("geometry")
		elif parsed.get("type") == "Feature":
			geometry = parsed.get("geometry")
		elif "coordinates" in parsed:
			geometry = parsed
	if not isinstance(geometry, dict):
		return None

	coords = geometry.get("coordinates") or []
	gtype = geometry.get("type")
	try:
		if gtype == "Polygon":
			ring = coords[0]
		elif gtype == "MultiPolygon":
			ring = coords[0][0]
		else:
			return None
		# Guard against a degenerate ring - two points cannot enclose
		# anything, and the ray-cast would happily return nonsense.
		if len(ring) < 3:
			return None
		return [(float(p[0]), float(p[1])) for p in ring]
	except Exception:
		return None


def active_zones(farm):
	"""Active zones of a farm that actually have a usable boundary."""
	out = []
	for z in frappe.get_all(
		"Security Zone",
		filters={"farm": farm, "active": 1},
		fields=["name", "zone_name", "farm", "severity", "default_access"],
	):
		raw = frappe.db.get_value("Security Zone", z.name, "boundary_geojson")
		ring = _ring_from_geojson(_read_attachment(raw))
		if ring:
			z["ring"] = ring
			out.append(z)
	return out


def _read_attachment(value):
	"""boundary_geojson is an Attach, so the field holds a /files/... path,
	not the GeoJSON. Read the file; tolerate a site where someone pasted the
	JSON straight into the field instead."""
	if not value:
		return None
	if isinstance(value, str) and value.strip().startswith("{"):
		return value
	try:
		from frappe.utils.file_manager import get_file

		return get_file(value)[1]
	except Exception:
		return None


def _day_matches(rule_days, when):
	if not rule_days or rule_days == "All Days":
		return True
	weekday = when.weekday()  # Mon=0 .. Sun=6
	if rule_days == "Weekdays":
		return weekday < 5
	if rule_days == "Weekends":
		return weekday >= 5
	return True


def _time_matches(from_time, to_time, when):
	"""Both blank is the whole day. An end before the start runs past
	midnight (22:00-06:00), which is the common case for a night rule."""
	if not from_time or not to_time:
		return True
	now = when.time()
	start = (frappe.utils.get_time(from_time), frappe.utils.get_time(to_time))
	f, t = start
	if f <= t:
		return f <= now <= t
	return now >= f or now <= t


def _rule_applies_to(rule, person):
	"""`person` is {'employee': .., 'security_guard': .., 'user': ..}."""
	if rule.applies_to == "Anyone":
		return True
	if rule.applies_to == "Employee":
		return bool(rule.employee) and rule.employee == person.get("employee")
	if rule.applies_to == "Security Guard":
		return bool(rule.security_guard) and rule.security_guard == person.get("security_guard")
	if rule.applies_to == "Role":
		if not rule.role or not person.get("user"):
			return False
		return rule.role in frappe.get_roles(person["user"])
	return False


def is_allowed(zone_name, person, when=None):
	"""May `person` be in this zone at `when`? First matching rule wins;
	no match falls back to the zone's default_access."""
	when = when or frappe.utils.now_datetime()
	zone = frappe.get_cached_doc("Security Zone", zone_name)
	for rule in zone.access_rules or []:
		if not _rule_applies_to(rule, person):
			continue
		if not _day_matches(rule.days, when):
			continue
		if not _time_matches(rule.from_time, rule.to_time, when):
			continue
		return rule.effect == "Allow"
	return zone.default_access == "Allow"


def _recent_breach(zone, person_key, grace_minutes):
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-grace_minutes)
	return frappe.db.exists(
		"Unauthorized Access Attempt",
		{
			"attempt_type": ATTEMPT_TYPE,
			"zone": zone,
			"reference": person_key,
			"attempt_time": [">=", cutoff],
		},
	)


def record_breach(zone, person, point, when=None):
	"""Write the Unauthorized Access Attempt for one breach, or None if an
	identical one was already raised inside the repeat window.

	Best-effort by design, matching security_alerts.log_unauthorized_access:
	a failure here must never break the sweep that found it.
	"""
	when = when or frappe.utils.now_datetime()
	grace = (
		frappe.db.get_single_value("Security Ops Settings", "zone_breach_grace_minutes")
		or _DEFAULT_GRACE_MINUTES
	)
	person_key = person.get("security_guard") or person.get("employee") or person.get("user") or "?"
	if _recent_breach(zone["name"], person_key, grace):
		return None

	try:
		doc = frappe.new_doc("Unauthorized Access Attempt")
		doc.attempt_type = ATTEMPT_TYPE
		doc.zone = zone["name"]
		doc.farm = zone.get("farm")
		doc.severity = zone.get("severity")
		doc.reference = person_key
		doc.person_name = person.get("name") or person_key
		doc.attempted_by = person.get("user")
		doc.latitude = str(point.get("latitude") or "")
		doc.longitude = str(point.get("longitude") or "")
		doc.attempt_time = point.get("captured_at") or when
		doc.detail = (
			(person.get("name") or person_key)
			+ " was inside "
			+ (zone.get("zone_name") or zone["name"])
			+ " at "
			+ str(point.get("captured_at") or when)
			+ ", which they are not cleared for."
		)
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return doc.name
	except Exception as e:
		frappe.log_error("zones.record_breach " + str(zone.get("name")), str(e))
		return None
