# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Drive the whole pipeline without a camera.

seed_demo(site) creates a demo NVR with gate, exit, dock and cold-room
cameras (names start with "DEMO"), a cold-room zone that allows anyone only
Mon-Sat 06:00-18:00, and an agent. simulate() builds a normal event envelope
and pushes it through the same store_event -> process_event path the real
agent uses, synchronously, so the result comes straight back.

System Manager only. Demo records are removed by clear_demo().
"""

import frappe
from frappe.utils import now_datetime

from upande_security.cctv.engine import process_event
from upande_security.cctv.ingest import store_event

DEMO = "DEMO"


def _only_admin():
	frappe.only_for("System Manager")


@frappe.whitelist()
def seed_demo(farm):
	_only_admin()
	agent_id = f"{DEMO}-{frappe.scrub(farm)}-agent"
	if not frappe.db.exists("CCTV Site Agent", agent_id):
		frappe.get_doc({"doctype": "CCTV Site Agent", "agent_id": agent_id, "farm": farm, "hmac_secret": frappe.generate_hash(length=32),
			"gateway_url": "https://media.demo.invalid"}).insert(ignore_permissions=True)
	server = frappe.db.get_value("CCTV Server", {"server_name": f"{DEMO} NVR", "farm": farm})
	if not server:
		server = frappe.get_doc({"doctype": "CCTV Server", "server_name": f"{DEMO} NVR", "farm": farm, "agent": agent_id,
			"brand": "Hikvision", "host": "10.0.0.10", "port": 80, "username": "demo", "password": "demo",
			"recording_mode": "Continuous"}).insert(ignore_permissions=True).name
	zone = frappe.db.get_value("Security Zone", {"zone_name": f"{DEMO} Cold Room", "farm": farm})
	if not zone:
		zone = frappe.get_doc({"doctype": "Security Zone", "zone_name": f"{DEMO} Cold Room", "farm": farm, "active": 1,
			"severity": "High", "default_access": "Deny",
			"access_rules": [{"effect": "Allow", "applies_to": "Anyone", "days": "All Days",
				"from_time": "06:00:00", "to_time": "18:00:00", "note": "Working hours"}]})
		zone.flags.ignore_mandatory = True
		zone.insert(ignore_permissions=True)
		zone = zone.name
	cams = {}
	for name, role, ch, extra in (
		("Gate In", "Entry", 1, {"cap_anpr": 1}),
		("Gate Out", "Exit", 2, {"cap_anpr": 1}),
		("Dock", "Dock", 3, {"cap_anpr": 1}),
		("Cold Room Door", "Cold Room", 4, {"cap_line_crossing": 1, "zone": zone}),
	):
		existing = frappe.db.get_value("CCTV Camera", {"camera_name": f"{DEMO} {name}", "server": server})
		if not existing:
			existing = frappe.get_doc({"doctype": "CCTV Camera", "camera_name": f"{DEMO} {name}", "server": server, "channel_no": ch,
				"role": role, "gate": "Main Gate" if role in ("Entry", "Exit") else None, "status": "Online",
				"analytics_provider": "Camera Native", "analytics_enabled": 1, **extra}).insert(ignore_permissions=True).name
		cams[name] = existing
	frappe.db.commit()
	return {"agent": agent_id, "server": server, "zone": zone, "cameras": cams}


@frappe.whitelist()
def simulate(camera, event_type, at=None, confidence=None, **data):
	"""One event through the real pipeline. `at` is site-local time (default now)."""
	_only_admin()
	import pytz
	from frappe.utils import get_datetime

	when = get_datetime(at) if at else now_datetime()
	tz = pytz.timezone(frappe.utils.get_system_timezone())
	iso = tz.localize(when).astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
	data = {k: v for k, v in data.items() if k not in ("cmd",)}
	env = {"event_id": f"SIM-{frappe.generate_hash(length=12)}", "schema_version": "1.0", "camera": camera,
		"event_type": event_type, "event_time": iso, "source": {"provider": "simulator", "model_version": "sim"},
		"confidence": float(confidence) if confidence is not None else None, "data": data}
	status, ref = store_event(env)
	if status != "accepted":
		return {"status": status, "ref": ref}
	result = process_event(ref)
	return {"status": status, "event": ref, "result": result}


DEMO_PLATE = "KDE 220M"


def seed_demo_booking(farm, at=None):
	"""A booked, host-approved visitor arriving by car today, so a gate read of
	DEMO_PLATE matches an appointment. Written directly (db_insert): no SMS,
	no email, no workflow notifications go out for it."""
	name = f"APMT-DEMO-{frappe.scrub(farm)}"
	if frappe.db.exists("Appointment", name):
		return name
	when = frappe.utils.get_datetime(at) if at else frappe.utils.now_datetime()
	doc = frappe.get_doc({
		"doctype": "Appointment", "name": name, "customer_name": "Demo Visitor", "customer_organization": "Demo Supplies Ltd",
		"scheduled_time": when, "custom_expected_exit": frappe.utils.add_to_date(when, hours=2),
		"custom_meet_with_farm": farm, "custom_farmunit": farm, "custom_meet_with_name": "Demo Host",
		"custom_company": frappe.db.get_value("Farm", farm, "company"),
		"custom_visitor_type": "Visitor", "custom_mode_of_transport": "Vehicle",
		"custom_vehicles_number_plate": DEMO_PLATE, "custom_vehicles_colour": "White",
		"custom_visit_purpose": "Demo - CCTV plate matching", "status": "Open", "workflow_state": "Approved by Host",
	})
	doc.db_insert()
	return name


@frappe.whitelist()
def clear_demo(farm=None):
	"""Delete everything the demo created or caused."""
	_only_admin()
	cams = frappe.get_all("CCTV Camera", filters={"camera_name": ["like", f"{DEMO} %"]}, pluck="name")
	for dt, field in (("CCTV Review Item", None), ("CCTV Vehicle Sighting", "camera"), ("CCTV Person Sighting", "camera"),
			("CCTV Alert", "camera"), ("CCTV Vehicle Visit", "entry_camera"), ("CCTV Event", "camera"),
			("CCTV Live View Log", "camera"), ("CCTV Playback Log", "camera")):
		if field:
			names = frappe.get_all(dt, filters={field: ["in", cams or ["-"]]}, pluck="name")
		else:
			names = frappe.get_all(dt, filters={"sighting": ["in", frappe.get_all("CCTV Vehicle Sighting", filters={"camera": ["in", cams or ["-"]]}, pluck="name") or ["-"]]}, pluck="name")
		for n in names:
			frappe.delete_doc(dt, n, ignore_permissions=True, force=True, delete_permanently=True)
	for v in frappe.get_all("CCTV Vehicle Visit", filters={"exit_camera": ["in", cams or ["-"]]}, pluck="name"):
		frappe.delete_doc("CCTV Vehicle Visit", v, ignore_permissions=True, force=True, delete_permanently=True)
	for n in cams:
		frappe.delete_doc("CCTV Camera", n, ignore_permissions=True, force=True, delete_permanently=True)
	for dt, filters in (("CCTV Server", {"server_name": f"{DEMO} NVR"}), ("Security Zone", {"zone_name": f"{DEMO} Cold Room"}),
			("CCTV Site Agent", {"agent_id": ["like", f"{DEMO}-%"]})):
		for n in frappe.get_all(dt, filters=filters, pluck="name"):
			frappe.delete_doc(dt, n, ignore_permissions=True, force=True, delete_permanently=True)
	for name in frappe.get_all("Appointment", filters={"name": ["like", "APMT-DEMO-%"]}, pluck="name"):
		frappe.db.delete("Appointment", {"name": name})
	frappe.db.commit()
	return True
