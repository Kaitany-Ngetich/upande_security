# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""CCTV Camera: a code people can say on the radio, and a position on the map.

NAMING
camera_code = SITE-ROLE-NN, e.g. KPK-GATE-01, KPK-COLD-02: the site's Farm
abbreviation (else a short farm_code, else its first three letters), a short
word for the camera's role, and the next free number for that pair. It is
the record name, so alerts, links and URLs show it. camera_name stays the
plain-language label ("Main gate - incoming lane").

POSITION
The Location map field (Geolocation) and Latitude/Longitude are kept in step:
place the marker or type the numbers. Facing, field of view and range draw
the camera's view cone on the site map, and the position is what guard
matching (distance to the camera) and camera-link suggestions use.
"""

import json
import re

import frappe
from frappe import _
from frappe.model.document import Document

ROLE_CODES = {
	"Gate": "GATE", "Entry": "GIN", "Exit": "GOUT", "Parking": "PARK", "Dock": "DOCK", "Door": "DOOR",
	"Corridor": "CORR", "Perimeter": "PERI", "Cold Room": "COLD", "Overview": "VIEW", "Other": "CAM",
}


def site_code(farm):
	if not farm:
		return "CAM"
	row = frappe.db.get_value("Farm", farm, ["abbreviation", "farm_code"], as_dict=True) or {}
	clean = lambda v: re.sub(r"[^A-Z0-9]", "", str(v or "").upper())  # noqa: E731
	# The abbreviation (KPK) first. farm_code is often a registration number
	# (KE/030/0809/047), so it is used only when it is already short.
	for raw in (row.get("abbreviation"), row.get("farm_code") if len(clean(row.get("farm_code"))) <= 5 else None, farm[:3]):
		if clean(raw):
			return clean(raw)[:6]
	return "CAM"


def next_code(farm, role):
	prefix = f"{site_code(farm)}-{ROLE_CODES.get(role or 'Overview', 'CAM')}-"
	taken = frappe.get_all("CCTV Camera", filters={"name": ["like", f"{prefix}%"]}, pluck="name")
	nums = [int(m.group(1)) for n in taken if (m := re.match(re.escape(prefix) + r"(\d+)$", n))]
	return f"{prefix}{(max(nums) + 1) if nums else 1:02d}"


class CCTVCamera(Document):
	def autoname(self):
		if not self.farm and self.server:
			self.farm = frappe.db.get_value("CCTV Server", self.server, "farm")
		code = (self.camera_code or "").strip().upper().replace(" ", "-")
		self.camera_code = code or next_code(self.farm, self.role)
		self.name = self.camera_code

	def validate(self):
		if self.camera_code and not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,30}", self.camera_code.upper()):
			frappe.throw(_("Camera Code: letters, digits and dashes only, e.g. KPK-GATE-01."))
		self._sync_position()
		if self.bearing_deg is not None and self.bearing_deg != "":
			self.bearing_deg = int(self.bearing_deg) % 360
		if self.field_of_view_deg and not 5 <= int(self.field_of_view_deg) <= 360:
			frappe.throw(_("Field of view is between 5 and 360 degrees."))
		if self.view_range_m and int(self.view_range_m) < 0:
			frappe.throw(_("Range cannot be negative."))
		self._check_licence()

	def _sync_position(self):
		"""Map marker <-> latitude/longitude, whichever was changed."""
		point = _point(self.location)
		moved_map = self.has_value_changed("location") and point
		if moved_map:
			self.longitude, self.latitude = point
		elif self.latitude and self.longitude and (self.has_value_changed("latitude") or self.has_value_changed("longitude") or not point):
			self.location = json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
				"geometry": {"type": "Point", "coordinates": [float(self.longitude), float(self.latitude)]}}]})
		if self.latitude and not -90 <= float(self.latitude) <= 90 or self.longitude and not -180 <= float(self.longitude) <= 180:
			frappe.throw(_("Latitude must be -90..90 and longitude -180..180."))

	def _check_licence(self):
		if self.enabled and (self.is_new() or self.has_value_changed("enabled")):
			from upande_security.cctv.settings import max_cameras

			farm = self.farm or frappe.db.get_value("CCTV Server", self.server, "farm")
			limit = max_cameras(farm)
			if limit and frappe.db.count("CCTV Camera", {"farm": farm, "enabled": 1, "name": ["!=", self.name or ""]}) >= limit:
				frappe.throw(_("The licence for {0} allows {1} cameras.").format(farm, limit))


def _point(value):
	"""(lng, lat) of the first point in a Geolocation value, or None."""
	if not value:
		return None
	try:
		g = json.loads(value) if isinstance(value, str) else value
		feats = g.get("features") if g.get("type") == "FeatureCollection" else [g]
		for f in feats or []:
			geom = f.get("geometry") or {}
			if geom.get("type") == "Point":
				lng, lat = geom["coordinates"][:2]
				return float(lng), float(lat)
	except Exception:
		return None
	return None
