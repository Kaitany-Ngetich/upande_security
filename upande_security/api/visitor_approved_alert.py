# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Notifies the guard(s) actually ON DUTY RIGHT NOW at a farm the moment a
host approves a visit (workflow_state -> "Approved by Host"), so gate staff
know the visitor is coming and can check them in without the visitor
having to explain who they're there for.

Scoped to the specific guard(s), not the whole farm's roster - if Anita is
the one currently on shift, she's the only one who gets this, not every
guard who has ever been assigned to that farm. "On duty right now" reads
Security Guard Shift Assignment's own status field (kept current by
tasks.refresh_shift_statuses, which runs hourly and is the same
time-aware status this app's coverage board and missed-checkin checks
already rely on) rather than re-deriving shift math here.

A farm can have more than one currently-Active shift assignment at once
(different posts/blocks staffed simultaneously), so this can resolve to
more than one guard - every one of them currently on duty at that farm
gets notified, never guards off duty or at a different farm.

Reuses the same Guard Device Token + Expo push pattern sos_alert.py uses
for nearby-guard SOS alerts, on its own channel/data type so the mobile
app can tell the two apart and route/style them differently.
"""

import json
import urllib.request

import frappe

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
VISITOR_APPROVED_CHANNEL_ID = "visitor-approved"


def _send_expo_push(messages):
	"""Fire-and-forget batch send to Expo's push API. Never raises - a
	push-delivery failure must not block the host's approval from saving."""
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
		frappe.log_error("Visitor approved push send", str(e))
		return {"sent": 0, "error": str(e)}


def _on_duty_tokens(farm):
	"""Expo push tokens for every guard with a currently-Active Security
	Guard Shift Assignment at `farm` right now. A guard with no registered
	Guard Device Token (never opened the app / no push permission) is
	silently skipped, same as every other push path in this app."""
	shifts = frappe.get_all(
		"Security Guard Shift Assignment",
		filters={"farm": farm, "status": "Active"},
		fields=["security_guard", "internal_guard", "external_guard"],
		ignore_permissions=True,
	)

	tokens = []
	for s in shifts:
		if s.security_guard == "Internal Guard" and s.internal_guard:
			token = frappe.db.get_value(
				"Guard Device Token",
				{"guard_type": "Internal Guard", "internal_guard": s.internal_guard},
				"expo_push_token",
			)
		elif s.security_guard == "External Guard" and s.external_guard:
			token = frappe.db.get_value(
				"Guard Device Token",
				{"guard_type": "External Guard", "external_guard": s.external_guard},
				"expo_push_token",
			)
		else:
			continue

		if token:
			tokens.append(token)

	return tokens


def notify_gate_guards_on_host_approval(doc, method=None):
	"""Appointment on_update hook. Fires exactly once per real transition
	into "Approved by Host" - has_value_changed guards against every other
	save (e.g. a later checkout) re-sending the same push."""
	if not doc.has_value_changed("workflow_state"):
		return
	if doc.workflow_state != "Approved by Host":
		return
	if not doc.custom_meet_with_farm:
		# Nothing to scope this to - skip rather than guess or broadcast.
		return

	push_tokens = _on_duty_tokens(doc.custom_meet_with_farm)
	if not push_tokens:
		return

	host_name = None
	if doc.custom_meet_with:
		host_name = frappe.db.get_value("Employee", doc.custom_meet_with, "employee_name")

	visitor_name = doc.customer_name or "A visitor"
	body = visitor_name + " was approved to see " + (host_name or "their host") + " at " + doc.custom_meet_with_farm

	messages = []
	for token in push_tokens:
		messages.append(
			{
				"to": token,
				"priority": "high",
				"sound": "default",
				"title": "Visitor approved - ready to check in",
				"body": body,
				"data": {
					"type": "visitor_approved",
					"appointment_name": doc.name,
					"visitor_name": visitor_name,
					"host_name": host_name or "",
					"farm": doc.custom_meet_with_farm,
				},
				"channelId": VISITOR_APPROVED_CHANNEL_ID,
			}
		)

	_send_expo_push(messages)
