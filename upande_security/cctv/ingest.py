# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""The site agent's API: events in, config out, heartbeats.

AUTH
The agent calls with a normal API key/secret of a user holding the CCTV
Agent role, AND signs every body:

	X-CCTV-Agent:      <agent_id>
	X-CCTV-Timestamp:  <unix seconds>
	X-CCTV-Signature:  hex(HMAC-SHA256(agent.hmac_secret, "<timestamp>." + raw body))

Requests older than max_clock_skew_seconds are refused (replay). An agent can
only post events for cameras of its own site.

EVENTS
Batch of up to 100 normalised envelopes (see docs below). Each event is
stored and queued; matching, rules and alerts run in a worker. event_id is
the idempotency key: a resend is reported as "duplicate", which the agent
treats as success. Unknown event types are stored, never rejected, so a
newer agent does not break an older server.

	{"event_id": "SITE01-CAM12-20261121T094215123Z-7f3a", "schema_version": "1.0",
	 "camera": "<CCTV Camera name>", "event_type": "plate_read",
	 "event_time": "2026-11-21T09:42:15.123Z",
	 "source": {"provider": "camera_native", "model_version": "...", "device_offset_ms": 0},
	 "confidence": 0.94, "snapshot_ref": "/private/files/...",
	 "data": {"plate": "KDA 123A", "direction": "in", ...}}
