# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Visitor-facing SMS: an informational OTP + welcome message sent to the
visitor's own phone the moment they're actually checked in at the gate,
and a thank-you SMS the moment they're checked out.

Deliberately tied to check-in, not booking - a scheduled visit might sit
booked for days and never arrive, or get rescheduled; the SMS only means
anything once the visitor is actually walking in. Also deliberately
informational only, not a verification gate - the guard never asks for or
checks this code against anything.

Reuses Frappe's own generic SMS gateway
(frappe.core.doctype.sms_settings.sms_settings.send_sms) rather than a
bespoke HTTP call to one specific provider - this app has no opinion on
which SMS gateway a given Kaitet Group instance wires up, and send_sms()
already no-ops cleanly (a msgprint, not an exception) if Security Ops
Settings' host site hasn't configured "SMS Settings" yet.

Called two different ways, deliberately:

1. Directly, by name, from every mobile check-in/check-out Server Script
   ("Check In Visitor", "Create Walk In", "Check Out Visitor") - all three
   write straight to the DB (frappe.db.set_value, or doc.insert() without a
   workflow_state-driven save), so there is no single on_update transition
   that reliably covers every one of them. Calling send_checkin_otp/
   send_checkout_thankyou directly from each is what actually works, same
   reason visitor_badge_qr.py's release_badge_on_checkout is called both
   from a hook AND directly inside check_out_visitor.py.

2. Via on_appointment_update (an Appointment on_update doc_event) - covers
   the Desk-only path, a host/secretary manually flipping workflow_state
   through Frappe's own workflow engine (apply_workflow -> a real
   doc.save()), which none of the mobile scripts above ever touch.
"""

import random

import frappe

from upande_security.api.feature_flags import is_feature_enabled


def _normalize_kenyan_number(raw):
	"""Same normalization as the WhatsApp host-alert fix ("Appointment Host
	WA Number" Server Script) - most visitor phone numbers are typed in
	local format ("0707196203") but any real SMS gateway needs E.164-style
	international format ("254707196203")."""
	digits = "".join(ch for ch in (raw or "") if ch.isdigit())
	if not digits:
		return None
	if digits[0] == "0":
		digits = "254" + digits[1:]
	elif not digits.startswith("254"):
		digits = "254" + digits
	return digits


def _send(number, message):
	from frappe.core.doctype.sms_settings.sms_settings import send_sms

	send_sms([number], message, success_msg=False)


def send_checkin_otp(appointment_name):
	"""Best-effort, self-contained: takes just the Appointment's name (not a
	loaded doc) so it's cheap to call directly from a Server Script right
	after a raw frappe.db.set_value/doc.insert() call, with no risk of
	acting on stale in-memory field values. Never resends for the same
	appointment (custom_visitor_otp already set is treated as "already
	handled"), so a second check-in-adjacent save is a safe no-op."""
	if not is_feature_enabled("feature_visitor_sms_otp"):
		return
	try:
		row = frappe.db.get_value(
			"Appointment",
			appointment_name,
			["customer_phone_number", "custom_meet_with_company", "custom_visitor_otp"],
			as_dict=True,
		)
		if not row or row.custom_visitor_otp:
			return
		number = _normalize_kenyan_number(row.customer_phone_number)
		if not number:
			return

		otp = str(random.randint(100000, 999999))
		frappe.db.set_value(
			"Appointment", appointment_name, "custom_visitor_otp", otp, update_modified=False
		)

		company = row.custom_meet_with_company or "us"
		message = "Welcome to " + company + "! Your visit code is " + otp + "."
		_send(number, message)
	except Exception as e:
		frappe.log_error("send_checkin_otp", str(e))


def send_checkout_thankyou(appointment_name):
	"""Same by-name, best-effort shape as send_checkin_otp."""
	if not is_feature_enabled("feature_visitor_sms_otp"):
		return
	try:
		row = frappe.db.get_value(
			"Appointment",
			appointment_name,
			["customer_phone_number", "custom_meet_with_company"],
			as_dict=True,
		)
		if not row:
			return
		number = _normalize_kenyan_number(row.customer_phone_number)
		if not number:
			return

		company = row.custom_meet_with_company or "us"
		message = "Thanks for visiting " + company + ", welcome again!"
		_send(number, message)
	except Exception as e:
		frappe.log_error("send_checkout_thankyou", str(e))


def on_appointment_update(doc, method=None):
	"""Appointment on_update doc_event - Desk-path parity only. The mobile
	Server Scripts call send_checkin_otp/send_checkout_thankyou directly
	(see module docstring); this exists so a host/secretary flipping
	workflow_state by hand in Desk still triggers the same SMS."""
	if not doc.has_value_changed("workflow_state"):
		return
	if doc.workflow_state == "Visitor Checked In":
		send_checkin_otp(doc.name)
	elif doc.workflow_state == "Visitor Checked Out":
		send_checkout_thankyou(doc.name)
