# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Direct Push: recorders that send their own alarms straight to ERPNext.

A FALLBACK. The site agent stays the recommended way to connect a recorder:
it adds live view and playback in the dashboard, the own AI engine, the site
survey, camera discovery and an offline buffer. Direct Push is for a recorder
with no box beside it (yet): alerts, plate reads matched to bookings, guard
checks and reports still work, from the recorder's own analytics.

HOW IT WORKS
The recorder's "HTTP listening" / "alarm server" / "event push" setting posts
each alarm to a secret link. The body is parsed by the SAME brand parsers the
site agent uses (cctv_agent/cctv_agent/adapters), so an event looks identical
whichever path brought it, and then goes through ingest.store_event and the
normal pipeline (rules, alerts, plates, guards).

SETUP
1. CCTV Settings > Accept Direct Push from Recorders.
2. CCTV Server: Connection = Direct Push; add its cameras with their channel
   numbers (channel 1 = D1).
3. CCTV Server > Direct Push > Generate push link. The full link is shown
   once; only a hash of the secret is stored.
4. Put the link in the recorder (see push_instructions below).

SECURITY
- The link carries a 256-bit secret; only its SHA-256 is stored, and a new
  link replaces the old one at once.
- Nothing is accepted unless CCTV is on, Direct Push is on, and the server is
  set to Direct Push. A recorder can only report its own cameras' channels.
- Per-recorder rate limit and a size limit. Refusals say nothing about why.
- Recorders retry: an identical body is stored once (event_id from its hash).
"""

import hashlib
import os
import secrets
import sys
import time
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import get_system_timezone, get_url, now_datetime

from upande_security.cctv.settings import get_settings, is_on

ENDPOINT = "/api/method/upande_security.cctv.push.receive"
ADMIN_ROLES = {"System Manager", "Security Head"}
SUPPORTED = ("Hikvision", "Dahua")
IMAGE_EXT = (".jpg", ".jpeg", ".png")


# ------------------------------------------------------------------ parsers

def _agent_adapters():
	"""The site agent's brand parsers (pure functions), shipped in this repo."""
	path = os.path.abspath(os.path.join(frappe.get_app_path("upande_security"), "..", "cctv_agent"))
	if path not in sys.path:
		sys.path.append(path)  # appended: never shadows anything already importable
	from cctv_agent.adapters.dahua import DahuaAdapter
	from cctv_agent.adapters.hikvision import HikvisionAdapter

	return {"Hikvision": HikvisionAdapter, "Dahua": DahuaAdapter}


def _parser(server):
	cls = _agent_adapters()[server.brand]
	a = cls.__new__(cls)  # no __init__: that opens an HTTP client to the recorder
	a.server = {"name": server.name, "host": server.host}
	a.site = server.farm
	a.offset = float(server.time_offset_seconds or 0)
	if server.brand == "Dahua":
		a.tz = ZoneInfo(get_system_timezone())
	return a


def _token_hash(token):
	return hashlib.sha256((token or "").encode()).hexdigest()


# ------------------------------------------------------------------ request body

def _is_image(ctype, name, body):
	return (ctype or "").startswith("image") or (name or "").lower().endswith(IMAGE_EXT) or body[:3] == b"\xff\xd8\xff"


def _parts():
	"""[(content_type, name, bytes)] of whatever the recorder sent."""
	req = frappe.request
	ctype = (req.content_type or "").lower()
	if ctype.startswith("multipart/form-data"):
		out = [((fs.mimetype or "").lower(), fs.filename or key, fs.read()) for key, fs in req.files.items(multi=True)]
		out += [("", key, (val or "").encode()) for key, val in req.form.items(multi=True)]
		return out
	data = req.get_data(cache=True) or b""
	if ctype.startswith("multipart/"):  # multipart/mixed, as on the alertStream
		_agent_adapters()
		from cctv_agent.adapters.multipart import MultipartStream, boundary_of

		boundary = boundary_of(req.content_type) or "boundary"
		parser = MultipartStream(boundary)
		parts = parser.feed(data + b"\r\n--" + boundary.lstrip("-").encode() + b"--\r\n")
		return [(h.get("content-type", "").lower(), h.get("content-disposition", ""), b) for h, b in parts]
	return [(ctype, "", data)]


