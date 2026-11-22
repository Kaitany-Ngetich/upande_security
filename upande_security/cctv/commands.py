# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""ERPNext -> site agent requests, over the agent's own outbound connection.

ERPNext cannot open a connection into a site, so it leaves CCTV Agent
Commands for the agent; the agent polls (poll_commands, every few seconds),
runs them and reports back (command_result / upload_command_file). Results
are applied here:

	export_clip        recorder clip for an alert -> attached to the alert as evidence
	snapshot           a still from a camera now (or at a time)
	discover_channels  a recorder's channels -> the camera setup wizard
	test_connection    reach a recorder, read model / firmware / clock
	enroll_face        a person's face images -> the site's face store (consent required)
	delete_face        remove a person from the site's face store (withdrawal, deletion request)
	sync_models        tell the agent to re-pull engine models

Every request is a record: who asked, when, what came back.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from upande_security.cctv.settings import get_settings, require

COMMANDS = ("export_clip", "snapshot", "discover_channels", "test_connection", "enroll_face", "delete_face", "sync_models", "survey_server")


def agent_for_camera(camera):
	farm = frappe.db.get_value("CCTV Camera", camera, "farm")
	server = frappe.db.get_value("CCTV Camera", camera, "server")
	return frappe.db.get_value("CCTV Server", server, "agent") or frappe.db.get_value("CCTV Site Agent", {"farm": farm})


