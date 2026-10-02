# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Patrol coverage grid for the Patrol Map: a farm's boundary cut into
rectangular cells (clipped to the boundary, nothing outside it), each tagged with how many
hours ago a guard's GPS ping last landed in it. The map colors cells on a ramp
from green (patrolled within coverage_fresh_hours) to red (not patrolled for
coverage_stale_hours or longer) - both thresholds and the cell width/height
live in Security Ops Settings."""

import base64
import json
import math
import zlib

import numpy as np
import shapely

import frappe
from frappe import _
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import unary_union
from shapely.prepared import prep

from upande_security.api.feature_flags import is_feature_enabled
from upande_security.api.security_dashboard import _patrol_float

# Above this a farm/cell-size combination is refused rather than rendered:
# Geofence Test Farm's boundary is a ~1.2M ha test square, which at 50 m would
# be ~5 billion cells.
MAX_CELLS = 6000
# Same cutoff fetchPatrolData uses to drop coarse network/wifi fixes - a
# 300 m-accuracy ping says nothing about which 50 m cell a guard was in.
MAX_ACCURACY_M = 100
# Longest side of the coverage surface in pixels - keeps the payload and
# the per-ping update cost bounded regardless of farm size.
MAX_SURFACE_PX = 800
# A clipped edge sliver smaller than this share of a full cell is dropped -
# too small to see or to patrol meaningfully.
MIN_EDGE_FRACTION = 0.05


def _coverage_settings():
	s = frappe.get_single("Security Ops Settings")
	width = int(s.coverage_grid_cell_width_m or 50)
	height = int(s.coverage_grid_cell_height_m or 50)
	fresh = float(s.coverage_fresh_hours or 2)
	stale = float(s.coverage_stale_hours or 12)
	radius = int(s.coverage_influence_radius_m or 50)
	return width, height, fresh, max(stale, fresh + 0.5), max(radius, 1)


def _load_farm_polygon(farm):
	"""Farm.boundary_geojson (or Geolocation `location` on sites without it,
	same precedence as get_farm_boundaries) as one shapely polygon. The value
	is either inline GeoJSON text or the URL of an uploaded File."""
	meta = frappe.get_meta("Farm")
	field = "boundary_geojson" if meta.has_field("boundary_geojson") else "location"
	if not meta.has_field(field):
		return None
	raw = (frappe.db.get_value("Farm", farm, field) or "").strip()
	if not raw:
		return None
	if raw[0] not in "{[":
		file_name = frappe.db.get_value("File", {"file_url": raw}, "name")
		if not file_name:
			return None
		raw = frappe.get_doc("File", file_name).get_content()
		if isinstance(raw, bytes):
			raw = raw.decode("utf-8")
	data = json.loads(raw)

	if data.get("type") == "FeatureCollection":
		geoms = [f.get("geometry") for f in data.get("features") or []]
	elif data.get("type") == "Feature":
		geoms = [data.get("geometry")]
	else:
		geoms = [data]
	polys = [shape(g) for g in geoms if g and g.get("type") in ("Polygon", "MultiPolygon")]
	if not polys:
		return None
	poly = unary_union(polys)
	if not poly.is_valid:
		poly = poly.buffer(0)
	return None if poly.is_empty else poly


def boundary_filter_area(farm, poly=None):
	"""The selected farm's boundary grown by Boundary Tolerance, prepared for
	fast point tests - or None when the Hide Patrol Points Outside Farm
	Boundary flag is off or the farm has no usable boundary. Shared by the
	coverage grid and fetchPatrolData so paths and coverage always agree."""
	if not is_feature_enabled("feature_patrol_boundary_filter"):
		return None
	if poly is None:
		try:
			poly = _load_farm_polygon(farm)
		except Exception:
			return None
	if poly is None:
		return None
	tol = frappe.db.get_single_value("Security Ops Settings", "coverage_boundary_tolerance_m")
	tol = 5 if tol is None else max(0, int(tol))
	return prep(poly.buffer(tol / 111320.0) if tol else poly)


def _build_cells(poly, width_m, height_m):
	"""Rectangular cells (width east-west, height north-south) in a local equirectangular projection (fine at farm
	scale), anchored to the boundary's south-west corner. Returns
	(cells, grid) where cells maps (i, j) -> {"geom", "full"} and grid holds
	what's needed to bin a point into (i, j) arithmetically."""
	minx, miny, maxx, maxy = poly.bounds
	lat_mid = (miny + maxy) / 2
	dx = width_m / (111320 * math.cos(math.radians(lat_mid)))
	dy = height_m / 110540
	nx = max(1, math.ceil((maxx - minx) / dx))
	ny = max(1, math.ceil((maxy - miny) / dy))
	if nx * ny > MAX_CELLS * 4:
		return None, None

	prepared = prep(poly)
	cells = {}
	full_area = dx * dy
	for i in range(nx):
		for j in range(ny):
			cell = box(minx + i * dx, miny + j * dy, minx + (i + 1) * dx, miny + (j + 1) * dy)
			if not prepared.intersects(cell):
				continue
			if prepared.contains(cell):
				cells[(i, j)] = {"geom": cell, "full": True}
				continue
			part = poly.intersection(cell)
			if part.is_empty or part.area < full_area * MIN_EDGE_FRACTION:
				continue
			cells[(i, j)] = {"geom": part, "full": False}
			if len(cells) > MAX_CELLS:
				return None, None
	return cells, {"minx": minx, "miny": miny, "dx": dx, "dy": dy, "nx": nx, "ny": ny}


