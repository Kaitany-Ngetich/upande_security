import json
import math

import frappe
from shapely.geometry import LineString, Polygon
from upande_spatial.api.epanet import add_element, create_network

DEMAND_RATE_LPS_PER_HA = 0.4
N_BANDS = 7
MIN_BAND_WIDTH_M = 30


def m_per_deg(lat_mid):
    return (111320 * math.cos(math.radians(lat_mid)), 110540)


def plan_geometry():
    """Pure geometry pass, no DB writes - returns everything needed to
    build the network, including the terminal-junction count so demand
    per junction can be computed before any element is actually created."""
    sf = frappe.db.get_value(
        "Spatial Feature",
        {"reference_doctype": "Farm", "reference_name": "Kapkolia", "feature_role": "Boundary"},
        "geometry",
    )
    geom = json.loads(sf)
    raw_coords = geom["features"][0]["geometry"]["coordinates"][0]
    coords_2d = [(c[0], c[1]) for c in raw_coords]
    poly = Polygon(coords_2d)
    minx, miny, maxx, maxy = poly.bounds
    lat_mid = (miny + maxy) / 2
    mx, my = m_per_deg(lat_mid)

    south_vertex = min(coords_2d, key=lambda c: c[1])

    band_ys = [miny + (maxy - miny) * (i + 0.5) / N_BANDS for i in range(N_BANDS)]
    spine_points = []
    band_segments = []
    for y in band_ys:
        band_line = LineString([(minx - 0.001, y), (maxx + 0.001, y)])
        inter = poly.intersection(band_line)
        segs = []
        if inter.geom_type == "LineString":
            segs = [inter]
        elif inter.geom_type == "MultiLineString":
            segs = list(inter.geoms)
        if not segs:
            continue
        longest = max(segs, key=lambda s: s.length)
        (x0, y0), (x1, y1) = longest.coords[0], longest.coords[-1]
        width_m = abs(x1 - x0) * mx
        if width_m < MIN_BAND_WIDTH_M:
            continue
        mid = longest.interpolate(0.5, normalized=True)
        spine_points.append((mid.x, mid.y))
        band_segments.append(((min(x0, x1), y), (max(x0, x1), y)))

    branches = []  # (spine_point_idx, label, end_x, end_y)
    for i, (sp, (west, east)) in enumerate(zip(spine_points, band_segments)):
        for label, edge in (("W", west), ("E", east)):
            ex = sp[0] + (edge[0] - sp[0]) * 0.85
            ey = sp[1] + (edge[1] - sp[1]) * 0.85
            branch_len_m = (((ex - sp[0]) * mx) ** 2 + ((ey - sp[1]) * my) ** 2) ** 0.5
            if branch_len_m < MIN_BAND_WIDTH_M:
                continue
            branches.append((i, label, ex, ey))

    total_area_ha = poly.area * mx * my / 10000
    per_junction_ha = total_area_ha / len(branches) if branches else 0
    per_junction_demand = round(per_junction_ha * DEMAND_RATE_LPS_PER_HA, 3)

    return {
        "south_vertex": south_vertex,
        "spine_points": spine_points,
        "branches": branches,
        "total_area_ha": total_area_ha,
        "per_junction_demand": per_junction_demand,
        "miny": miny, "maxy": maxy,
    }


def run():
    plan = plan_geometry()
    print(f"reservoir at {plan['south_vertex']}")
    print(f"{len(plan['spine_points'])} spine waypoints, {len(plan['branches'])} branches")
    print(f"total area: {plan['total_area_ha']:.2f} ha, demand/junction: {plan['per_junction_demand']} L/s")

    network = create_network(
        network_name="Kapkolia Irrigation Network",
        reference_doctype="Farm",
        reference_name="Kapkolia",
    )["name"]
    print("created network:", network)

    def pt(role, lon, lat, title, props):
        return add_element(
            network, role, json.dumps({"type": "Point", "coordinates": [lon, lat]}), title, json.dumps(props)
        )["name"]

    def line(role, a, b, title, props):
        add_element(
            network, role, json.dumps({"type": "LineString", "coordinates": [list(a), list(b)]}), title, json.dumps(props)
        )

    miny, maxy = plan["miny"], plan["maxy"]

    def elev_for(lat):
        t = (lat - miny) / (maxy - miny) if maxy > miny else 0
        return round(15 - t * 8, 1)

    south_vertex = plan["south_vertex"]
    pt("Reservoir", south_vertex[0], south_vertex[1], "Kapkolia Source", {"base_head_m": 70})

    spine_names = []
    for i, sp in enumerate(plan["spine_points"]):
        name = pt("Junction", sp[0], sp[1], f"Mainline Node {i+1}", {"elevation_m": elev_for(sp[1]), "base_demand_lps": 0})
        spine_names.append(name)

    prev, prev_name = south_vertex, "Kapkolia Source"
    for name, sp in zip(spine_names, plan["spine_points"]):
        line("Pipe", prev, sp, f"Mainline {prev_name}-{name}", {"diameter_mm": 150, "roughness": 145})
        prev, prev_name = sp, name

    demand = plan["per_junction_demand"]
    branch_count = 0
    for spine_idx, label, ex, ey in plan["branches"]:
        sp = plan["spine_points"][spine_idx]
        spine_name = spine_names[spine_idx]
        end_name = pt(
            "Junction", ex, ey, f"Block Inlet {spine_idx+1}{label}",
            {"elevation_m": elev_for(ey), "base_demand_lps": demand},
        )
        line("Pipe", sp, (ex, ey), f"Sub-main {spine_name}-{label}", {"diameter_mm": 100, "roughness": 145})
        branch_count += 1

    frappe.db.commit()
    print(f"done: 1 reservoir, {len(spine_names)} mainline junctions, {branch_count} block-inlet junctions")
    print(f"total nodes: {1 + len(spine_names) + branch_count}, total pipes: {len(spine_names) + branch_count}")