def queue(agent, command, payload=None, reference_doctype=None, reference_name=None):
	if command not in COMMANDS:
		frappe.throw(_("Unknown command {0}").format(command))
	if not agent:
		frappe.throw(_("No site agent is set up for this site."))
	s = get_settings()
	doc = frappe.get_doc({
		"doctype": "CCTV Agent Command", "agent": agent, "command": command, "status": "Queued",
		"payload": frappe.as_json(payload or {}), "reference_doctype": reference_doctype, "reference_name": reference_name,
		"requested_by": frappe.session.user, "requested_at": now_datetime(),
		"expires_at": add_to_date(now_datetime(), minutes=s.command_ttl_minutes),
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _ops():
	if not set(frappe.get_roles()) & {"System Manager", "Security Head", "Security Manager", "CCTV Operator"}:
		frappe.throw(_("Not permitted."), frappe.PermissionError)


# ------------------------------------------------------------------ user-facing requests

@frappe.whitelist()
def request_evidence(alert, minutes_before=None, minutes_after=None):
	"""Ask the recorder for the alert's clip and keep it on the alert."""
	require("enabled")
	_ops()
	a = frappe.get_doc("CCTV Alert", alert)
	if not frappe.has_permission("CCTV Alert", "write", a):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	s = get_settings()
	start = add_to_date(a.event_time, minutes=-float(minutes_before)) if minutes_before else get_datetime(a.clip_start)
	end = add_to_date(a.event_time, minutes=float(minutes_after)) if minutes_after else get_datetime(a.clip_end)
	if (end - start).total_seconds() > s.evidence_max_minutes * 60:
		frappe.throw(_("Evidence clips are limited to {0} minutes.").format(s.evidence_max_minutes))
	from upande_security.cctv.tokens import _utc_stamp

	name = queue(agent_for_camera(a.camera), "export_clip",
		{"camera": a.camera, "start_utc": _utc_stamp(start), "end_utc": _utc_stamp(end), "label": a.name},
		"CCTV Alert", a.name)
	frappe.db.set_value("CCTV Alert", alert, "evidence_command", name)
	return {"ok": True, "command": name}


@frappe.whitelist()
def request_snapshot(camera):
	require("enabled")
	_ops()
	return {"ok": True, "command": queue(agent_for_camera(camera), "snapshot", {"camera": camera}, "CCTV Camera", camera)}


@frappe.whitelist()
def discover(server):
	"""Camera setup wizard, step 1: ask the recorder what channels it has."""
	frappe.only_for(("System Manager", "Security Head"))
	sv = frappe.get_doc("CCTV Server", server)
	agent = sv.agent or frappe.db.get_value("CCTV Site Agent", {"farm": sv.farm})
	return {"ok": True, "command": queue(agent, "discover_channels", {"server": server}, "CCTV Server", server)}


@frappe.whitelist()
def test_connection(server):
	frappe.only_for(("System Manager", "Security Head"))
	sv = frappe.get_doc("CCTV Server", server)
	agent = sv.agent or frappe.db.get_value("CCTV Site Agent", {"farm": sv.farm})
	return {"ok": True, "command": queue(agent, "test_connection", {"server": server}, "CCTV Server", server)}


@frappe.whitelist()
def command_status(name):
	doc = frappe.get_doc("CCTV Agent Command", name)
	if doc.requested_by != frappe.session.user and not frappe.has_permission("CCTV Agent Command", "read", doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	return {"status": doc.status, "result": frappe.parse_json(doc.result) if doc.result else None, "file": doc.file, "error": doc.error}


@frappe.whitelist()
def create_cameras(server, channels):
	"""Camera setup wizard, step 2: create CCTV Cameras for the chosen discovered channels."""
	frappe.only_for(("System Manager", "Security Head"))
	from upande_security.cctv.settings import max_cameras

	sv = frappe.get_doc("CCTV Server", server)
	channels = frappe.parse_json(channels) if isinstance(channels, str) else channels
	limit = max_cameras(sv.farm)
	existing = frappe.db.count("CCTV Camera", {"farm": sv.farm, "enabled": 1})
	made = []
	for ch in channels:
		if limit and existing + len(made) >= limit:
			frappe.msgprint(_("Site licence allows {0} cameras; the rest were not added.").format(limit))
			break
		if frappe.db.exists("CCTV Camera", {"server": server, "channel_no": ch.get("channel_no")}):
			continue
		doc = frappe.get_doc({
			"doctype": "CCTV Camera", "camera_code": (ch.get("camera_code") or "").strip() or None,
			"camera_name": ch.get("camera_name") or ch.get("name") or f"Channel {ch.get('channel_no')}",
			"server": server, "channel_no": ch.get("channel_no"), "role": ch.get("role") or "Overview",
			"zone": ch.get("zone"), "gate": ch.get("gate"),
			"main_stream": ch.get("main_stream"), "sub_stream": ch.get("sub_stream"), "codec": ch.get("codec") or "",
			"resolution": ch.get("resolution"), "cap_anpr": 1 if ch.get("anpr") else 0, "cap_face": 1 if ch.get("face") else 0,
			"cap_motion": 1, "cap_line_crossing": 1 if ch.get("line_crossing") else 0, "cap_intrusion": 1 if ch.get("intrusion") else 0,
			"cap_ptz": 1 if ch.get("ptz") else 0,
		})
		doc.insert()
		made.append(doc.name)
	return {"ok": True, "created": made}


# ------------------------------------------------------------------ agent side

def _agent():
	from upande_security.cctv.ingest import _agent as authenticate

	return authenticate()


@frappe.whitelist()
def poll_commands():
	"""Agent: the commands waiting for it (marked Sent). Expired ones are closed."""
	agent = _agent()
	now = now_datetime()
	for name in frappe.get_all("CCTV Agent Command", filters={"agent": agent.name, "status": ["in", ["Queued", "Sent"]],
			"expires_at": ["<", now]}, pluck="name"):
		frappe.db.set_value("CCTV Agent Command", name, {"status": "Expired", "error": "Agent did not complete it in time."})
	out = []
	for c in frappe.get_all("CCTV Agent Command", filters={"agent": agent.name, "status": "Queued"},
			fields=["name", "command", "payload"], order_by="creation asc", limit=20):
		payload = frappe.parse_json(c.payload or "{}")
		if c.command == "enroll_face":
			payload["image_count"] = _face_image_urls(payload.get("person_profile"))
		out.append({"id": c.name, "command": c.command, "payload": payload})
		frappe.db.set_value("CCTV Agent Command", c.name, {"status": "Sent", "sent_at": now})
	frappe.db.commit()
	return {"commands": out}


def _face_image_urls(profile):
	"""How many images the agent should fetch (with fetch_face_image) - the files
	themselves are private and never handed out as links."""
	if not profile:
		return 0
	return frappe.db.count("CCTV Face Image", {"parent": profile, "parenttype": "CCTV Person Profile"})


@frappe.whitelist()
def fetch_face_image(command, index):
	"""Agent: one enrolment image for an enroll_face command it holds, base64."""
	import base64

	agent = _agent()
	doc = frappe.get_doc("CCTV Agent Command", command)
	if doc.agent != agent.name or doc.command != "enroll_face" or doc.status != "Sent":
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	profile = frappe.parse_json(doc.payload or "{}").get("person_profile")
	images = frappe.get_all("CCTV Face Image", filters={"parent": profile, "parenttype": "CCTV Person Profile"},
		fields=["image"], order_by="idx asc")
	i = int(index)
	if i >= len(images):
		frappe.throw(_("No such image."))
	f = frappe.get_doc("File", {"file_url": images[i].image})
	with open(f.get_full_path(), "rb") as fh:  # raw bytes; get_content() may hand back text
		content = fh.read()
	return {"index": i, "content": base64.b64encode(content).decode(), "count": len(images)}


@frappe.whitelist(methods=["POST"])
def command_result(command, status, result=None, error=None):
	"""Agent: outcome of one command."""
	agent = _agent()
	doc = frappe.get_doc("CCTV Agent Command", command)
	if doc.agent != agent.name:
		frappe.throw(_("Not this agent's command."), frappe.PermissionError)
	result = frappe.parse_json(result) if isinstance(result, str) else (result or {})
	doc.status = "Done" if status == "done" else "Failed"
	doc.result = frappe.as_json(result)
	doc.error = (error or "")[:1000] or None
	doc.done_at = now_datetime()
	doc.flags.ignore_permissions = True
	doc.save()
	if doc.status == "Done":
		try:
			_apply(doc, result)
		except Exception:
			frappe.log_error(title=f"CCTV command {doc.name} result could not be applied")
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def upload_command_file(command, filename=None):
	"""Agent: the file a command produced (evidence clip, snapshot) as the raw
	request body (signed), attached to the command and the record it was for. Private."""
	agent = _agent()
	doc = frappe.get_doc("CCTV Agent Command", command)
	if doc.agent != agent.name:
		frappe.throw(_("Not this agent's command."), frappe.PermissionError)
	content = frappe.request.get_data()
	if not content:
		frappe.throw(_("No file."))
	file_doc = frappe.get_doc({"doctype": "File", "file_name": filename or f"{doc.command}-{doc.name}", "content": content, "is_private": 1,
		"attached_to_doctype": doc.reference_doctype or "CCTV Agent Command",
		"attached_to_name": doc.reference_name or doc.name})
	file_doc.flags.ignore_permissions = True
	file_doc.insert()
	frappe.db.set_value("CCTV Agent Command", doc.name, "file", file_doc.file_url)
	return {"file_url": file_doc.file_url}


def _apply(doc, result):
	ref_dt, ref = doc.reference_doctype, doc.reference_name
	file_url = frappe.db.get_value("CCTV Agent Command", doc.name, "file")
	if doc.command == "export_clip" and ref_dt == "CCTV Alert" and file_url:
		frappe.db.set_value("CCTV Alert", ref, {"evidence_exported": 1, "evidence_file": file_url})
		frappe.get_doc("CCTV Alert", ref).add_comment("Info", _("Evidence clip exported from the recorder by {0}.").format(doc.requested_by))
	elif doc.command == "snapshot" and file_url and ref_dt == "CCTV Alert":
		frappe.db.set_value("CCTV Alert", ref, "snapshot", file_url)
	elif doc.command == "test_connection" and ref_dt == "CCTV Server":
		frappe.db.set_value("CCTV Server", ref, {k: v for k, v in {
			"status": result.get("status"), "model": result.get("model"), "firmware": result.get("firmware"),
			"time_offset_seconds": result.get("time_offset_seconds"), "last_seen": now_datetime(),
		}.items() if v is not None})
	elif doc.command == "survey_server":
		from upande_security.cctv.survey import save_survey

		survey = save_survey(result.get("report") or {}, server=(frappe.parse_json(doc.payload or "{}") or {}).get("server"),
			report_file=result.get("html_url") or file_url, command=doc.name)
		frappe.db.set_value("CCTV Agent Command", doc.name, "result", frappe.as_json({"survey": survey, "verdict": result.get("report", {}).get("verdict")}))
	elif doc.command == "enroll_face" and ref_dt == "CCTV Person Profile":
		from upande_security.cctv.presence import on_enrolled

		on_enrolled(ref, frappe.db.get_value("CCTV Site Agent", doc.agent, "farm"), result)
	elif doc.command == "delete_face" and ref_dt == "CCTV Person Profile":
		from upande_security.cctv.presence import on_deleted

		on_deleted(ref, frappe.db.get_value("CCTV Site Agent", doc.agent, "farm"))
