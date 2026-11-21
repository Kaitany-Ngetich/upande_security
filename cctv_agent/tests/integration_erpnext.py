"""Agent <-> ERPNext integration, in-process (no web server, no cameras).

Sends requests signed by the agent's own ERP client through Frappe's WSGI app,
so the real auth, signature check, ingest, heartbeat and config endpoints run.
Needs Redis up. Cleans up after itself.

	cd ~/frappe-bench/sites && ../env/bin/python ../apps/upande_security/cctv_agent/tests/integration_erpnext.py
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import frappe  # noqa: E402
import frappe.app  # noqa: E402
from werkzeug.test import Client  # noqa: E402

from cctv_agent.envelope import make_event  # noqa: E402
from cctv_agent.erp import ERP  # noqa: E402

SITE, FARM, USER = "mysite.local", "Kapkolia", "cctv-agent-test@example.com"
ok = fail = 0


def check(label, cond, extra=""):
	global ok, fail
	ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
	print("  PASS" if cond else "  FAIL", label, "" if cond else extra)


def connect():
	frappe.init(site=SITE, sites_path=".")
	frappe.connect()
	frappe.set_user("Administrator")


connect()
from upande_security.cctv import settings, simulator  # noqa: E402
import atexit  # noqa: E402


@atexit.register
def _always_off():
	"""Even if setup crashes: leave the module switched off and the demo gone."""
	try:
		if not getattr(frappe.local, "db", None):
			connect()
		simulator.clear_demo()
		if frappe.db.exists("User", USER):
			frappe.delete_doc("User", USER, ignore_permissions=True, force=True)
		frappe.db.sql("update `tabSingles` set value='0' where doctype='CCTV Settings' and field in %s", (tuple(settings.SWITCHES),))
		frappe.db.commit()
	except Exception as e:
		print("cleanup:", e)


orig = {k: frappe.db.get_single_value("CCTV Settings", k) for k in settings.SWITCHES}
frappe.db.set_single_value("CCTV Settings", "enabled", 1)
frappe.db.set_single_value("CCTV Settings", "anpr_enabled", 1)
demo = simulator.seed_demo(FARM)
hmac_secret = frappe.get_doc("CCTV Site Agent", demo["agent"]).get_password("hmac_secret")
if not frappe.db.exists("User", USER):
	frappe.get_doc({"doctype": "User", "email": USER, "first_name": "CCTV Agent Test", "send_welcome_email": 0,
		"user_type": "System User", "roles": [{"role": "CCTV Agent"}]}).insert(ignore_permissions=True)
user = frappe.get_doc("User", USER)
api_key, api_secret = frappe.generate_hash(length=15), frappe.generate_hash(length=15)
user.api_key, user.api_secret = api_key, api_secret
user.save(ignore_permissions=True)
frappe.db.commit()
cam = demo["cameras"]["Gate In"]
frappe.destroy()

erp = ERP(f"http://{SITE}", api_key, api_secret, demo["agent"], hmac_secret)
wsgi = Client(frappe.app.application)


def send(method, name, **kw):
	req = erp._sign(erp.client.build_request(method, erp.url + "/api/method/upande_security.cctv.ingest." + name, **kw))
	headers = {k: v for k, v in req.headers.items() if k.lower() not in ("host", "content-length")}
	r = wsgi.open(req.url.raw_path.decode(), method=method, data=req.content if method != "GET" else None,
		headers={**headers, "Host": SITE})
	return r.status_code, (json.loads(r.data) if r.data and r.data.lstrip().startswith(b"{") else r.data)


try:
	print("agent -> ERPNext")
	ev = make_event(FARM, cam, "plate_read", datetime(2026, 11, 12, 5, 22, tzinfo=timezone.utc),
		{"plate": "KDB 076A", "direction": "in"}, 0.95)
	code, body = send("POST", "ingest_events", json={"events": [ev]})
	res = body["message"]["results"][0] if code == 200 else body
	check("signed batch accepted", code == 200 and res["status"] == "accepted", (code, str(body)[:300]))
	code, body = send("POST", "ingest_events", json={"events": [ev]})
	check("resend reported as duplicate", code == 200 and body["message"]["results"][0]["status"] == "duplicate", body)

	bad = ERP(f"http://{SITE}", api_key, api_secret, demo["agent"], "wrong-secret")
	req = bad._sign(bad.client.build_request("POST", bad.url + "/api/method/upande_security.cctv.ingest.ingest_events", json={"events": [ev]}))
	r = wsgi.open(req.url.raw_path.decode(), method="POST", data=req.content,
		headers={**{k: v for k, v in req.headers.items() if k.lower() not in ("host", "content-length")}, "Host": SITE})
	check("wrong signing secret refused (401)", r.status_code == 401, r.status_code)

	code, body = send("POST", "agent_heartbeat", json={"version": "0.1.0", "queue_depth": 3, "cpu": 12.5,
		"cameras": [{"camera": cam, "state": "online"}]})
	check("heartbeat accepted", code == 200 and body["message"]["ok"], body)

	code, body = send("GET", "get_site_config")
	cfg = body.get("message") if code == 200 else {}
	check("site config has this site's cameras", code == 200 and any(c["name"] == cam for c in cfg.get("cameras", [])), (code, str(body)[:200]))
	check("recorder password delivered to the agent only", any(s.get("password") == "demo" for s in cfg.get("servers", [])))

	connect()
	from upande_security.cctv.engine import process_event
	name = frappe.db.get_value("CCTV Event", {"event_id": ev["event_id"]})
	process_event(name)
	visit = frappe.db.get_value("CCTV Vehicle Sighting", {"event": name}, "vehicle_visit")
	check("agent's plate read became a matched visit",
		frappe.db.get_value("CCTV Vehicle Visit", visit, "appointment") == "APMT-Hillary maiyo-1293348", visit)
	check("agent marked online", frappe.db.get_value("CCTV Site Agent", demo["agent"], "status") == "Online")
finally:
	if not frappe.db:
		connect()
	frappe.set_user("Administrator")
	simulator.clear_demo()
	frappe.delete_doc("User", USER, ignore_permissions=True, force=True)
	for k, v in orig.items():
		frappe.db.set_single_value("CCTV Settings", k, 0)  # tests always leave the module OFF
	frappe.db.commit()
	print(f"\n{ok} passed, {fail} failed. Cleaned up.")
