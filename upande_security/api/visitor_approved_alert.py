# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Notifies gate app devices AT THE SAME FARM the moment a host approves a
visit (workflow_state -> "Approved by Host"), so gate staff know the
visitor is coming and can check them in without the visitor having to
explain who they're there for.

Strictly farm-scoped, not a broadcast - a guard at one farm's gate must
never see push notifications for visits happening at a different farm.
Guard Device Token has no farm field of its own, so a token's farm is
derived from whichever record it's linked to:
  - Internal Guard -> Employee.custom_farm
  - External Guard -> Security Guard.farm
  - App User       -> no farm source exists (an App User row only exists
    because _resolve_calling_guard found no Employee/Security Guard record
    for that login at all - see sos_alert.py's own resolution order), so
    these are always excluded rather than guessed at or broadcast to.

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


def _farm_scoped_tokens(farm):
	"""Every Guard Device Token whose linked Employee/Security Guard record
	is stamped to `farm`. App User rows are always excluded - see module
	docstring."""
	tokens = frappe.get_all(
		"Guard Device Token",
		filters={"expo_push_token": ["is", "set"]},
		fields=["guard_type", "internal_guard", "external_guard", "expo_push_token"],
		ignore_permissions=True,
	)

	matched = []
	for t in tokens:
		if t.guard_type == "Internal Guard" and t.internal_guard:
			guard_farm = frappe.db.get_value("Employee", t.internal_guard, "custom_farm")
		elif t.guard_type == "External Guard" and t.external_guard:
			guard_farm = frappe.db.get_value("Security Guard", t.external_guard, "farm")
		else:
			continue

		if guard_farm and guard_farm == farm:
			matched.append(t.expo_push_token)

	return matched


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

	push_tokens = _farm_scoped_tokens(doc.custom_meet_with_farm)
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
