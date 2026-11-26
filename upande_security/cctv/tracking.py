# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Cross-camera tracks: chaining sightings across cameras into one trail.

NAMED people (face match) chain trivially: one Active track per person per
site, extended by each sighting.

ANONYMOUS people (person detected, no identity) chain by topology and time,
not by appearance: CCTV Camera Link says which cameras are next to each
other and how long it takes to walk between them. A new sighting at camera
B joins the track last seen at a linked camera A only when it falls inside
that link's [min, max] travel time AND exactly one track fits. Two or more
fitting tracks = ambiguous, so it starts a new track rather than guess.
Confidence decays with each hop. The result is "probably the same person",
shown as such - never an identity.

Tracks close after the presence window with no new sighting.
"""

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime, time_diff_in_seconds

from upande_security.cctv.settings import get_settings

HOP_DECAY = 0.85


def _links_into(camera):
	"""{from_camera: (min_s, max_s)} for cameras that lead to `camera`."""
	out = {}
	for l in frappe.get_all("CCTV Camera Link", filters={"to_camera": camera}, fields=["from_camera", "min_seconds", "max_seconds"]):
		out[l.from_camera] = (l.min_seconds or 0, l.max_seconds or 180)
	for l in frappe.get_all("CCTV Camera Link", filters={"from_camera": camera, "bidirectional": 1},
			fields=["to_camera", "min_seconds", "max_seconds"]):
		out.setdefault(l.to_camera, (l.min_seconds or 0, l.max_seconds or 180))
	return out


def _new_track(kind, sighting, profile=None, label=None):
	doc = frappe.get_doc({"doctype": "CCTV Track", "kind": kind, "status": "Active", "farm": sighting.farm,
		"person_profile": profile, "label": label, "first_seen": sighting.sighting_time, "last_seen": sighting.sighting_time,
		"last_camera": sighting.camera, "last_zone": sighting.zone, "sighting_count": 1, "confidence": 100})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.insert()
	if not label:
		frappe.db.set_value("CCTV Track", doc.name, "label", f"Person {doc.name[:6].upper()}")
	return doc.name


def _extend(track, sighting, confidence=None):
	t = frappe.db.get_value("CCTV Track", track, ["sighting_count", "confidence"], as_dict=True)
	frappe.db.set_value("CCTV Track", track, {"last_seen": sighting.sighting_time, "last_camera": sighting.camera,
		"last_zone": sighting.zone, "sighting_count": (t.sighting_count or 0) + 1,
		"confidence": min(t.confidence or 100, confidence) if confidence is not None else t.confidence})


def attach(sighting):
	"""Put a CCTV Person Sighting on a track (called right after it is created)."""
	if sighting.person_profile:
		track = frappe.db.get_value("CCTV Track", {"kind": "Person", "status": "Active", "person_profile": sighting.person_profile,
			"farm": sighting.farm})
		if track:
			_extend(track, sighting)
		else:
			name = frappe.db.get_value("CCTV Person Profile", sighting.person_profile, "full_name")
			track = _new_track("Person", sighting, sighting.person_profile, name)
		frappe.db.set_value("CCTV Person Sighting", sighting.name, "track", track)
		return track

	# Same camera, same tracker id (the camera's own single-view tracker): same track.
	if sighting.track_id:
		same = frappe.db.get_value("CCTV Person Sighting", {"camera": sighting.camera, "track_id": sighting.track_id,
			"name": ["!=", sighting.name], "track": ["is", "set"],
			"sighting_time": [">=", add_to_date(sighting.sighting_time, minutes=-10)]}, "track")
		if same:
			_extend(same, sighting)
			frappe.db.set_value("CCTV Person Sighting", sighting.name, "track", same)
			return same

	fits = []
	when = get_datetime(sighting.sighting_time)
	for cam, (lo, hi) in _links_into(sighting.camera).items():
		for t in frappe.get_all("CCTV Track", filters={"kind": "Person", "status": "Active", "person_profile": ["is", "not set"],
				"last_camera": cam, "last_seen": ["between", [add_to_date(when, seconds=-hi), add_to_date(when, seconds=-lo)]]},
				fields=["name", "confidence"]):
			fits.append(t)
	if len(fits) == 1:
		track = fits[0].name
		_extend(track, sighting, (fits[0].confidence or 100) * HOP_DECAY)
	else:
		track = _new_track("Person", sighting)
	frappe.db.set_value("CCTV Person Sighting", sighting.name, "track", track)
	return track


def close_stale():
	"""Scheduler: tracks with nothing new inside the presence window are closed."""
	cutoff = add_to_date(now_datetime(), hours=-get_settings().presence_stale_hours)
	frappe.db.sql("update `tabCCTV Track` set status='Closed' where status='Active' and last_seen < %s", cutoff)


@frappe.whitelist()
def track_trail(track):
	"""The cameras a track passed, with times - for the map and timeline."""
	if not set(frappe.get_roles()) & {"System Manager", "Security Head", "Security Manager", "CCTV Operator"}:
		frappe.throw("Not permitted.", frappe.PermissionError)
	rows = frappe.get_all("CCTV Person Sighting", filters={"track": track},
		fields=["sighting_time", "camera", "zone", "direction", "confidence"], order_by="sighting_time asc")
	cams = {c.name: c for c in frappe.get_all("CCTV Camera", filters={"name": ["in", [r.camera for r in rows] or ["-"]]},
		fields=["name", "camera_name", "latitude", "longitude"])}
	for r in rows:
		c = cams.get(r.camera) or {}
		r.update({"camera_name": c.get("camera_name"), "latitude": c.get("latitude"), "longitude": c.get("longitude")})
	return rows
