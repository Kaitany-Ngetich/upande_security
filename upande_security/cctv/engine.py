# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Background processing of a stored CCTV Event: route it by type.

Runs in a worker (enqueued by ingest), never in the web request, so a burst
of events cannot block the site. Every outcome - including failures - is
written back on the event (processed / processing_error) so nothing is lost
silently and a failed event can be re-run with reprocess().
"""

import frappe

from upande_security.cctv.settings import is_on

VEHICLE = {"plate_read", "vehicle_detected"}
ZONE = {"person_detected", "line_crossing", "zone_intrusion", "face_match", "face_unknown", "door_state", "access_event"}
DEVICE = {"tamper", "video_loss", "recording_gap", "camera_status"}


def process_event(event):
	if not is_on("enabled"):
		return
	ev = frappe.get_doc("CCTV Event", event)
	if ev.processed:
		return
	ev.payload_dict = (frappe.parse_json(ev.payload or "{}") or {}).get("data") or {}
	result = None
	try:
		if ev.event_type == "plate_read":
			from upande_security.cctv.vehicles import handle_plate_read
			result = handle_plate_read(ev)
		elif ev.event_type in ZONE:
			from upande_security.cctv.rules import handle_zone_event
			result = handle_zone_event(ev)
		elif ev.event_type in DEVICE:
			from upande_security.cctv.rules import handle_device_event
			result = handle_device_event(ev)
		else:
			result = "stored only"
		frappe.db.set_value("CCTV Event", ev.name, {"processed": 1, "processing_error": None}, update_modified=False)
	except Exception:
		frappe.db.rollback()
		frappe.db.set_value("CCTV Event", ev.name, {"processed": 0,
			"processing_error": frappe.get_traceback()[-1000:]}, update_modified=False)
		frappe.log_error(title=f"CCTV event {ev.name} failed")
	frappe.db.commit()
	return result


@frappe.whitelist()
def reprocess(event):
	frappe.only_for(("System Manager", "Security Head"))
	frappe.db.set_value("CCTV Event", event, {"processed": 0, "processing_error": None})
	return process_event(event)
