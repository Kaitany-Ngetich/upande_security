# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Alert delivery channels. Each returns (status, error); a channel that fails
falls back to On Screen so the alert is never silently lost.

	On Screen  Notification Log + realtime toast in Desk / dashboard
	Email      frappe.sendmail (queued)
	Push       the guard's Security app (Expo push, same path as security messages)
	SMS        SMS Settings, through the app's existing sender (api/visitor_sms.py)
	WhatsApp   the frappe_whatsapp app, when installed
	Telegram   CCTV Settings > Telegram Bot Token / Chat ID (one group per site setup)
"""

import frappe

from upande_security.cctv.settings import get_settings


def _plain(html):
	from frappe.utils import strip_html_tags

	return strip_html_tags((html or "").replace("<br>", "\n")).strip()


def _phone(user):
	return frappe.db.get_value("User", user, "mobile_no") or frappe.db.get_value("User", user, "phone")


def on_screen(user, subject, body, alert):
	note = frappe.new_doc("Notification Log")
	note.for_user = user
	note.type = "Alert"
	note.subject = subject
	note.email_content = body
	note.document_type = "CCTV Alert"
	note.document_name = alert
	note.insert(ignore_permissions=True)
	return "Sent", None


def email(user, subject, body, alert):
	addr = frappe.db.get_value("User", user, "email")
	if not addr:
		return "Failed", "no email"
	frappe.sendmail(recipients=[addr], subject=subject, message=body, reference_doctype="CCTV Alert", reference_name=alert)
	return "Queued", None


def push(user, subject, body, alert):
	from upande_security.api.notifications import _resolve_owner_push_token, _send_expo_push

	token = _resolve_owner_push_token(user)
	if not token:
		return "Failed", "no app on this user's phone"
	_send_expo_push([{"to": token, "sound": "default", "priority": "high", "title": subject, "body": _plain(body)[:180],
		"channelId": "security-alerts", "data": {"type": "cctv_alert", "alert": alert}}])
	return "Sent", None


def sms(user, subject, body, alert, link=None):
	number = _phone(user)
	if not number:
		return "Failed", "no mobile number"
	from upande_security.api.visitor_sms import send_system_sms

	text = f"{subject}\n{_plain(body).splitlines()[1] if len(_plain(body).splitlines()) > 1 else ''}\n{link or ''}".strip()
	send_system_sms([number], text[:450])
	return "Sent", None


def whatsapp(user, subject, body, alert, link=None):
	if not frappe.db.exists("DocType", "WhatsApp Message"):
		return "Failed", "frappe_whatsapp is not installed"
	number = _phone(user)
	if not number:
		return "Failed", "no mobile number"
	digits = "".join(ch for ch in number if ch.isdigit())
	if digits.startswith("0"):
		digits = "254" + digits[1:]
	frappe.get_doc({"doctype": "WhatsApp Message", "type": "Outgoing", "to": digits, "content_type": "text",
		"message": f"*{subject}*\n{_plain(body)}"[:1500], "reference_doctype": "CCTV Alert", "reference_name": alert}).insert(ignore_permissions=True)
	return "Queued", None


def telegram(user, subject, body, alert, link=None):
	s = frappe.get_single("CCTV Settings")
	token = s.get_password("telegram_bot_token", raise_exception=False)
	if not (token and s.telegram_chat_id):
		return "Failed", "Telegram bot not configured"
	import requests

	r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=10,
		json={"chat_id": s.telegram_chat_id, "text": f"{subject}\n{_plain(body)}"[:3500], "disable_web_page_preview": True})
	return ("Sent", None) if r.ok else ("Failed", f"Telegram {r.status_code}")


SENDERS = {"On Screen": on_screen, "Email": email, "Push": push, "SMS": sms, "WhatsApp": whatsapp, "Telegram": telegram}
_GROUP_ONCE = {"Telegram"}  # one message to the group, not one per recipient


def deliver(channel, user, subject, body, alert, link, sent_group):
	"""(status, error, fell_back). Group channels send once per alert."""
	if channel in _GROUP_ONCE:
		if channel in sent_group:
			return "Sent", "group already told", False
		sent_group.add(channel)
	fn = SENDERS.get(channel, on_screen)
	try:
		status, error = fn(user, subject, body, alert, link) if channel in ("SMS", "WhatsApp", "Telegram") else fn(user, subject, body, alert)
	except Exception as e:
		status, error = "Failed", str(e)[:200]
	if status == "Failed" and channel != "On Screen":
		on_screen(user, subject, body, alert)
		return status, error, True
	return status, error, False