def _dahua_texts(ctype, body):
	"""Dahua sends either the eventManager text (Code=..;action=..;index=..;data={..})
	or JSON ({"Code", "Action", "Index", "Data"}, alone, in a list or under "Events")."""
	text = body.decode("utf-8", "replace")
	if "Code=" in text:
		return [chunk for chunk in text.split("--") if "Code=" in chunk] or [text]
	try:
		obj = frappe.parse_json(text)
	except Exception:
		return []
	items = obj if isinstance(obj, list) else (obj.get("Events") or [obj]) if isinstance(obj, dict) else []
	out = []
	for it in items:
		if isinstance(it, dict) and it.get("Code"):
			out.append(f"Code={it['Code']};action={it.get('Action') or 'Pulse'};index={int(it.get('Index') or 0)};data={frappe.as_json(it.get('Data') or {}, indent=None)}")
	return out


def parse(server, parts, cameras):
	"""Normalised events from one push (pure apart from the parser import)."""
	p = _parser(server)
	events = []
	for ctype, name, body in parts:
		if not body or _is_image(ctype, name, body):
			continue
		if server.brand == "Hikvision":
			events += p.normalise(body, ctype, cameras)
		else:
			for text in _dahua_texts(ctype, body):
				events += p.normalise(text, cameras)
	return events


def _pick_image(parts):
	"""The scene picture if there is one (more useful than the plate crop), else any picture."""
	images = [(n or "", b) for c, n, b in parts if b and _is_image(c, n, b)]
	for want in ("detection", "background", "scene", "vehicle"):
		for n, b in images:
			if want in n.lower():
				return n, b
	return images[0] if images else (None, None)


# ------------------------------------------------------------------ endpoint

def _refuse(code, msg="Refused"):
	frappe.local.response.http_status_code = code
	frappe.db.rollback()
	return {"ok": 0, "message": msg}


def _over_limit(key, limit):
	try:
		k = f"{frappe.local.site}:cctv_push:{key}:{int(time.time() // 60)}"
		n = frappe.cache.incr(k)
		if n == 1:
			frappe.cache.expire(k, 90)
		return n > limit
	except Exception:
		return False  # no redis: do not block the alarm


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive(t=None, **kwargs):
	"""The recorder posts here: /api/method/upande_security.cctv.push.receive?t=<secret>"""
	s = get_settings()
	if not (is_on("enabled") and s.push_enabled):
		return _refuse(403)
	ip = frappe.local.request_ip or "-"
	if _over_limit(f"ip:{ip}", max(s.push_rate_limit_per_minute * 4, 100)):
		return _refuse(429)
	# JSON bodies replace form_dict, so read the secret from the query string itself.
	token = t or frappe.request.args.get("t") or frappe.form_dict.get("t")
	if not token or len(token) < 20:
		return _refuse(401)
	server = frappe.db.get_value("CCTV Server", {"push_token_hash": _token_hash(token), "connection": "Direct Push"},
		["name", "brand", "farm", "host", "time_offset_seconds"], as_dict=True)
	if not server:
		return _refuse(401)
	if _over_limit(server.name, s.push_rate_limit_per_minute):
		return _refuse(429)
	length = frappe.request.content_length or 0
	if length > s.push_max_body_mb * 1024 * 1024:
		return _refuse(413)
	if server.brand not in SUPPORTED:
		return _note(server, f"{server.brand} push is not supported - use the site agent.")

	cameras = frappe.get_all("CCTV Camera", filters={"server": server.name, "enabled": 1},
		fields=["name", "channel_no", "direction_in"])
	parts = _parts()
	try:
		events = parse(server, parts, cameras)
	except Exception:
		frappe.log_error(title=f"CCTV push from {server.name} could not be read")
		events = []
	if not events:
		return _note(server, "Received, nothing to record (heartbeat, inactive state, or a camera channel not set up).")

	from upande_security.cctv.ingest import store_event

	digest = hashlib.sha1(b"".join(b for _c, _n, b in parts if not _is_image(_c, _n, b))).hexdigest()[:16]
	name, image = _pick_image(parts)
	snapshot = _save_image(name, image) if image else None
	results = []
	for i, ev in enumerate(events):
		ev["event_id"] = f"push-{server.name}-{digest}-{i}"[:140]  # a retried push is a duplicate, not a new event
		ev.setdefault("source", {})["model_version"] = f"direct push ({server.brand})"
		if snapshot:
			ev["snapshot_ref"] = snapshot
		try:
			status, ref = store_event(ev, farm=server.farm)
		except Exception as e:
			status, ref = "rejected", str(e)[:120]
		results.append(status)
		if status == "accepted":
			frappe.enqueue("upande_security.cctv.engine.process_event", queue="short", event=ref, enqueue_after_commit=True)
	summary = ", ".join(f"{results.count(x)} {x}" for x in ("accepted", "duplicate", "rejected") if results.count(x))
	return _note(server, f"{len(events)} event(s): {summary}.", accepted=results.count("accepted"))