"""

import hashlib
import hmac
import time

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime
from frappe.utils.data import convert_utc_to_system_timezone

from upande_security.cctv import plates
from upande_security.cctv.settings import get_settings, is_on, site_allows

MAX_BATCH = 100


def _known_types():
	return set((frappe.get_meta("CCTV Event").get_field("event_type").options or "").split("\n"))


def _agent():
	"""The calling agent, after checking role, signature and freshness."""
	if "CCTV Agent" not in frappe.get_roles() and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not a CCTV agent."), frappe.PermissionError)
	agent_id = frappe.get_request_header("X-CCTV-Agent")
	if not agent_id or not frappe.db.exists("CCTV Site Agent", agent_id):
		frappe.throw(_("Unknown agent."), frappe.AuthenticationError)
	agent = frappe.get_doc("CCTV Site Agent", agent_id)
	s = get_settings()
	if s.require_agent_signature:
		ts = frappe.get_request_header("X-CCTV-Timestamp") or "0"
		sig = frappe.get_request_header("X-CCTV-Signature") or ""
		if abs(time.time() - float(ts)) > s.max_clock_skew_seconds:
			frappe.throw(_("Stale request."), frappe.AuthenticationError)
		secret = agent.get_password("hmac_secret", raise_exception=False) or ""
		body = frappe.request.get_data() if frappe.request else b""
		expected = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
		if not secret or not hmac.compare_digest(expected, sig):
			frappe.throw(_("Bad signature."), frappe.AuthenticationError)
	return agent


def _to_local(iso_utc):
	"""'2026-11-21T09:42:15.123Z' -> naive site-local datetime."""
	dt = get_datetime(str(iso_utc).replace("Z", "+00:00"))
	if dt.tzinfo is None:
		return dt
	return convert_utc_to_system_timezone(dt.replace(tzinfo=None)).replace(tzinfo=None)


def store_event(ev, farm=None, agent=None):
	"""Validate and store one envelope. Returns (status, name_or_reason)."""
	for key in ("event_id", "camera", "event_type", "event_time"):
		if not ev.get(key):
			return "rejected", f"missing {key}"
	if frappe.db.exists("CCTV Event", {"event_id": ev["event_id"]}):
		return "duplicate", ev["event_id"]
	cam_farm = frappe.db.get_value("CCTV Camera", ev["camera"], "farm")
	if not cam_farm:
		return "rejected", "unknown camera"
	if farm and cam_farm != farm:
		return "rejected", "camera belongs to another site"
	if not site_allows(cam_farm, "core"):
		return "rejected", "site not licensed for CCTV"
	if (ev.get("source") or {}).get("provider") == "own_engine" and not site_allows(cam_farm, "ai_engine"):
		return "rejected", "site not licensed for the AI engine"
	etype = ev["event_type"] if ev["event_type"] in _known_types() else "other"
	data = ev.get("data") or {}
	source = ev.get("source") or {}
	try:
		when = _to_local(ev["event_time"])
	except Exception:
		return "rejected", "bad event_time"
	conf = ev.get("confidence")
	doc = frappe.get_doc({
		"doctype": "CCTV Event",
		"event_id": ev["event_id"],
		"event_type": etype,
		"event_time": when,
		"event_time_utc": str(ev["event_time"]),
		"received_at": now_datetime(),
		"camera": ev["camera"],
		"farm": cam_farm,
		"agent": agent,
		"provider": source.get("provider") if source.get("provider") in ("camera_native", "own_engine", "third_party", "agent", "simulator") else "agent",
		"model_version": source.get("model_version"),
		"confidence": round(float(conf) * 100, 1) if conf is not None else None,
		"direction": data.get("direction") if data.get("direction") in ("in", "out", "unknown") else None,
		"plate_normalized": plates.normalize(data.get("plate")) or None,
		"snapshot": ev.get("snapshot_ref"),
		"payload": frappe.as_json(ev),
	})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.insert()
	if etype != "camera_status" or (data.get("state") or "").lower() == "online":
		# Any event from a camera proves it is alive.
		frappe.db.set_value("CCTV Camera", ev["camera"], "last_frame_time", now_datetime(), update_modified=False)
	return "accepted", doc.name


@frappe.whitelist(methods=["POST"])
def ingest_events(events):
	if not is_on("enabled"):
		frappe.throw(_("CCTV is switched off."), frappe.PermissionError)
	agent = _agent()
	events = frappe.parse_json(events) if isinstance(events, str) else events
	if not isinstance(events, list):
		frappe.throw(_("events must be a list."))
	if len(events) > MAX_BATCH:
		frappe.local.response.http_status_code = 413
		frappe.throw(_("At most {0} events per batch.").format(MAX_BATCH))
	results = []
	for ev in events:
		try:
			status, ref = store_event(ev, farm=agent.farm, agent=agent.name)
		except Exception as e:
			status, ref = "rejected", str(e)[:120]
		results.append({"event_id": ev.get("event_id"), "status": status, "ref": ref})
		if status == "accepted":
			frappe.enqueue("upande_security.cctv.engine.process_event", queue="short", event=ref, enqueue_after_commit=True)
	frappe.db.commit()
	return {"results": results, "accepted": sum(r["status"] == "accepted" for r in results)}


@frappe.whitelist(methods=["POST"])
def upload_snapshot(filename=None):
	"""Image bytes from the agent (raw body, signed) -> private File; returns its reference."""
	agent = _agent()
	content = frappe.request.get_data()
	if not content:
		frappe.throw(_("No file."))
	doc = frappe.get_doc({"doctype": "File", "file_name": filename or "snapshot.jpg", "content": content,
		"is_private": 1, "folder": "Home/Attachments"})
	doc.flags.ignore_permissions = True
	doc.insert()
	return {"snapshot_ref": doc.file_url, "agent": agent.name}


@frappe.whitelist(methods=["POST"])
def agent_heartbeat(version=None, queue_depth=None, cpu=None, gpu=None, cameras=None, servers=None):
	agent = _agent()
	now = now_datetime()
	values = {"status": "Online", "last_heartbeat": now, "version": version, "queue_depth": queue_depth,
		"cpu_percent": cpu, "gpu_percent": gpu, "health_json": frappe.as_json({"cameras": cameras, "servers": servers})}
	# numeric columns are NOT NULL: leave out what the agent did not report
	frappe.db.set_value("CCTV Site Agent", agent.name, {k: v for k, v in values.items() if v is not None}, update_modified=False)
	for c in frappe.parse_json(cameras) if isinstance(cameras, str) else (cameras or []):
		if c.get("camera") and frappe.db.get_value("CCTV Camera", c["camera"], "farm") == agent.farm:
			online = (c.get("state") or "").lower() == "online"
			frappe.db.set_value("CCTV Camera", c["camera"], {"status": "Online" if online else "Offline",
				**({"last_frame_time": now} if online else {}), **{k: c[k] for k in ("fps", "resolution", "codec") if c.get(k)}},
				update_modified=False)
	for sv in frappe.parse_json(servers) if isinstance(servers, str) else (servers or []):
		if sv.get("server") and frappe.db.get_value("CCTV Server", sv["server"], "farm") == agent.farm:
			frappe.db.set_value("CCTV Server", sv["server"], {k: v for k, v in {
				"status": sv.get("status"), "last_seen": now, "time_offset_seconds": sv.get("time_offset_seconds"),
				"recording_mode": sv.get("recording_mode"), "firmware": sv.get("firmware"), "model": sv.get("model"),
			}.items() if v is not None}, update_modified=False)
	frappe.db.commit()
	return {"ok": True, "config_version": _config_version(agent.farm)}


def _config_version(farm):
	"""Changes whenever anything the agent reads changes, so it knows to re-pull."""
	stamps = []
	for dt, by_site in (("CCTV Server", 1), ("CCTV Camera", 1), ("Security Zone", 1), ("CCTV Alert Rule", 0), ("CCTV Known Vehicle", 0)):
		where, args = ("where farm=%s", (farm,)) if by_site else ("", ())
		stamps.append(str(frappe.db.sql(f"select max(modified) from `tab{dt}` {where}", args)[0][0] or ""))
	stamps.append(str(frappe.db.sql("select group_concat(value) from `tabSingles` where doctype='CCTV Settings'")[0][0] or ""))
	return int(hashlib.sha1("|".join(stamps).encode()).hexdigest()[:8], 16)


@frappe.whitelist()
def get_site_config():
	"""Everything the agent needs for its site: servers (with credentials - the
	agent is the one place they are allowed), cameras and analytics settings."""
	agent = _agent()
	s = get_settings()
	servers = []
	for sv in frappe.get_all("CCTV Server", filters={"farm": agent.farm}, fields=["name", "brand", "kind", "host", "port", "use_tls", "verify_tls", "username", "time_offset_seconds"]):
		sv.password = frappe.get_doc("CCTV Server", sv.name).get_password("password", raise_exception=False)
		servers.append(sv)
	cameras = frappe.get_all("CCTV Camera", filters={"farm": agent.farm, "enabled": 1},
		fields=["name", "camera_name", "server", "channel_no", "role", "zone", "gate", "main_stream", "sub_stream", "codec",
			"cap_anpr", "cap_face", "cap_motion", "cap_line_crossing", "cap_intrusion", "analytics_provider", "analytics_enabled",
			"direction_in", "analytics_config"])
	return {
		"agent": agent.name, "site": agent.farm, "config_version": _config_version(agent.farm),
		"servers": servers, "cameras": cameras,
		"gateway": {"token_secret": frappe.get_single("CCTV Settings").get_password("gateway_jwt_secret", raise_exception=False)},
		"analytics": {"anpr": s.anpr_enabled and site_allows(agent.farm, "vehicles"),
			"faces": s.face_recognition_enabled and site_allows(agent.farm, "presence"),
			"presence": s.presence_enabled and site_allows(agent.farm, "presence"),
			"engine": site_allows(agent.farm, "ai_engine"),
			"face_match_threshold": s.face_match_threshold / 100,
			"plate_formats": s.plate_formats, "duplicate_window_seconds": s.duplicate_window_seconds},
	}


@frappe.whitelist()
def engine_models():
	"""Agent: the engine models it should run (enabled, licence-cleared), with checksums."""
	agent = _agent()
	if not site_allows(agent.farm, "ai_engine"):
		return {"models": []}
	return {"models": frappe.get_all("CCTV Engine Model", filters={"enabled": 1, "model_file": ["is", "set"]},
		fields=["name", "task", "version", "sha256", "shadow_mode", "input_size", "labels"])}


@frappe.whitelist()
def download_model(name):
	"""Agent: one model file (raw download)."""
	agent = _agent()
	if not site_allows(agent.farm, "ai_engine"):
		frappe.throw(_("Site not licensed for the AI engine."), frappe.PermissionError)
	m = frappe.get_doc("CCTV Engine Model", name)
	if not m.enabled or not m.model_file:
		frappe.throw(_("Model not available."))
	f = frappe.get_doc("File", {"file_url": m.model_file})
	frappe.local.response.filename = f"{m.name}-{m.version}.onnx"
	with open(f.get_full_path(), "rb") as fh:
		frappe.local.response.filecontent = fh.read()
	frappe.local.response.type = "download"
