"""Normalised CCTV events (schema 1.0) - the only shape ERPNext ever sees.

Every adapter turns its brand's event into make_event(...). Times are UTC
after correcting the device's clock offset; the offset applied is kept in
source.device_offset_ms for audit.
"""

import secrets
from datetime import datetime, timedelta, timezone

SCHEMA_VERSION = "1.0"

EVENT_TYPES = {
	"plate_read", "vehicle_detected", "person_detected", "face_match", "face_unknown", "line_crossing",
	"zone_intrusion", "door_state", "access_event", "motion", "tamper", "video_loss", "recording_gap",
	"camera_status",
}
# Sent before bulk events after an outage (buffer priority).
PRIORITY_TYPES = {"plate_read", "face_match", "face_unknown", "line_crossing", "zone_intrusion", "door_state",
	"access_event", "tamper", "video_loss", "recording_gap", "person_detected"}


def camera_key(name):
	"""Same as ERPNext's tokens.camera_key (frappe.scrub, '_' -> '-')."""
	return str(name).replace(" ", "_").replace("-", "_").lower().replace("_", "-")


def to_utc(device_time, offset_seconds=0.0):
	"""Device timestamp (aware, or naive = UTC) -> true UTC, removing the device's clock error."""
	if device_time is None:
		return datetime.now(timezone.utc)
	if device_time.tzinfo is None:
		device_time = device_time.replace(tzinfo=timezone.utc)
	return device_time.astimezone(timezone.utc) - timedelta(seconds=offset_seconds or 0)


def iso(dt):
	return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def make_event(site, camera, event_type, when_utc, data=None, confidence=None, provider="camera_native",
		model_version=None, offset_seconds=0.0, snapshot_ref=None):
	if event_type not in EVENT_TYPES:
		raise ValueError(f"unknown event_type {event_type}")
	stamp = when_utc.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"{when_utc.microsecond // 1000:03d}Z"
	return {
		"event_id": f"{site}-{camera_key(camera)}-{stamp}-{secrets.token_hex(2)}",
		"schema_version": SCHEMA_VERSION,
		"camera": camera,
		"event_type": event_type,
		"event_time": iso(when_utc),
		"source": {"provider": provider, "model_version": model_version, "device_offset_ms": int((offset_seconds or 0) * 1000)},
		"confidence": None if confidence is None else round(float(confidence), 3),
		"snapshot_ref": snapshot_ref,
		"data": {k: v for k, v in (data or {}).items() if v not in (None, "")},
	}


def plate_direction(raw, direction_in):
	"""Map a camera's own approach/leave wording to in/out using the camera's
	configured 'Direction Counted as IN' (ERPNext CCTV Camera.direction_in)."""
	raw = (raw or "").lower()
	toward = raw in ("forward", "approach", "approaching", "toward", "towards", "obverse", "in", "1")
	away = raw in ("reverse", "leave", "leaving", "away", "back", "out", "2")
	if not (toward or away):
		return "unknown"
	if direction_in == "Away From Camera":
		return "in" if away else "out"
	return "in" if toward else "out"


def line_direction(raw, direction_in):
	raw = (raw or "").lower().replace("-", "").replace("_", "").replace(" ", "")
	ltr = raw in ("lefttoright", "atob", "ltr")
	rtl = raw in ("righttoleft", "btoa", "rtl")
	if not (ltr or rtl):
		return "unknown"
	if direction_in == "Right to Left":
		return "in" if rtl else "out"
	return "in" if ltr else "out"
