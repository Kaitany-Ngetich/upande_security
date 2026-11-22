# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Site surveys of CCTV recorders: what they are, what they can send, how
healthy they are (their own exception log), which API calls work, and a
verdict on how they fit. Run by the site agent (survey_server command) or on
a technician's laptop (python -m cctv_agent.survey) and imported here.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

ADMIN = ("System Manager", "Security Head")


@frappe.whitelist()
def request_survey(server, days=7, streams=1):
	frappe.only_for(ADMIN)
	from upande_security.cctv.commands import queue

	sv = frappe.get_doc("CCTV Server", server)
	agent = sv.agent or frappe.db.get_value("CCTV Site Agent", {"farm": sv.farm})
	name = queue(agent, "survey_server", {"server": server, "days": int(days), "streams": bool(int(streams))}, "CCTV Server", server)
	return {"ok": True, "command": name}


def save_survey(rep, server=None, farm=None, source="Site Agent", report_file=None, command=None):
	"""One CCTV Site Survey from a report dict (schema cctv-survey/1)."""
	if (rep or {}).get("schema") != "cctv-survey/1":
		frappe.throw(_("This is not a CCTV survey report."))
	d, t, caps = rep.get("device") or {}, rep.get("target") or {}, rep.get("capabilities") or {}
	chans = rep.get("channels") or []
	codecs = sorted({str(s.get("codec")).upper() for c in chans for s in (c.get("main"), c.get("sub")) if s and s.get("codec")})
	disks = rep.get("storage") or []
	logs = (rep.get("logs") or {}).get("summary") or {}
	api = rep.get("api") or []
	doc = frappe.get_doc({
		"doctype": "CCTV Site Survey", "server": server, "farm": farm or (frappe.db.get_value("CCTV Server", server, "farm") if server else None),
		"verdict": rep.get("verdict"), "surveyed_at": get_datetime((rep.get("surveyed_at") or "").replace("T", " ")[:19]) if rep.get("surveyed_at") else now_datetime(),
		"source": source, "brand": t.get("brand"), "host": t.get("host"), "model": d.get("model"), "firmware": d.get("firmwareVersion"),
		"serial_number": d.get("serialNumber"), "channels": len(chans), "channels_online": sum(1 for c in chans if c.get("online")),
		"codecs": ", ".join(codecs), "events_usable": ", ".join((rep.get("events") or {}).get("normalised") or []),
		"anpr": 1 if caps.get("anpr") else 0, "face": 1 if caps.get("face") else 0, "playback": 1 if caps.get("playback") else 0,
		"disks_ok": 1 if disks and all(str(x.get("status", "")).lower() in ("ok", "normal", "success", "idle", "") for x in disks) else 0,
		"ntp": 1 if (rep.get("time") or {}).get("ntp") else 0, "clock_offset_seconds": (rep.get("time") or {}).get("offset_seconds"),
		"log_issues": sum(v for k, v in logs.items() if k != "other"),
		"log_summary": ", ".join(f"{k}: {v}" for k, v in sorted(logs.items(), key=lambda x: -x[1])),
		"api_answered": sum(1 for c in api if c.get("ok")), "api_calls": len(api),
		"findings": "\n".join(f"[{f['level'].upper()}] {f['topic']}: {f['text']}" for f in rep.get("findings") or []),
		"report_file": report_file, "report": frappe.as_json(rep), "command": command,
	})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.insert()
	if server:
		frappe.db.set_value("CCTV Server", server, {k: v for k, v in {"model": d.get("model"), "firmware": d.get("firmwareVersion"),
			"time_offset_seconds": (rep.get("time") or {}).get("offset_seconds"), "last_seen": now_datetime() if doc.api_answered else None,
			"status": "Online" if doc.api_answered else "Offline"}.items() if v is not None})
	return doc.name


@frappe.whitelist()
def import_survey(file_url, server=None, html_file_url=None):
	"""A survey run on a laptop (survey-<host>.json, optionally its .html), attached to Desk and imported."""
	frappe.only_for(ADMIN)
	f = frappe.get_doc("File", {"file_url": file_url})
	with open(f.get_full_path(), "rb") as fh:
		rep = frappe.parse_json(fh.read().decode())
	return {"ok": True, "survey": save_survey(rep, server=server or None, source="Imported", report_file=html_file_url)}
