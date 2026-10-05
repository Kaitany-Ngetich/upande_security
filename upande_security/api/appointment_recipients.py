# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Extra people copied on every new appointment, on top of the host.

The host already gets the "Visitor at Reception" email (a Frappe Notification
on Appointment/New, addressed to custom_meet_with_email). Reception, a
security head, or a farm manager often needs the same heads-up, and who that
is differs per farm - so the list lives in Security Ops Settings'
Appointment Notification Recipients table rather than in the Notification
records, which have no farm awareness.

Recipients are picked from the Employee list, so the email and WhatsApp/
mobile number come off the Employee record rather than being retyped; either
can still be overridden per row for someone whose record is incomplete.

A row with a farm set only fires for appointments at that farm; a row with
the farm left blank fires for every farm. The host is never double-mailed,
and the whole thing is best-effort: a mail failure must never block the
appointment from being registered.
"""
import frappe

from upande_security.api.feature_flags import is_feature_enabled
from upande_security.upande_security.doctype.appointment_notification_recipient.appointment_notification_recipient import (
	employee_contact,
)


def _appointment_farm(doc):
	"""Which farm this appointment belongs to. custom_meet_with_farm is set
	from the host's own Employee record and is what the rest of the app
	keys off (see visitor_approved_alert); custom_farmunit is the gate-side
	stamp applied at check-in, used as a fallback for appointments created
	before a host farm was resolvable."""
	return (doc.get("custom_meet_with_farm") or doc.get("custom_farmunit") or "").strip()


def resolve_recipients(doc):
	"""{"emails": [...], "whatsapp": [(name, number), ...]} for this
	appointment's farm, minus the host (mailed separately) and duplicates."""
	settings = frappe.get_single("Security Ops Settings")
	rows = settings.get("appointment_notification_recipients") or []
	empty = {"emails": [], "whatsapp": []}
	if not rows:
		return empty

	farm = _appointment_farm(doc)
	host_email = (doc.get("custom_meet_with_email") or "").strip().lower()

	emails, whatsapp, seen_mail, seen_num = [], [], set(), set()
	for row in rows:
		if not row.enabled:
			continue
		row_farm = (row.farm or "").strip()
		if row_farm and row_farm != farm:
			continue

		email = (row.email or "").strip()
		number = (row.whatsapp_no or "").strip()
		if row.employee and not (email and number):
			emp_email, emp_phone = employee_contact(row.employee)
			email = email or (emp_email or "")
			number = number or (emp_phone or "")

		if email and email.lower() != host_email and email.lower() not in seen_mail:
			seen_mail.add(email.lower())
			emails.append(email)
		if number and number not in seen_num:
			seen_num.add(number)
			whatsapp.append((row.employee_name or row.employee or email or number, number))

	return {"emails": emails, "whatsapp": whatsapp}


def _build_message(doc, farm):
	# Every value here is visitor- or guard-entered free text landing in an
	# HTML email, so escape all of it - same convention as
	# gate_receiving._notify_receiving_team.
	esc = frappe.utils.escape_html
	rows = [
		("Visitor", doc.get("customer_name")),
		("Type", doc.get("custom_visitor_type")),
		("Phone", doc.get("customer_phone_number")),
		("Host", doc.get("custom_meet_with_name") or doc.get("custom_meet_with")),
		("Company", doc.get("custom_meet_with_company")),
		("Farm", farm),
		("Scheduled", doc.get("scheduled_time")),
		("Purpose", doc.get("custom_visit_purpose") or doc.get("customer_details")),
	]
	body = (
		"<p>A new appointment has been registered. You are receiving this because "
		"you are on the appointment notification list"
		+ (" for <strong>" + esc(farm) + "</strong>." if farm else ".")
		+ "</p><table cellpadding='6' cellspacing='0' border='0'>"
	)
	for label, value in rows:
		if value:
			body += (
				"<tr><td style='color:#6b7280'>" + esc(label) + "</td>"
				"<td><strong>" + esc(str(value)) + "</strong></td></tr>"
			)
	body += "</table><p><a href='" + frappe.utils.get_url_to_form("Appointment", doc.name) + "'>Open the appointment</a></p>"
	return body