def _save_image(name, content):
	"""Private File for the picture, or None: a bad picture never loses the alarm."""
	try:
		return _insert_file(name, content)
	except Exception:
		frappe.log_error(title="CCTV push picture could not be saved")
		return None


def _insert_file(name, content):
	doc = frappe.get_doc({"doctype": "File", "file_name": os.path.basename(name or "")[:80] or "push.jpg",
		"content": content, "is_private": 1, "folder": "Home/Attachments"})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.file_url


def _note(server, note, accepted=0):
	now = now_datetime()
	frappe.db.set_value("CCTV Server", server.name, {"status": "Online", "last_seen": now, "last_push_at": now,
		"last_push_note": note}, update_modified=False)
	frappe.db.commit()
	return {"ok": 1, "accepted": accepted}


# ------------------------------------------------------------------ setup (desk)

@frappe.whitelist()
def generate_push_link(server):
	"""A new secret link for this recorder. Shown once; the previous link stops working."""
	if not set(frappe.get_roles()) & ADMIN_ROLES:
		frappe.throw(_("Only a System Manager or Security Head can do this."), frappe.PermissionError)
	doc = frappe.get_doc("CCTV Server", server)
	if doc.connection != "Direct Push":
		frappe.throw(_("Set Connection to Direct Push first."))
	if doc.brand not in SUPPORTED:
		frappe.throw(_("Direct Push works with {0} recorders. Use the site agent for {1}.").format(" and ".join(SUPPORTED), doc.brand))
	token = secrets.token_urlsafe(32)
	doc.db_set({"push_token_hash": _token_hash(token), "push_token_hint": f"…{token[-4:]} (created {now_datetime():%d %b %Y %H:%M})"})
	url = get_url(f"{ENDPOINT}?t={token}")
	return {"url": url, **push_instructions(doc.brand, url)}


def push_instructions(brand, url):
	from urllib.parse import urlsplit

	u = urlsplit(url)
	https = u.scheme == "https"
	where = {"host": u.hostname, "port": u.port or (443 if https else 80), "protocol": "HTTPS" if https else "HTTP",
		"path": f"{u.path}?{u.query}"}
	if brand == "Hikvision":
		steps = [
			"Configuration > Network > Advanced Settings > HTTP Listening (on some firmware: Alarm Server / Alarm Host).",
			f"Destination IP or Host Name: {where['host']}   Port: {where['port']}   Protocol: {where['protocol']}",
			f"URL: {where['path']}",
			"Then, for each event to send (Event > Smart Event / Basic Event / Road Traffic > Vehicle Detection), tick 'Notify Surveillance Center' / 'Notify Alarm Center' in Linkage Method.",
			"For plates: Road Traffic > Vehicle Detection on, with picture upload on.",
		]
	else:
		steps = [
			"Network > Platform Access / Event Push / HTTP Upload (name varies with firmware).",
			f"Server: {where['host']}   Port: {where['port']}   Protocol: {where['protocol']}",
			f"Path / URL: {where['path']}",
			"Enable the events to send (Smart Plan > IVS / ANPR, Event > Video Detection) with 'Upload to platform' / 'Alarm upload' ticked.",
		]
	steps.append("If the recorder cannot do HTTPS or refuses '?' in the URL, it needs the site agent instead.")
	return {"where": where, "steps": steps}
