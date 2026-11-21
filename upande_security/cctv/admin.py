# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Desk helpers for setting CCTV up: secrets, the agent's config file, demo data."""

import secrets

import frappe
from frappe import _

ADMIN_ROLES = ("System Manager", "Security Head")


@frappe.whitelist()
def generate_agent_secret(agent):
	"""New signing secret for a site agent. Shown ONCE - copy it to the box's
	secrets/agent_hmac; the old one stops working immediately."""
	frappe.only_for(ADMIN_ROLES)
	secret = secrets.token_urlsafe(32)
	doc = frappe.get_doc("CCTV Site Agent", agent)
	doc.hmac_secret = secret
	doc.save()
	return {"secret": secret}


@frappe.whitelist()
def generate_gateway_secret():
	"""New token secret shared with every site's media gateway (via the agent's
	config pull). Viewers already watching keep their stream; new tokens use the new one."""
	frappe.only_for(("System Manager",))
	doc = frappe.get_single("CCTV Settings")
	doc.gateway_jwt_secret = secrets.token_urlsafe(48)
	doc.save()
	return {"ok": True}


@frappe.whitelist()
def agent_config(agent):
	"""agent.yml for this agent, ready to paste on the site box (no secrets in it)."""
	frappe.only_for(ADMIN_ROLES)
	doc = frappe.get_doc("CCTV Site Agent", agent)
	tz = frappe.utils.get_system_timezone()
	return {"yaml": f"""agent:
  id: {doc.agent_id}
  erp_url: {frappe.utils.get_url()}
  api_key_file: /run/secrets/erp_api_key
  api_secret_file: /run/secrets/erp_api_secret
  hmac_secret_file: /run/secrets/agent_hmac
  site_timezone: {tz}
  batch_size: 100
  batch_interval_ms: 1000
  heartbeat_seconds: 30
  config_poll_seconds: 60
  health_seconds: 60
  upload_snapshots: true

buffer:
  path: /data/buffer.db
  max_size_mb: 20480
  site_config_cache: /data/site_config.json

gateway:
  api: http://127.0.0.1:9997
  auth_listen: 127.0.0.1:8765
  rtsp_port: 8554
  transcode_h265: false

log_level: INFO
""", "api_user": doc.api_user}


@frappe.whitelist()
def load_demo(farm):
	frappe.only_for(("System Manager",))
	from upande_security.cctv import simulator

	from upande_security.cctv.settings import clear, is_on

	clear()
	if not is_on("enabled"):
		frappe.throw(_("Switch CCTV on first: Security Ops Settings > CCTV Integration, then CCTV Settings > CCTV Module Enabled (and Alerts / Plate Recognition to see those)."))
	demo = simulator.seed_demo(farm)
	c = demo["cameras"]
	now = frappe.utils.now_datetime()
	at = lambda minutes: str(frappe.utils.add_to_date(now, minutes=minutes))  # noqa: E731
	results = [
		simulator.simulate(c["Gate In"], "plate_read", at=at(-90), confidence=0.96, plate="KDM 401J", direction="in"),
		simulator.simulate(c["Dock"], "plate_read", at=at(-60), confidence=0.91, plate="KDM 401J"),
		simulator.simulate(c["Gate In"], "plate_read", at=at(-40), confidence=0.97, plate="KZZ 111Q", direction="in"),
		simulator.simulate(c["Gate In"], "plate_read", at=at(-20), confidence=0.62, plate="KCB 7O8C", direction="in"),
		simulator.simulate(c["Gate Out"], "plate_read", at=at(-5), confidence=0.95, plate="KDM 401J", direction="out"),
		simulator.simulate(c["Cold Room Door"], "person_detected", at=str(now.replace(hour=21, minute=15, second=0)), confidence=0.9),
		simulator.simulate(c["Dock"], "tamper", at=at(-10), kind="covered"),
	]
	return {"demo": demo, "events": len(results)}


@frappe.whitelist()
def clear_demo():
	frappe.only_for(("System Manager",))
	from upande_security.cctv import simulator

	simulator.clear_demo()
	return {"ok": True}