def _host_whatsapp_config():
	"""The host's own WhatsApp alert, so the extra recipients get the very
	same message rather than a second, differently-worded one.

	Read live instead of hardcoded: the template's name differs per site
	(staging carries visitor_host_alert_v2-en), and if someone re-points the
	host alert at a new template the copies follow it automatically.

	Returns (template, account, [fieldnames for the body parameters]) or
	None when frappe_whatsapp isn't installed / no host alert is set up.
	"""
	if not frappe.db.exists("DocType", "WhatsApp Notification"):
		return None
	row = frappe.db.get_value(
		"WhatsApp Notification",
		{"reference_doctype": "Appointment", "doctype_event": "After Insert", "disabled": 0},
		["name", "template", "whatsapp_account"],
		as_dict=True,
	)
	if not row or not row.template:
		return None
	fields = frappe.get_all(
		"WhatsApp Message Fields",
		filters={"parent": row.name},
		order_by="idx asc",
		pluck="field_name",
	)
	return row.template, row.whatsapp_account, fields


def _send_whatsapp(doc, farm, people):
	"""Copy the host's WhatsApp alert to each configured recipient.

	WhatsApp Business only delivers pre-approved templates for messages a
	business starts, so this deliberately reuses the host's approved
	template and its parameter values - every recipient sees exactly what
	the host saw. Security Ops Settings can override the template/account
	for a site that wants a separate one.
	"""
	host_cfg = _host_whatsapp_config()
	template = (frappe.db.get_single_value("Security Ops Settings", "appointment_whatsapp_template") or "").strip()
	account = (frappe.db.get_single_value("Security Ops Settings", "appointment_whatsapp_account") or "").strip()
	param_fields = ["custom_meet_with_name", "customer_name", "custom_visit_purpose"]
	if host_cfg:
		host_template, host_account, host_fields = host_cfg
		template = template or host_template
		account = account or host_account
		# The host alert's own field list, minus any trailing non-body
		# entries (the fixture carries `name` after the three body params).
		body = [f for f in host_fields if f != "name"]
		if body:
			param_fields = body
	if not template:
		frappe.logger("upande_security").info(
			"appointment %s: no WhatsApp template (none configured and no host alert), skipped %d recipient(s)"
			% (doc.name, len(people))
		)
		return
	if not frappe.db.exists("DocType", "WhatsApp Message"):
		frappe.logger("upande_security").info(
			"appointment %s: frappe_whatsapp not installed, skipped %d WhatsApp recipient(s)"
			% (doc.name, len(people))
		)
		return

	params = [str(doc.get(f) or "") for f in param_fields]
	for name, number in people:
		try:
			msg = frappe.new_doc("WhatsApp Message")
			msg.type = "Outgoing"
			msg.to = number
			msg.content_type = "text"
			msg.message_type = "Template"
			msg.use_template = 1
			msg.template = template
			msg.template_parameters = frappe.as_json(params)
			if account:
				msg.whatsapp_account = account
			msg.reference_doctype = "Appointment"
			msg.reference_name = doc.name
			msg.insert(ignore_permissions=True)
		except Exception as e:
			# One bad number must never stop the rest, nor the email.
			frappe.log_error("appointment WhatsApp to " + str(number), str(e))


def notify_extra_recipients(doc, method=None):
	"""Appointment after_insert hook. Best-effort by design - an appointment
	must still be registered even if mail is misconfigured or a recipient
	address is bad."""
	try:
		if not is_feature_enabled("feature_appointment_extra_recipients"):
			return
		targets = resolve_recipients(doc)
		farm = _appointment_farm(doc)
		if targets["whatsapp"]:
			_send_whatsapp(doc, farm, targets["whatsapp"])
		if not targets["emails"]:
			return
		subject = "New appointment: " + (doc.get("customer_name") or doc.name)
		if farm:
			subject += " (" + farm + ")"
		# Queued, not now=True: the guard's registration request should not
		# wait on an SMTP round-trip, and a queued mail is retried by
		# Frappe's own scheduler instead of failing here.
		frappe.sendmail(
			recipients=targets["emails"],
			subject=subject,
			message=_build_message(doc, farm),
			reference_doctype="Appointment",
			reference_name=doc.name,
		)
	except Exception as e:
		frappe.log_error("appointment_recipients.notify_extra_recipients " + str(doc.name), str(e))
