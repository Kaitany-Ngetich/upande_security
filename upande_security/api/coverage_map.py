# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Patrol coverage maps for the security report: one picture per farm of the
Patrol Map's grid cells, each filled by when a guard was last in it on the
dashboard's green-to-dark-red colour ramp, inside the farm's boundary - the
same cells the report's hectares count. Built only from the report window's pings (a day,
a night, a week), as of the window's end, and the ramp spans that window:
dark green is patrolled at its end, orange at its start, and dark red is
kept for ground nobody patrolled in it. Drawn server-side with matplotlib
into a PNG, so the PDF needs no map tiles or network."""

import base64
import io
import math
import zlib

import frappe

from upande_security.api.patrol_coverage import _load_farm_polygon, get_patrol_coverage_grid

# Where the window's start lands on the ramp: patrols from its first minute
# show orange, leaving dark red to mean not patrolled at all.
START_AT = 0.7
# The Patrol Map's ramp (patrol-map COV_STOPS): 0 = patrolled, 1 = not.
COV_STOPS = [(0, "#1a9850"), (0.25, "#a6d96a"), (0.5, "#fee08b"), (0.7, "#fdae61"), (0.86, "#d73027"), (1, "#67001f")]
OUTLINE = "#1f1f1c"
MAX_SIDE_IN = 7.0
DPI = 140


def _rings(geom):
	"""Exterior rings of a Polygon or MultiPolygon as (lng, lat) lists - a
	boundary drawn in Google Earth carries a height on every point."""
	if geom.is_empty:
		return []
	parts = getattr(geom, "geoms", [geom])
	return [[(c[0], c[1]) for c in p.exterior.coords] for p in parts if p.geom_type == "Polygon"]


def _when(dt, hours=0):
	"""at 06:00 for a day or night; 24 Oct 06:00 for a full day (both ends
	fall at the same hour); on 3 Nov for a window longer than a day."""
	dt = frappe.utils.get_datetime(dt)
	if hours > 24.5:
		return "on " + dt.strftime("%-d %b")
	if hours > 12.5:
		return dt.strftime("%-d %b %H:%M")
	return "at " + dt.strftime("%H:%M")


def _cell_polygons(geometry):
	"""A cell's GeoJSON geometry (clipped to the boundary, so possibly a
	MultiPolygon) as lists of (lng, lat) rings."""
	coords = geometry.get("coordinates") or []
	polys = coords if geometry.get("type") == "MultiPolygon" else [coords]
	return [[(c[0], c[1]) for c in p[0]] for p in polys if p]


def _draw(poly, surface, start, end, cells=None, stale_hours=None):
	import matplotlib

	matplotlib.use("Agg")
	import numpy as np
	from matplotlib.colors import LinearSegmentedColormap
	from matplotlib.figure import Figure

	cmap = LinearSegmentedColormap.from_list("coverage", COV_STOPS)
	cmap.set_bad((1, 1, 1, 0))

	west, east, south, north = surface["west"], surface["east"], surface["south"], surface["north"]
	kx = math.cos(math.radians((south + north) / 2))
	w_m, h_m = (east - west) * kx, (north - south)
	if w_m >= h_m:
		fw, fh = MAX_SIDE_IN, max(2.5, MAX_SIDE_IN * h_m / w_m)
	else:
		fh, fw = MAX_SIDE_IN, max(2.5, MAX_SIDE_IN * w_m / h_m)

	bar_in = 0.6
	fig = Figure(figsize=(fw, fh + bar_in), dpi=DPI)
	ax = fig.add_axes([0, bar_in / (fh + bar_in), 1, fh / (fh + bar_in)])
	if cells is not None:
		# One filled cell per grid square: its colour is how long before the
		# window's end a guard was last in it, dark red if nobody was.
		from matplotlib.collections import PolyCollection

		verts, colours = [], []
		for c in cells:
			h = c.get("best_hours")
			t = 1.0 if h is None or not stale_hours else min(1.0, max(0.0, h / stale_hours))
			for ring in _cell_polygons(c.get("geometry") or {}):
				verts.append(ring)
				colours.append(cmap(t))
		# Edges in each cell's own colour: no grid lines, and no hairline
		# gaps between neighbouring cells.
		ax.add_collection(PolyCollection(verts, facecolors=colours, edgecolors=colours, linewidths=0.4,
			antialiased=False))
	else:
		nx, ny = surface["width"], surface["height"]
		raw = np.frombuffer(zlib.decompress(base64.b64decode(surface["data"])), dtype=np.uint8).reshape(ny, nx)
		values = np.ma.masked_equal(raw, 255).astype(float) / 254.0
		ax.imshow(values, cmap=cmap, vmin=0, vmax=1, extent=(west, east, south, north),
			interpolation="bilinear", origin="upper")
	for ring in _rings(poly):
		xs, ys = zip(*ring)
		ax.plot(xs, ys, color=OUTLINE, linewidth=1.2)
	pad_x, pad_y = (east - west) * 0.02, (north - south) * 0.02
	ax.set_xlim(west - pad_x, east + pad_x)
	ax.set_ylim(south - pad_y, north + pad_y)
	ax.set_aspect(1 / kx)
	ax.axis("off")

	# The ramp as a legend bar, labelled at both ends like the dashboard's.
	cax = fig.add_axes([0.2, 0.32 * bar_in / (fh + bar_in), 0.6, 0.18 * bar_in / (fh + bar_in)])
	cax.imshow(np.linspace(0, 1, 256)[None, :], cmap=cmap, aspect="auto", extent=(0, 1, 0, 1))
	cax.set_yticks([])
	cax.set_xticks([0, START_AT, 1])
	hours = (frappe.utils.get_datetime(end) - frappe.utils.get_datetime(start)).total_seconds() / 3600
	cax.set_xticklabels([f"Patrolled {_when(end, hours)}", f"Patrolled {_when(start, hours)}", "Not patrolled"],
		fontsize=7.5)
	cax.tick_params(length=0, pad=2)
	for spine in cax.spines.values():
		spine.set_visible(False)

	buf = io.BytesIO()
	fig.savefig(buf, format="png", dpi=DPI, facecolor="white")
	return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def farm_coverage_maps(farms, start, end, farm_rows=None):
	"""[{farm, image, area_ha, covered_ha, coverage_pct, error}] for each
	farm, in order, over start..end. farm_rows is the guard ranking's
	per-farm totals: its hectares and percentage are what the map's caption
	shows, so the caption agrees with the Patrols table."""
	totals = {f["farm"]: f for f in (farm_rows or [])}
	out = []
	for farm in farms:
		m = frappe._dict(farm=farm, image=None, error=None)
		t = totals.get(farm) or {}
		m.area_ha, m.covered_ha, m.coverage_pct = t.get("area_ha"), t.get("covered_ha"), t.get("coverage_pct")
		try:
			poly = _load_farm_polygon(farm)
			window_h = max((frappe.utils.get_datetime(end) - frappe.utils.get_datetime(start)).total_seconds() / 3600, 1)
			stale_h = window_h / START_AT
			data = get_patrol_coverage_grid(farm, from_datetime=str(start), to_datetime=str(end),
				ramp_hours=(0.0, stale_h))
		except Exception:
			frappe.log_error(f"Coverage map for {farm} failed")
			m.error = "The map could not be drawn."
			out.append(m)
			continue
		if not data.get("enabled"):
			m.error = "Coverage maps are switched off in Security Ops Settings."
		elif data.get("error") or poly is None:
			m.error = data.get("error") or "No boundary on record."
		else:
			if m.coverage_pct is None:
				# A farm nobody patrolled has no ranking row: nothing covered.
				m.coverage_pct, m.covered_ha = 0.0, 0.0
			if m.area_ha is None:
				minx, miny, maxx, maxy = poly.bounds
				m.area_ha = round(poly.area * 111320 * math.cos(math.radians((miny + maxy) / 2)) * 110540 / 10000, 2)
			try:
				m.image = _draw(poly, data["surface"], start, end, cells=data.get("cells"), stale_hours=stale_h)
			except Exception:
				frappe.log_error(f"Coverage map for {farm} failed")
				m.error = "The map could not be drawn."
		out.append(m)
	return out
