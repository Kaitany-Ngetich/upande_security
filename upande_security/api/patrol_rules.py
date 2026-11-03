# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Which GPS points count, and which steps between them count as walked.

One rule for the Patrol Map (fetchPatrolData), the app's Reports > Patrols
tab (patrol_report) and the Guard ranking (patrol_ranking), in Python for
code that already holds the rows and in SQL for code that sums in the
database.

A POINT counts when
- it has a latitude and a longitude that parse, inside -90..90 / -180..180,
  and is not exactly (0, 0) - the position a phone reports before it has
  any fix;
- its accuracy is MAX_ACCURACY_M or better, or not recorded (older rows,
  before the field existed: absence is not evidence of a bad fix).

A STEP between two consecutive points of one guard's one patrol counts
towards distance only when the points are at most MAX_GAP_S apart and the
implied speed is at most MAX_SPEED_KMH. A longer gap is the phone asleep -
the straight line across it is a guess, not a walk. A faster step is a GPS
jump (a swapped or stale fix with no accuracy recorded, a cell-tower fix):
one such step can add hundreds of kilometres to a day.
"""

import math

# No app imports: the Patrol Map's module (security_dashboard) and
# patrol_coverage both import this one.

# Coarse network / wifi fixes are 100s-1000s of metres out; a point this
# vague says nothing about where on the farm the guard was.
MAX_ACCURACY_M = 100
MAX_GAP_S = 600
MAX_SPEED_KMH = 25
MAX_SPEED_MPS = MAX_SPEED_KMH / 3.6

#: Part of every cache key holding figures worked out under these rules -
#: change a rule above, bump this, and nothing cached under the old ones is
#: read again.
RULES_VERSION = "2"

_EARTH_M = 6371000


def to_float(value):
	"""Number from a text column ("12", "12.5", "12 m"), or None."""
	if value in (None, ""):
		return None
	raw = str(value).strip().lower()
	for suffix in ("metres", "meters", "metre", "meter", "m"):
		if raw.endswith(suffix):
			raw = raw[: -len(suffix)].strip()
			break
	try:
		v = float(raw)
	except (TypeError, ValueError):
		return None
	return v if math.isfinite(v) else None


def valid_fix(lat, lng):
	"""True when (lat, lng) - already floats or None - is a usable position."""
	if lat is None or lng is None:
		return False
	if not (-90 <= lat <= 90 and -180 <= lng <= 180):
		return False
	return not (lat == 0 and lng == 0)


def accurate_enough(accuracy):
	acc = to_float(accuracy)
	return acc is None or acc <= MAX_ACCURACY_M


def haversine_m(lat1, lng1, lat2, lng2):
	p1, p2 = math.radians(lat1), math.radians(lat2)
	dp, dl = p2 - p1, math.radians(lng2 - lng1)
	a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
	return 2 * _EARTH_M * math.asin(min(1.0, math.sqrt(a)))


def step_counts(metres, seconds):
	"""Whether a step of `metres` over `seconds` counts as walked."""
	if seconds is None or seconds < 0 or seconds > MAX_GAP_S:
		return False
	return metres <= max(seconds, 1) * MAX_SPEED_MPS


# --- SQL ---------------------------------------------------------------
# Over `tabPatrol GPS Log`; every column tested here is in the
# captured_at_coverage_mode index, so a window scan through that index
# answers them without reading the row. Takes %(acc)s.
POINT_WHERE_SQL = [
	"ifnull(latitude, '') != ''",
	"ifnull(longitude, '') != ''",
	"latitude + 0 between -90 and 90",
	"longitude + 0 between -180 and 180",
	"not (latitude + 0 = 0 and longitude + 0 = 0)",
	"(ifnull(gps_accuracy, '') = '' or gps_accuracy + 0 <= %(acc)s)",
]


def sql_params():
	return {"acc": MAX_ACCURACY_M, "gap": MAX_GAP_S, "mps": MAX_SPEED_MPS}


def step_sql(window="w", lat="lat", lng="lng", at="captured_at"):
	"""(seconds, metres) SQL expressions for the step from the previous row
	of `window` to this one, over numeric `lat` / `lng` columns."""
	secs = f"timestampdiff(second, lag({at}) over {window}, {at})"
	metres = (
		f"{_EARTH_M} * 2 * asin(least(1, sqrt("
		f"pow(sin(radians({lat} - lag({lat}) over {window}) / 2), 2)"
		f" + cos(radians({lat})) * cos(radians(lag({lat}) over {window}))"
		f" * pow(sin(radians({lng} - lag({lng}) over {window}) / 2), 2)"
		")))"
	)
	return secs, metres


#: Over columns `secs` and `metres` from step_sql; takes %(gap)s, %(mps)s.
STEP_COUNTS_SQL = "(secs is not null and secs between 0 and %(gap)s and metres <= greatest(secs, 1) * %(mps)s)"
