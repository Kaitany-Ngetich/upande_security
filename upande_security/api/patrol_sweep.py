# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Patrolled area as the ground a guard swept: a corridor of Sweep Offset
metres either side of every step they walked, inside the farm's boundary.

Why not the grid: a grid square counts in full the moment one GPS fix lands
in it, so with coarse squares a 200 m walk "patrols" 25 ha. The corridor
grows with the ground actually walked - out and back along one path adds
nothing the second time, and two guards on the same road share it.

WHICH STEPS
The same steps that count towards distance (patrol_rules.step_counts): a
gap longer than MAX_GAP_S or a GPS jump breaks the track, so no corridor is
drawn across ground nobody walked. A fix with no counted step on either
side (one stray point) sweeps nothing.

GEOMETRY
Worked in metres on a flat frame anchored at the farm's south-west corner
(equirectangular at the farm's mid latitude - well under 1% off at farm
scale, the same approximation the grid uses). A day's corridor per guard
is clipped to the farm, simplified to ~1 m and kept as compressed WKB, so
a period is the union of its days and the farm's total the union of its
guards - overlap counted once either way.
"""

import base64
import math
import zlib

import frappe

DEFAULT_OFFSET_M = 100
MAX_OFFSET_M = 500
#: Part of the ranking's cache keys: bump when the corridor rules change.
SWEEP_VERSION = "1"
# Arc segments per quarter circle on a corridor's rounded ends - plenty at
# 100 m, and four times fewer vertices than shapely's default.
_QUAD_SEGS = 4
_SIMPLIFY_M = 1.0
# A walk is first straightened to within ~5 m (GPS jitter while standing or
# strolling - against a 100 m corridor it moves the area by well under 1%)
# and buffered CHUNK points at a time: GEOS buffers a long, self-crossing
# line very slowly (a day's walk: minutes and GBs), short pieces in
# milliseconds, and their union is the same ground.
_PATH_TOL_M = 5.0
_CHUNK = 20
_W_PER_DEG_LAT = 110540
_W_PER_DEG_LNG = 111320


def offset_m():
	"""Security Ops Settings > Patrol Sweep Offset: metres either side of a
	guard's path counted as patrolled."""
	# Before the site has migrated the field is not there yet, and reading
	# it would throw - the ranking keeps working on the default meanwhile.
	if not frappe.get_meta("Security Ops Settings").has_field("coverage_sweep_offset_m"):
		return DEFAULT_OFFSET_M
	value = frappe.db.get_single_value("Security Ops Settings", "coverage_sweep_offset_m")
	try:
		value = int(value)
	except (TypeError, ValueError):
		return DEFAULT_OFFSET_M
	return min(max(value, 1), MAX_OFFSET_M) if value > 0 else DEFAULT_OFFSET_M


def frame(poly):
	"""The flat metre frame for a farm boundary (shapely, lng/lat)."""
	minx, miny, _maxx, maxy = poly.bounds
	return {
		"lng0": minx,
		"lat0": miny,
		"kx": _W_PER_DEG_LNG * math.cos(math.radians((miny + maxy) / 2)),
		"ky": _W_PER_DEG_LAT,
	}


def to_metres(fr, lng, lat):
	return ((lng - fr["lng0"]) * fr["kx"], (lat - fr["lat0"]) * fr["ky"])


def farm_shape(poly, fr):
	"""The farm boundary in the frame's metres, valid and simplified."""
	from shapely import make_valid
	from shapely.ops import transform

	shape = transform(lambda x, y, z=None: to_metres(fr, x, y), poly)
	shape = make_valid(shape)
	return shape.simplify(_SIMPLIFY_M, preserve_topology=True)


def corridor(tracks, offset, farm):
	"""The ground `offset` metres either side of the tracks ([[(x, y)...]]
	in metres, each one unbroken walk), inside `farm`. None if nothing."""
	from shapely.geometry import LineString, Point
	from shapely.ops import unary_union

	# Tolerances scale down with a narrow corridor so its ends are not shaved.
	tol = min(_SIMPLIFY_M, offset / 100)
	path_tol = min(_PATH_TOL_M, offset / 20)
	pieces = []
	for track in tracks:
		if len(track) < 2:
			continue
		line = LineString(track)
		if line.length == 0:
			# Steps of 0 m (a guard standing still) make a line with no
			# length, which buffers to nothing: they still watched around them.
			pieces.append(Point(track[0]).buffer(offset, quad_segs=_QUAD_SEGS))
			continue
		coords = list(line.simplify(path_tol).coords)
		for i in range(0, len(coords) - 1, _CHUNK):
			pieces.append(LineString(coords[i : i + _CHUNK + 1]).buffer(offset, quad_segs=_QUAD_SEGS))
	if not pieces:
		return None
	swept = unary_union(pieces).intersection(farm)
	if swept.is_empty:
		return None
	return swept.simplify(tol, preserve_topology=True)


def union(geoms):
	"""One geometry covering all of `geoms` (overlap once), or None."""
	from shapely.ops import unary_union

	geoms = [g for g in geoms if g is not None and not g.is_empty]
	if not geoms:
		return None
	return geoms[0] if len(geoms) == 1 else unary_union(geoms)


def area_m2(geom):
	return float(geom.area) if geom is not None else 0.0


def encode(geom):
	"""Compact text for the cache: zlib-compressed WKB, base64."""
	if geom is None:
		return None
	import shapely

	return base64.b64encode(zlib.compress(shapely.to_wkb(geom))).decode()


def decode(text):
	if not text:
		return None
	import shapely

	return shapely.from_wkb(zlib.decompress(base64.b64decode(text)))
