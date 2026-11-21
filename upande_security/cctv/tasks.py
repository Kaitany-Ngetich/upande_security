# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Scheduled CCTV jobs. Each one does nothing while the module is off."""

import frappe
from frappe.utils import add_days, now_datetime

from upande_security.cctv.settings import get_settings, is_on


def every_minute():
	if not is_on("enabled"):
		return
	from upande_security.cctv import alerts, rules

	for fn in (alerts.escalate_due, rules.check_states, _review_sla):
		try:
			fn()
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"CCTV scheduled job {fn.__name__} failed")


def every_five_minutes():
	if not is_on("enabled"):
		return
	from upande_security.cctv.vehicles import check_open_visits

	check_open_visits()
	frappe.db.commit()


def end_of_day():
	if not is_on("enabled"):
		return
	from upande_security.cctv.vehicles import close_day

	close_day()
	frappe.db.commit()


def _review_sla():
	"""Review items the gate has not handled in time go to the supervisor."""
	from upande_security.cctv.alerts import _role_users

	late = frappe.get_all("CCTV Review Item", filters={"status": "Open", "sla_due": ["<", now_datetime()]},
		fields=["name", "plate", "farm", "reason"], limit=200)
	if not late:
		return
	supervisors = _role_users(["Security Head", "Security Manager"])
	for item in late:
		frappe.db.set_value("CCTV Review Item", item.name, "status", "Escalated")
		for user in supervisors:
			note = frappe.new_doc("Notification Log")
			note.for_user = user
			note.type = "Alert"
			note.subject = f"CCTV review waiting: {item.plate} ({item.reason})"
			note.document_type = "CCTV Review Item"
			note.document_name = item.name
			note.insert(ignore_permissions=True)


def purge_old_records():
	"""Daily: enforce the retention periods in CCTV Settings. Alerts, visits
	and review items are business records and are kept; raw events,
	sightings and logs are not."""
	s = get_settings()
	plan = [
		("CCTV Event", "event_time", s.retention_events_days),
		("CCTV Vehicle Sighting", "sighting_time", s.retention_sightings_days),
		("CCTV Person Sighting", "sighting_time", s.retention_sightings_days),
		("CCTV Live View Log", "started_at", s.retention_audit_days),
		("CCTV Playback Log", "opened_at", s.retention_audit_days),
	]
	for doctype, field, days in plan:
		if not days:
			continue
		cutoff = add_days(now_datetime(), -int(days))
		names = frappe.get_all(doctype, filters={field: ["<", cutoff]}, pluck="name", limit=5000)
		for name in names:
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True, delete_permanently=True)
		frappe.db.commit()
