# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Tell the people a reporter picked under an Incident Report's Notify table.

The guard filing the report (app or Desk) picks who should know - the
responsible person, their supervisor - and each of them gets, once:

- the incident shared with them, read-only, so the links below open even
  for someone who cannot otherwise see Incident Reports;
- an entry in their ERP notification bell;
- a push notification, when they use the app;
- an email;
- and, only when none of those could reach them (no login, no email - most
  guards and farm workers), an SMS to the mobile on their Employee record.

The account is the one linked on the Employee, else an enabled user with
exactly the employee's name - many people have a login nobody linked to
their Employee record. A name shared by several users matches none of them:
better unreached and visible on the row than the wrong person told.

Runs on every save (Incident Report on_update), but only for rows not yet
notified - re-saving never notifies anyone twice, and a person added later
is notified on that save. Each row records when and how. Delivery problems
are logged and never stop the report from saving.
"""

import frappe

from upande_security.api.notifications import _resolve_owner_push_token, _send_expo_push


def notify_people(doc, method=None):
	"""Incident Report on_update."""
	pending = [row for row in doc.get("notify_persons") or [] if row.employee and not row.notified_at]
	if not pending:
		return
	subject, body = _message(doc)
	for row in pending:
		user, note = _user_for(row.employee)
		try:
			via = _notify_one(doc, row.employee, user, subject, body)
		except Exception:
			frappe.log_error("Incident notify " + doc.name + " -> " + row.employee, frappe.get_traceback())
			via = []
		# Straight to the row: a doc.save() here would run this hook again.
		frappe.db.set_value(
			"Incident Notify Person",
			row.name,
			{
				"user": user,
				"notified_at": frappe.utils.now_datetime(),
				"notified_via": ", ".join(via) or note or "No login, email or app",
			},
			update_modified=False,
		)


def _user_for(employee):
	"""(user, note): the Employee's linked login, else the one enabled user
	whose full name matches the employee's exactly (case and spacing aside).
	note explains an unmatched or ambiguous name."""
	emp = frappe.db.get_value("Employee", employee, ["user_id", "employee_name"], as_dict=True) or {}
	if emp.get("user_id"):
		return emp["user_id"], None
	name = " ".join((emp.get("employee_name") or "").split())
	if not name:
		return None, None
	matches = frappe.db.sql(
		"""
		SELECT name FROM `tabUser`
		WHERE enabled = 1 AND name NOT IN ('Guest', 'Administrator')
		  AND LOWER(TRIM(full_name)) = LOWER(%s)
		LIMIT 2
		""",
		(name,),
		pluck=True,
	)
	if len(matches) == 1:
		return matches[0], None
	if len(matches) > 1:
		return None, "Several users named " + name + " - link the right one on the Employee"
	return None, None


def _message(doc):
	where = doc.location or doc.get("farm") or ""
	subject = "Incident {0}: {1} ({2}){3}".format(
		doc.name, doc.nature_of_incident or "Incident", doc.severity or "", " at " + where if where else ""
	)
	body = "{0} reported {1}{2}.".format(
		doc.reporter_name or doc.reported_by or "Security",
		(doc.nature_of_incident or "an incident").lower(),
		" at " + where if where else "",
	)
	if doc.description:
		body += "\n\n" + doc.description[:500]
	return subject, body


def _notify_one(doc, employee, user, subject, body):
	"""Returns the channels that went out. user: the account from _user_for."""
	emp = frappe.db.get_value(
		"Employee", employee, ["prefered_email", "company_email", "personal_email"], as_dict=True
	) or {}
	via = []

	if user:
		frappe.share.add_docshare(
			"Incident Report", doc.name, user, read=1, notify=0, flags={"ignore_share_permission": True}
		)
		log = frappe.new_doc("Notification Log")
		log.update(
			{
				"for_user": user,
				"type": "Alert",
				"document_type": "Incident Report",
				"document_name": doc.name,
				"subject": subject,
				"email_content": body,
				"from_user": doc.reported_by if doc.reported_by and frappe.db.exists("User", doc.reported_by) else None,
			}
		)
		log.insert(ignore_permissions=True)
		via.append("ERP")

		token = _resolve_owner_push_token(user)
		if token:
			_send_expo_push(
				[
					{
						"to": token,
						"sound": "default",
						"title": subject,
						"body": body[:180],
						"data": {"type": "incident", "name": doc.name},
					}
				]
			)
			via.append("App")

	email = emp.get("prefered_email") or emp.get("company_email") or emp.get("personal_email")
	if not email and user:
		email = frappe.db.get_value("User", user, "email")
	if email:
		frappe.sendmail(
			recipients=[email],
			subject=subject,
			message=frappe.utils.escape_html(body).replace("\n", "<br>")
			+ "<br><br>"
			+ '<a href="{0}">Open {1}</a>'.format(frappe.utils.get_url_to_form("Incident Report", doc.name), doc.name),
			reference_doctype="Incident Report",
			reference_name=doc.name,
		)
		via.append("Email")
	if not via:
		mobile = _mobile(employee)
		if mobile and frappe.db.get_single_value("SMS Settings", "sms_gateway_url"):
			# After the commit and off the request: a gateway call per person
			# would otherwise hold up the guard's submit.
			frappe.enqueue(
				"upande_security.api.incident_notify.send_sms",
				number=mobile,
				message=_sms_text(doc),
				enqueue_after_commit=True,
			)
			via.append("SMS")
	return via


def _mobile(employee):
	"""The employee's mobile in the gateway's 2547... form, or None."""
	from upande_security.api.visitor_sms import _normalize_kenyan_number

	fields = ["cell_number"]
	if frappe.get_meta("Employee").has_field("custom_phone_number"):
		fields.append("custom_phone_number")
	row = frappe.db.get_value("Employee", employee, fields, as_dict=True) or {}
	for f in fields:
		number = _normalize_kenyan_number(row.get(f))
		# A whole Kenyan mobile only (2547... / 2541..., 12 digits): a short or
		# mistyped number would spend credit on an SMS that cannot arrive.
		if number and len(number) == 12 and number[3] in "17":
			return number
	return None


def _sms_text(doc):
	"""Kept to one SMS (160 characters): no link - they have no login to open it."""
	where = doc.location or doc.get("farm") or ""
	text = "Incident {0}: {1} ({2}){3}. Reported by {4}. Contact security for details.".format(
		doc.name,
		doc.nature_of_incident or "Incident",
		doc.severity or "",
		" at " + where if where else "",
		doc.reporter_name or "Security",
	)
	return text[:160]


def send_sms(number, message):
	"""Background job. Never raises."""
	try:
		from frappe.core.doctype.sms_settings.sms_settings import send_sms as frappe_send_sms

		frappe_send_sms([number], message, success_msg=False)
	except Exception:
		frappe.log_error("Incident notify SMS", frappe.get_traceback())
