# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Patrol coverage maps for the security report: one picture per farm of the
Patrol Map's continuous coverage surface - the same pixels, influence
radius, fresh / not-patrolled hours and green-to-dark-red colour ramp as the
dashboard (Security Ops Settings > coverage) - inside the farm's boundary,
with no grid. Built only from the report period's pings, as of its end, the
way Playback builds it. Drawn server-side with matplotlib into a PNG, so the
PDF needs no map tiles or network."""

import base64
import io
import math
import zlib

import frappe

from upande_security.api.patrol_coverage import _load_farm_polygon, get_patrol_coverage_grid

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


def _h(hours):
	"""2 h, 7 days."""
	hours = float(hours or 0)
	if hours >= 48 and hours % 24 == 0:
		return f"{int(hours // 24)} days"
	return f"{hours:g} h"


def _draw(poly, surface, fresh_hours, stale_hours):
	import matplotlib

	matplotlib.use("Agg")
	import numpy as np
	from matplotlib.colors import LinearSegmentedColormap
	from matplotlib.figure import Figure

	nx, ny = surface["width"], surface["height"]
	raw = np.frombuffer(zlib.decompress(base64.b64decode(surface["data"])), dtype=np.uint8).reshape(ny, nx)
	values = np.ma.masked_equal(raw, 255).astype(float) / 254.0
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
	cax.set_xticks([0, 1])
	cax.set_xticklabels([f"Patrolled ≤ {_h(fresh_hours)} before the end", f"Not patrolled (≥ {_h(stale_hours)})"], fontsize=8)
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
			data = get_patrol_coverage_grid(farm, from_datetime=str(start), to_datetime=str(end))
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
				m.image = _draw(poly, data["surface"], data.get("fresh_hours"), data.get("stale_hours"))
			except Exception:
				frappe.log_error(f"Coverage map for {farm} failed")
				m.error = "The map could not be drawn."
		out.append(m)
	return out
