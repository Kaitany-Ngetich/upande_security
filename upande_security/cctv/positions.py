# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Placing cameras on the site map, and proposing which cameras are next to
each other (CCTV Camera Link) from those positions."""

import frappe
from frappe import _

from upande_security.cctv.guard_match import _distance_m

MANAGERS = ("System Manager", "Security Head", "Security Manager")
WALK_FAST_MPS = 2.0   # brisk walk / jog: the shortest believable time between two views
WALK_SLOW_MPS = 0.7   # stroll; plus a pause allowance below
PAUSE_SECONDS = 60


@frappe.whitelist()
def set_camera_position(camera, latitude, longitude, bearing=None, field_of_view=None, range_m=None, note=None):
	"""From the site map's Place cameras mode."""
	frappe.only_for(MANAGERS)
	doc = frappe.get_doc("CCTV Camera", camera)
	doc.latitude, doc.longitude = float(latitude), float(longitude)
	doc.location = None  # rebuilt from the numbers
	if bearing not in (None, ""):
		doc.bearing_deg = int(float(bearing))
	if field_of_view not in (None, ""):
		doc.field_of_view_deg = int(float(field_of_view))
	if range_m not in (None, ""):
		doc.view_range_m = int(float(range_m))
	if note is not None:
		doc.position_note = note
	doc.save()
	return {"ok": True, "camera": doc.name, "latitude": doc.latitude, "longitude": doc.longitude, "bearing_deg": doc.bearing_deg}


@frappe.whitelist()
def suggest_links(farm, max_distance_m=200, create=0):
	"""Pairs of placed cameras within max_distance_m of each other, with walking
	times for CCTV Camera Link. create=1 adds the ones that do not exist yet."""
	frappe.only_for(MANAGERS)
	cams = [c for c in frappe.get_all("CCTV Camera", filters={"farm": farm, "enabled": 1},
		fields=["name", "camera_name", "latitude", "longitude"]) if c.latitude and c.longitude]
	existing = {(l.from_camera, l.to_camera) for l in frappe.get_all("CCTV Camera Link", fields=["from_camera", "to_camera"])}
	out, made = [], []
	for i, a in enumerate(cams):
		for b in cams[i + 1:]:
			d = _distance_m(a.latitude, a.longitude, b.latitude, b.longitude)
			if d > float(max_distance_m):
				continue
			lo = max(3, int(d / WALK_FAST_MPS))
			hi = int(d / WALK_SLOW_MPS) + PAUSE_SECONDS
			have = (a.name, b.name) in existing or (b.name, a.name) in existing
			row = {"from_camera": a.name, "from_name": a.camera_name, "to_camera": b.name, "to_name": b.camera_name,
				"distance_m": round(d), "min_seconds": lo, "max_seconds": hi, "exists": have}
			out.append(row)
			if int(create) and not have:
				doc = frappe.get_doc({"doctype": "CCTV Camera Link", "from_camera": a.name, "to_camera": b.name, "bidirectional": 1,
					"min_seconds": lo, "max_seconds": hi})
				doc.insert()
				made.append(doc.name)
	out.sort(key=lambda r: r["distance_m"])
	return {"pairs": out, "created": len(made), "unplaced": frappe.db.count("CCTV Camera", {"farm": farm, "enabled": 1}) - len(cams)}