def _as_of(date):
	"""Reference moment cells are aged against: now for today, otherwise the
	end of the chosen day - so a past date shows coverage as it stood then."""
	now = frappe.utils.now_datetime()
	if not date:
		return now
	day = frappe.utils.getdate(date)
	if day >= now.date():
		return now
	return frappe.utils.get_datetime(str(day) + " 23:59:59")


@frappe.whitelist()
def get_patrol_coverage_grid(farm, date=None):
	"""Coverage is a continuous surface, not a per-cell value: every pixel
	(a few meters across) gets an effective age from the nearest pings, so
	the half of a cell beside a patrol path reads fresh and the far half
	doesn't. A ping of age a at distance d counts as a + (d / radius) *
	(stale - fresh); each pixel keeps the smallest value any ping gives it.
	The grid only partitions the farm into zones, each summarised from the
	pixels inside it.

	The surface is returned as one byte per pixel, row 0 at the north edge,
	zlib-compressed: 0-254 is the position on the fresh-to-stale ramp, 255
	is outside the farm boundary."""
	if not is_feature_enabled("feature_patrol_coverage_grid"):
		return {"enabled": False}
	if not frappe.has_permission("Patrol GPS Log", ptype="read"):
		frappe.throw(_("You do not have permission to view Patrol GPS Logs."), frappe.PermissionError)
	# Points are fetched by time and location below, not through get_list, so
	# per-farm User Permissions are enforced here on the farm itself.
	if not frappe.has_permission("Farm", ptype="read", doc=farm):
		frappe.throw(_("You do not have permission to view {0}.").format(farm), frappe.PermissionError)

	cell_width_m, cell_height_m, fresh_hours, stale_hours, radius_m = _coverage_settings()
	base = {
		"enabled": True,
		"farm": farm,
		"cell_width_m": cell_width_m,
		"cell_height_m": cell_height_m,
		"fresh_hours": fresh_hours,
		"stale_hours": stale_hours,
		"influence_radius_m": radius_m,
	}

	try:
		poly = _load_farm_polygon(farm)
	except Exception as e:
		frappe.log_error("get_patrol_coverage_grid boundary: " + str(farm), str(e))
		poly = None
	if poly is None:
		return {**base, "error": _("{0} has no usable boundary on record.").format(farm)}

	cells, grid = _build_cells(poly, cell_width_m, cell_height_m)
	if cells is None:
		return {
			**base,
			"error": _("{0} is too large for a {1} x {2} m grid (over {3} cells).").format(
				farm, cell_width_m, cell_height_m, MAX_CELLS
			),
		}

	as_of = _as_of(date)
	since = frappe.utils.add_to_date(as_of, hours=-stale_hours)
	# Read through the captured_at_coverage covering index (see
	# patrol_gps_log.on_doctype_update): ~0.1 s for a 2-day window on ~500k
	# rows, versus 20-80 s when MariaDB picks a full scan or has to fetch
	# rows scattered across a table bigger than the buffer pool.
	force = ""
	if frappe.db.db_type == "mariadb":
		for index in ("captured_at_coverage", "captured_at_index"):
			if frappe.db.has_index("tabPatrol GPS Log", index):
				force = " force index (" + index + ")"
				break
	points = frappe.db.sql(
		"select captured_at, latitude, longitude, gps_accuracy"
		" from `tabPatrol GPS Log`" + force + " where captured_at between %s and %s",
		(since, as_of),
		as_dict=True,
	)

	# Local meters from the grid's south-west corner: cell (i, j) spans
	# [i*W, (i+1)*W] x [j*H, (j+1)*H], and the surface covers the same extent.
	W, H = float(cell_width_m), float(cell_height_m)
	mx, my = W / grid["dx"], H / grid["dy"]
	ext_w, ext_h = grid["nx"] * W, grid["ny"] * H
	px_m = max(1.0, max(ext_w, ext_h) / MAX_SURFACE_PX)
	NX, NY = int(math.ceil(ext_w / px_m)), int(math.ceil(ext_h / px_m))
	span = stale_hours - fresh_hours

	# Pixel centres, row 0 = north. Mask = inside the farm boundary.
	xs = (np.arange(NX) + 0.5) * px_m
	ys = ext_h - (np.arange(NY) + 0.5) * px_m
	lng_c = grid["minx"] + xs / mx
	lat_c = grid["miny"] + ys / my
	mask = shapely.contains_xy(poly, lng_c[None, :], lat_c[:, None])

	E = np.full((NY, NX), np.inf, dtype=np.float64)
	rpx = int(math.ceil(radius_m / px_m))
	minx, miny, maxx, maxy = poly.bounds
	pad_x, pad_y = radius_m / mx, radius_m / my
	area = boundary_filter_area(farm, poly)
	direct = {}
	for p in points:
		lat = _patrol_float(p.get("latitude"))
		lng = _patrol_float(p.get("longitude"))
		if lat is None or lng is None:
			continue
		if not (minx - pad_x <= lng <= maxx + pad_x and miny - pad_y <= lat <= maxy + pad_y):
			continue
		if area is not None and not area.contains(Point(lng, lat)):
			continue
		acc = _patrol_float(p.get("gps_accuracy"))
		if acc is not None and acc > MAX_ACCURACY_M:
			continue
		ts = frappe.utils.get_datetime(p.get("captured_at"))
		age = max(0.0, (as_of - ts).total_seconds() / 3600)
		x = (lng - grid["minx"]) * mx
		y = (lat - grid["miny"]) * my

		key = (int(x // W), int(y // H))
		home = cells.get(key)
		if home and (home["full"] or home["geom"].intersects(Point(lng, lat))):
			d = direct.setdefault(key, {"last": None, "pings": 0})
			d["pings"] += 1
			if d["last"] is None or ts > d["last"]:
				d["last"] = ts

		col = int(x // px_m)
		row = int((ext_h - y) // px_m)
		c0, c1 = max(0, col - rpx), min(NX, col + rpx + 1)
		r0, r1 = max(0, row - rpx), min(NY, row + rpx + 1)
		if c0 >= c1 or r0 >= r1:
			continue
		dist = np.hypot(xs[c0:c1][None, :] - x, ys[r0:r1][:, None] - y)
		eff = np.where(dist <= radius_m, age + (dist / radius_m) * span, np.inf)
		np.minimum(E[r0:r1, c0:c1], eff, out=E[r0:r1, c0:c1])

	T = np.clip((E - fresh_hours) / span, 0.0, 1.0)
	T[~np.isfinite(E)] = 1.0
	surface = np.round(T * 254).astype(np.uint8)
	surface[~mask] = 255

	out = []
	inside = int(mask.sum())
	fresh_px = int(((E <= fresh_hours) & mask).sum())
	covered_px = int(((E < stale_hours) & mask).sum())
	zones = {"fresh": 0, "partial": 0, "unpatrolled": 0}
	for (i, j), cell in cells.items():
		c0, c1 = int(i * W // px_m), int(min(NX, math.ceil((i + 1) * W / px_m)))
		r0 = int((ext_h - (j + 1) * H) // px_m)
		r1 = int(min(NY, math.ceil((ext_h - j * H) / px_m)))
		m = mask[r0:r1, c0:c1]
		n = int(m.sum())
		e = E[r0:r1, c0:c1][m]
		t = T[r0:r1, c0:c1][m]
		fresh_share = float((e <= fresh_hours).mean()) if n else 0.0
		covered_share = float((e < stale_hours).mean()) if n else 0.0
		mean_t = float(t.mean()) if n else 1.0
		best = float(e.min()) if n and np.isfinite(e.min()) else None
		if mean_t <= 0.0001:
			zones["fresh"] += 1
		elif covered_share > 0:
			zones["partial"] += 1
		else:
			zones["unpatrolled"] += 1
		d = direct.get((i, j))
		out.append({
			"id": f"{i}-{j}",
			"geometry": mapping(cell["geom"]),
			"mean_t": round(mean_t, 4),
			"fresh_share": round(fresh_share, 3),
			"covered_share": round(covered_share, 3),
			"best_hours": round(best, 2) if best is not None and best < stale_hours else None,
			"last_seen": str(d["last"]) if d else None,
			"pings": d["pings"] if d else 0,
		})

	return {
		**base,
		"as_of": str(as_of),
		"surface": {
			"width": NX,
			"height": NY,
			"pixel_m": round(px_m, 3),
			"west": grid["minx"],
			"south": grid["miny"] + (ext_h - NY * px_m) / my,
			"east": grid["minx"] + NX * px_m / mx,
			"north": grid["miny"] + ext_h / my,
			"data": base64.b64encode(zlib.compress(surface.tobytes(), 6)).decode(),
		},
		"cells": out,
		"summary": {
			"cells": len(out),
			**zones,
			"fresh_pct": round(100 * fresh_px / inside, 1) if inside else 0,
			"covered_pct": round(100 * covered_px / inside, 1) if inside else 0,
		},
	}
