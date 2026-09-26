# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Two small notification-bell backend pieces for the mobile app:

1. A personal "your visitor's status changed" push to whoever personally
   handled a given Appointment — resolved off `doc.owner`, NOT
   `frappe.session.user`, since the hook runs under whoever is saving the
   workflow transition (a secretary or host), not the guard who needs to
   know about it. Every walk-in/contractor-checkin/booking flow in this app
   creates the Appointment via `frappe.new_doc(...).insert()` under the
   acting guard's own session, so `doc.owner` is already the right "who
   handled this" signal.

2. A manually-triggered broadcast (e.g. "an app update is ready tonight")
   to every registered device, gated to System Manager/Security Head.

Reuses the same Guard Device Token + Expo push pattern as sos_alert.py and
visitor_approved_alert.py. Kept as its own copy of `_send_expo_push` rather
than importing from either of those, matching this app's established
convention of not sharing code between these alert modules. Both pushes
here reuse the existing `visitor-approved` Android channel (already defined
client-side) rather than inventing a new one — same routine-info priority.
"""

import json
import urllib.request

import frappe

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
VISITOR_APPROVED_CHANNEL_ID = "visitor-approved"

# Every decision state on the Appointment Visitor Review workflow worth a
# personal ping, mapped to a human-readable fragment for the push body.
# Purely internal/no-op transitions (Open, Pending Secretary/Host Review,
# Visitor Checked In/Out) are deliberately left out.
STATUS_FRAGMENTS = {
	"Approved by Secretary": "was approved by the secretary",
	"Rejected by Secretary": "was rejected by the secretary",
	"Rescheduled by Secretary": "was rescheduled by the secretary",
	"Redirected to Another Host": "was redirected to another host",
	"Approved by Host": "was approved by the host",
	"Rejected by Host": "was rejected by the host",
	"Rescheduled by Host": "was rescheduled by the host",
}


def _send_expo_push(messages):
	"""Fire-and-forget batch send to Expo's push API. Never raises - a
	push-delivery failure must not block the workflow transition from
	saving, or the broadcast endpoint from reporting a result."""
	if not messages:
		return {"sent": 0}
	try:
		body = json.dumps(messages).encode()
		req = urllib.request.Request(
			EXPO_PUSH_URL,
			data=body,
			headers={"Content-Type": "application/json", "Accept": "application/json"},
			method="POST",
		)
		with urllib.request.urlopen(req, timeout=10) as resp:
			result = json.loads(resp.read())
		return {"sent": len(messages), "expo_response": result}
	except Exception as e:
		frappe.log_error("Notifications push send", str(e))
		return {"sent": 0, "error": str(e)}


def _resolve_owner_push_token(owner):
	"""Resolves a push token for an arbitrary Appointment.owner - NOT the
	calling user. Same identity chain as sos_alert.py's
	_resolve_calling_guard, but parameterized on the owner instead of
	frappe.session.user: Employee via user_id -> Internal Guard token; else
	Security Guard via full_name match on the owner's User.full_name ->
	External Guard token; else a Guard Device Token keyed on the owner
	directly as an App User. Returns None if nothing resolves at any step."""
	employee_name = frappe.db.get_value("Employee", {"user_id": owner}, "name")
	if employee_name:
		return frappe.db.get_value(
			"Guard Device Token",
			{"guard_type": "Internal Guard", "internal_guard": employee_name},
			"expo_push_token",
		)

	user_full = frappe.db.get_value("User", owner, "full_name")
	if user_full:
		guard_name = frappe.db.get_value("Security Guard", {"full_name": user_full}, "name")
		if guard_name:
			return frappe.db.get_value(
				"Guard Device Token",
				{"guard_type": "External Guard", "external_guard": guard_name},
				"expo_push_token",
			)

	return frappe.db.get_value(
		"Guard Device Token",
		{"guard_type": "App User", "app_user": owner},
		"expo_push_token",
	)


def notify_owner_on_status_change(doc, method=None):
	"""Appointment on_update hook, independent of and in addition to
	visitor_approved_alert.notify_gate_guards_on_host_approval. Fires
	exactly once per real transition into one of STATUS_FRAGMENTS -
	has_value_changed guards against every other save re-sending the same
	push. Notifies only the guard who personally owns this Appointment,
	never the whole farm's on-duty roster."""
	if not doc.has_value_changed("workflow_state"):
		return
	fragment = STATUS_FRAGMENTS.get(doc.workflow_state)
	if not fragment:
		return
	if not doc.owner or doc.owner == frappe.session.user:
		# No one to notify, or the owner is the one making this exact save -
		# no need to tell someone about their own action.
		return

	push_token = _resolve_owner_push_token(doc.owner)
	if not push_token:
		return

	visitor_name = doc.customer_name or "Your visitor"
	body = visitor_name + " " + fragment

	message = {
		"to": push_token,
		"priority": "high",
		"sound": "default",
		"title": "Visitor status update",
		"body": body,
		"data": {
			"type": "appointment_status",
			"appointment_name": doc.name,
			"visitor_name": visitor_name,
			"workflow_state": doc.workflow_state,
		},
		"channelId": VISITOR_APPROVED_CHANNEL_ID,
	}

	_send_expo_push([message])


@frappe.whitelist()
def broadcast_notification(title, body):
	"""Manually-triggered announcement (e.g. "an app update is ready
	tonight") to every registered Guard Device Token - not tied to any
	document. System Manager/Security Head only."""
	roles = frappe.get_roles(frappe.session.user)
	if "System Manager" not in roles and "Security Head" not in roles:
		frappe.throw("Not permitted to send broadcast notifications", frappe.PermissionError)

	tokens = frappe.get_all("Guard Device Token", pluck="expo_push_token", ignore_permissions=True)
	push_tokens = [t for t in tokens if t]

	messages = []
	for token in push_tokens:
		messages.append(
			{
				"to": token,
				"priority": "high",
				"sound": "default",
				"title": title,
				"body": body,
				"data": {
					"type": "announcement",
					"title": title,
					"body": body,
				},
				"channelId": VISITOR_APPROVED_CHANNEL_ID,
			}
		)

	send_result = _send_expo_push(messages)

	frappe.response["message"] = {"sent_to": len(push_tokens), "push_result": send_result}
