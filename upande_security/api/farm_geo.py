# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Which farm a GPS position falls in.

A farm's boundary is its Geolocation field `location` ("Farm Boundary",
drawn on the map in Desk). Older code read `boundary_geojson`, a field some
sites never had - there the boundary is taken from `location` too, so
anything built on farm_ring() (the patrol geofence, the farm-at-sign-in
lookup) works on both.
"""

import frappe

from upande_security.api.zones import _ring_from_geojson


def _boundary_fields():
	meta = frappe.get_meta("Farm")
	return [f for f in ("location", "boundary_geojson") if meta.has_field(f)]


def farm_ring(farm):
	"""The farm's outer boundary as [(lng, lat), ...], or None if none is drawn."""
	for field in _boundary_fields():
		ring = _ring_from_geojson(frappe.db.get_value("Farm", farm, field))
		if ring:
			return ring
	return None


def point_in_ring(lat, lng, ring):
	"""Ray-casting test; `ring` is [(lng, lat), ...] (GeoJSON order)."""
	inside = False
	j = len(ring) - 1
	for i in range(len(ring)):
		xi, yi = ring[i]
		xj, yj = ring[j]
		if (yi > lat) != (yj > lat):
			x_cross = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
			if lng < x_cross:
				inside = not inside
		j = i
	return inside


def _area(ring):
	"""Shoelace area in degrees^2 - only used to pick the smaller of two farms
	whose boundaries overlap (a farm drawn inside another's)."""
	total = 0.0
	for i in range(len(ring)):
		x1, y1 = ring[i - 1]
		x2, y2 = ring[i]
		total += x1 * y2 - x2 * y1
	return abs(total) / 2


def farm_at(lat, lng):
	"""The farm whose boundary contains the point, or None. Where boundaries
	overlap, the smallest (most specific) farm wins."""
	fields = _boundary_fields()
	if not fields:
		return None
	hits = []
	for row in frappe.get_all("Farm", fields=["name"] + fields):
		for field in fields:
			ring = _ring_from_geojson(row.get(field))
			if ring:
				if point_in_ring(lat, lng, ring):
					hits.append((_area(ring), row.name))
				break
	return min(hits)[1] if hits else None
