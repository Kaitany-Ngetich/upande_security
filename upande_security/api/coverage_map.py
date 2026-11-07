# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Patrol coverage maps for the security report: one picture per farm of
its boundary cut into the coverage grid's squares (the same squares and size
as the dashboard's Patrol Map and the report's "Area patrolled"), green
where any guard's GPS track entered the square during the report period and
red where nobody did. Drawn server-side with matplotlib into a PNG, so the
PDF needs no map tiles or network."""

import base64
import io
import math

import frappe

from upande_security.api.patrol_coverage import _build_cells, _coverage_settings, _load_farm_polygon

PATROLLED = "#4caf6a"
NOT_PATROLLED = "#e57368"
OUTLINE = "#1f1f1c"
# Longest side of the drawing, in inches at DPI - about a full A4 width.
MAX_SIDE_IN = 7.0
DPI = 140


def _hectares(poly):
	minx, miny, maxx, maxy = poly.bounds
	lat = math.radians((miny + maxy) / 2)
	return poly.area * 111320 * math.cos(lat) * 110540 / 10000


def _rings(geom):
	"""Exterior rings of a Polygon or MultiPolygon as coordinate lists."""
	if geom.is_empty:
		return []
	parts = getattr(geom, "geoms", [geom])
	# Boundaries drawn in Google Earth carry a height on every point; the
	# map only needs longitude and latitude.
	return [[(c[0], c[1]) for c in p.exterior.coords] for p in parts if p.geom_type == "Polygon"]


def _draw(farm, poly, cells, covered):
	import matplotlib

	matplotlib.use("Agg")
	from matplotlib.collections import PolyCollection
	from matplotlib.figure import Figure
	from matplotlib.patches import Patch

	minx, miny, maxx, maxy = poly.bounds
	kx = math.cos(math.radians((miny + maxy) / 2))
	w_m, h_m = (maxx - minx) * kx, (maxy - miny)
	if w_m >= h_m:
		fw, fh = MAX_SIDE_IN, max(2.5, MAX_SIDE_IN * h_m / w_m)
	else:
		fh, fw = MAX_SIDE_IN, max(2.5, MAX_SIDE_IN * w_m / h_m)

	verts, colours = [], []
	for (i, j), cell in cells.items():
		colour = PATROLLED if f"{i}-{j}" in covered else NOT_PATROLLED
		for ring in _rings(cell["geom"]):
			verts.append(ring)
			colours.append(colour)

	fig = Figure(figsize=(fw, fh + 0.45), dpi=DPI)
	ax = fig.add_axes([0, 0.45 / (fh + 0.45), 1, fh / (fh + 0.45)])
	ax.add_collection(PolyCollection(verts, facecolors=colours, edgecolors="#ffffff", linewidths=0.25))
	for ring in _rings(poly):
		xs, ys = zip(*ring)
		ax.plot(xs, ys, color=OUTLINE, linewidth=1.2)
	pad_x, pad_y = (maxx - minx) * 0.02, (maxy - miny) * 0.02
	ax.set_xlim(minx - pad_x, maxx + pad_x)
	ax.set_ylim(miny - pad_y, maxy + pad_y)
	ax.set_aspect(1 / kx)
	ax.axis("off")
	fig.legend(
		handles=[Patch(facecolor=PATROLLED, label="Patrolled"), Patch(facecolor=NOT_PATROLLED, label="Not patrolled")],
		loc="lower center", ncol=2, frameon=False, fontsize=9,
	)
	buf = io.BytesIO()
	fig.savefig(buf, format="png", dpi=DPI, facecolor="white")
	return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def farm_coverage_maps(farms, covered_cells, farm_rows=None):
	"""[{farm, image, cells, covered, area_ha, covered_ha, coverage_pct,
	error}] for each farm, in order. covered_cells is the ranking's
	{farm: [cell keys]}; farm_rows its per-farm totals, whose hectares and
	percentage are used when present so the map agrees with the table."""
	width, height = _coverage_settings()[:2]
	totals = {f["farm"]: f for f in (farm_rows or [])}
	out = []
	for farm in farms:
		m = frappe._dict(farm=farm, image=None, error=None)
		try:
			poly = _load_farm_polygon(farm)
		except Exception:
			poly = None
		if poly is None:
			m.error = "No boundary on record."
			out.append(m)
			continue
		cells, _grid = _build_cells(poly, width, height)
		if not cells:
			m.error = "Too large to draw at this square size."
			out.append(m)
			continue
		keys = {f"{i}-{j}" for i, j in cells}
		covered = set(covered_cells.get(farm) or []) & keys
		m.cells, m.covered = len(keys), len(covered)
		t = totals.get(farm) or {}
		m.area_ha = t.get("area_ha") or round(_hectares(poly), 2)
		m.coverage_pct = t.get("coverage_pct") if t.get("coverage_pct") is not None else round(100 * len(covered) / len(keys), 1)
		m.covered_ha = t.get("covered_ha") if t.get("covered_ha") is not None else round(m.area_ha * m.coverage_pct / 100, 2)
		try:
			m.image = _draw(farm, poly, cells, covered)
		except Exception:
			frappe.log_error(f"Coverage map for {farm} failed")
			m.error = "The map could not be drawn."
		out.append(m)
	return out
