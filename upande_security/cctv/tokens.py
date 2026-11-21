# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Short-lived viewing tokens for the site's media gateway (MediaMTX).

The browser never gets a camera URL or credential. It gets a gateway URL
for one path plus a signed token:

	live      live/<camera key>/<sub|main>
	playback  pb/<camera key>/<start>_<end>      (UTC, YYYYMMDDTHHMMSSZ)

MediaMTX is configured with authMethod: http pointing at the site agent,
which verifies the token (HS256, shared CCTV Settings > Gateway Token Secret)
and, for a playback path, starts the recorder's own playback stream for that
range. So no request ever comes back to ERPNext per view, and ERPNext never
has to reach into the site network.

Every token issued is a row in CCTV Live View Log / CCTV Playback Log.
"""

import hashlib
import hmac
import base64
import json
import time

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from upande_security.cctv.settings import get_settings, is_on, require

# Who may watch what, beyond plain read permission on the camera.
FULL_VIEW_ROLES = {"System Manager", "Security Head", "Security Manager", "CCTV Operator"}
GUARD_CAMERA_ROLES = {"Gate", "Entry", "Exit", "Parking"}
RESTRICTED_SEVERITIES = {"High", "Critical"}


def _b64(data):
	return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign(claims, secret):
	header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
	body = _b64(json.dumps(claims, separators=(",", ":")).encode())
	sig = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
	return f"{header}.{body}.{_b64(sig)}"


def verify(token, secret):
	"""For tests and for the agent's reference implementation."""
	header, body, sig = token.split(".")
	expected = _b64(hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
	if not hmac.compare_digest(expected, sig):
		raise ValueError("bad signature")
	claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
	if claims.get("exp", 0) < time.time():
		raise ValueError("expired")
	return claims


def camera_key(camera):
	return frappe.scrub(camera).replace("_", "-")


def can_view(camera, scope="live", user=None):
	"""Read permission on the camera (which carries site/zone User Permissions),
	plus: restricted-zone cameras for supervisors/operators only, and gate
	guards only the gate-side cameras and no manual playback search."""
	user = user or frappe.session.user
	cam = frappe.get_doc("CCTV Camera", camera)
	if not cam.enabled or not frappe.has_permission("CCTV Camera", "read", cam, user=user):
		return False
	roles = set(frappe.get_roles(user))
	if roles & FULL_VIEW_ROLES:
		return True
	if cam.zone and frappe.db.get_value("Security Zone", cam.zone, "severity") in RESTRICTED_SEVERITIES:
		return False
	if "Gate Guard" in roles:
		return cam.role in GUARD_CAMERA_ROLES and scope in ("live", "alert")
	return False


def _gateway(camera):
	farm = frappe.db.get_value("CCTV Camera", camera, "farm")
	url = frappe.db.get_value("CCTV Site Agent", {"farm": farm}, "gateway_url")
	if not url:
		frappe.throw(_("No media gateway is configured for site {0}.").format(farm))
	return url.rstrip("/")


def _secret():
	secret = frappe.get_single("CCTV Settings").get_password("gateway_jwt_secret", raise_exception=False)
	if not secret:
		frappe.throw(_("Set the Gateway Token Secret in CCTV Settings."))
	return secret


def _ip():
	return getattr(frappe.local, "request_ip", None)


@frappe.whitelist()
def get_live_token(camera, profile="sub"):
	require("live_view_enabled")
	profile = "main" if profile == "main" else "sub"
	if not can_view(camera, "live"):
		frappe.throw(_("You may not view this camera."), frappe.PermissionError)
	s = get_settings()
	jti = frappe.generate_hash(length=16)
	path = f"live/{camera_key(camera)}/{profile}"
	token = sign({"sub": frappe.session.user, "cam": camera, "path": path, "scope": "live",
		"exp": int(time.time()) + s.live_token_ttl_seconds, "jti": jti}, _secret())
	frappe.get_doc({"doctype": "CCTV Live View Log", "user": frappe.session.user, "camera": camera, "profile": profile,
		"started_at": now_datetime(), "ip_address": _ip(), "token_id": jti}).insert(ignore_permissions=True)
	base = _gateway(camera)
	return {"token": token, "expires_in": s.live_token_ttl_seconds, "path": path,
		"whep_url": f"{base}/{path}/whep?jwt={token}", "hls_url": f"{base}/{path}/index.m3u8?jwt={token}"}


def _utc_stamp(local_dt):
	import pytz

	tz = pytz.timezone(frappe.utils.get_system_timezone())
	return tz.localize(get_datetime(local_dt)).astimezone(pytz.utc).strftime("%Y%m%dT%H%M%SZ")


@frappe.whitelist()
def get_playback_session(alert=None, camera=None, start=None, end=None, source=None):
	"""Playback cued to an alert (or a vehicle visit / manual range for those allowed).
	Returns the gateway URL for the recorder's footage over that range."""
	require("enabled")
	s = get_settings()
	if alert:
		a = frappe.get_doc("CCTV Alert", alert)
		if not frappe.has_permission("CCTV Alert", "read", a):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		camera = camera or a.camera
		start, end, scope, source = a.clip_start, a.clip_end, "alert", "Alert"
		if not a.first_viewed_by:
			frappe.db.set_value("CCTV Alert", alert, {"first_viewed_by": frappe.session.user, "first_viewed_at": now_datetime()})
	else:
		scope, source = "playback", (source if source in ("Manual", "Vehicle Visit") else "Manual")
	if not (camera and start and end):
		frappe.throw(_("A camera and a time range are needed."))
	start, end = get_datetime(start), get_datetime(end)
	if end <= start or (end - start).total_seconds() > 4 * 3600:
		frappe.throw(_("Choose a range of up to 4 hours."))
	if not can_view(camera, scope):
		frappe.throw(_("You may not view this camera's footage."), frappe.PermissionError)
	offset = frappe.db.get_value("CCTV Server", frappe.db.get_value("CCTV Camera", camera, "server"), "time_offset_seconds") or 0
	dev_start, dev_end = add_to_date(start, seconds=offset), add_to_date(end, seconds=offset)
	jti = frappe.generate_hash(length=16)
	path = f"pb/{camera_key(camera)}/{_utc_stamp(dev_start)}_{_utc_stamp(dev_end)}"
	token = sign({"sub": frappe.session.user, "cam": camera, "path": path, "scope": "playback",
		"rng": [_utc_stamp(dev_start), _utc_stamp(dev_end)], "exp": int(time.time()) + s.playback_token_ttl_seconds,
		"jti": jti, "once": 1}, _secret())
	frappe.get_doc({"doctype": "CCTV Playback Log", "user": frappe.session.user, "camera": camera, "alert": alert,
		"source": source, "range_start": start, "range_end": end, "opened_at": now_datetime(), "ip_address": _ip(),
		"token_id": jti}).insert(ignore_permissions=True)
	base = _gateway(camera)
	event_offset = None
	if alert:
		event_offset = int((get_datetime(a.event_time) - start).total_seconds())
	return {"token": token, "path": path, "whep_url": f"{base}/{path}/whep?jwt={token}",
		"hls_url": f"{base}/{path}/index.m3u8?jwt={token}", "start": str(start), "end": str(end),
		"event_offset_seconds": event_offset, "expires_in": s.playback_token_ttl_seconds}


@frappe.whitelist()
def end_live_view(token_id):
	frappe.db.set_value("CCTV Live View Log", {"token_id": token_id, "user": frappe.session.user}, "ended_at", now_datetime())
	return True


@frappe.whitelist()
def list_cameras(farm=None, zone=None):
	"""Cameras this user may watch, for the Live View grid."""
	require("live_view_enabled")
	filters = {"enabled": 1}
	if farm:
		filters["farm"] = farm
	if zone:
		filters["zone"] = zone
	rows = frappe.get_list("CCTV Camera", filters=filters,
		fields=["name", "camera_name", "farm", "zone", "gate", "role", "status", "last_frame_time", "cap_ptz", "cap_anpr"],
		order_by="farm asc, camera_name asc", limit_page_length=500)
	return [r for r in rows if can_view(r.name, "live")]
