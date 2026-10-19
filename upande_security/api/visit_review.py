# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Host / secretary review of visits from the Security Dashboard.

The same workflow actions Desk shows on an Appointment (Approve Visit,
Reschedule, Redirect to Another Host, Reject Visit, Forward to Host,
Approve on Behalf of Host), offered on the dashboard's Visitors,
Contractors and Customers tabs. Which actions a user gets is the
workflow's own answer (frappe.model.workflow.get_transitions), so roles
and transitions stay configured in one place.

A user whose only access to appointments is hosting (see
appointment_events.host_sees_own_appointments) may act only on the visits
they host - the list is already narrowed for them, and review_visit
checks it again for a name passed in directly.
"""

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow, get_transitions

DOCTYPE = "Appointment"
REVIEW_STATES = ("Pending Host Review", "Pending Secretary Review")
# Visits booked longer ago than this are not offered for review - on live,
# hundreds of old walk-ins were never reviewed and are long gone.
REVIEW_WINDOW_DAYS = 7


def _own_employee_only(user):
	"""The user's Employee when they may review only the visits they host,
	"" when they have no Employee, None when their access is wider."""
	from upande_security.api.appointment_events import host_sees_own_appointments

	if host_sees_own_appointments(user) is None:
		return None
	return frappe.db.get_value("Employee", {"user_id": user}, "name") or ""


@frappe.whitelist()
def review_queue():
	"""Visits waiting for review that the current user can act on, newest
	first, each with the workflow actions open to them."""
	since = frappe.utils.add_days(frappe.utils.nowdate(), -REVIEW_WINDOW_DAYS)
	rows = frappe.get_list(
		DOCTYPE,
		filters={"workflow_state": ["in", REVIEW_STATES], "creation": [">=", since]},
		fields=[
			"name", "customer_name", "customer_phone_number", "customer_organization",
			"custom_visitor_type", "custom_meet_with", "scheduled_time", "customer_details",
			"workflow_state", "creation", "owner",
		],
		order_by="creation desc",
		limit_page_length=200,
	)
	me = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
	queue = []
	for row in rows:
		doc = frappe.get_doc(DOCTYPE, row.name)
		actions = list(dict.fromkeys(t.action for t in get_transitions(doc, raise_exception=True)))
		# Both approvals land on the same state; offer the one that fits who
		# is looking - the host approves, anyone else approves on their behalf.
		if me and row.custom_meet_with == me:
			actions = [a for a in actions if a != "Approve on Behalf of Host"]
		elif "Approve on Behalf of Host" in actions:
			actions = [a for a in actions if a != "Approve Visit"]
		if not actions:
			continue
		row.actions = actions
		row.host_name = (
			frappe.db.get_value("Employee", row.custom_meet_with, "employee_name")
			if row.custom_meet_with else None
		)
		queue.append(row)
	return queue


@frappe.whitelist(methods=["POST"])
def review_visit(name, action, scheduled_time=None, new_host=None, note=None):
	"""Apply one workflow action to a visit. Reschedule needs scheduled_time,
	Redirect to Another Host needs new_host; note is kept as a comment."""
	user = frappe.session.user
	doc = frappe.get_doc(DOCTYPE, name)

	own = _own_employee_only(user)
	if own is not None and (not own or doc.custom_meet_with != own):
		frappe.throw(_("You can only review visits you are hosting."), frappe.PermissionError)

	allowed = [t.action for t in get_transitions(doc, raise_exception=True)]
	if action not in allowed:
		frappe.throw(_("{0} is not available for this visit (now {1}).").format(action, doc.workflow_state))

	changed = False
	if action == "Reschedule":
		if not scheduled_time:
			frappe.throw(_("Choose the new date and time."))
		doc.scheduled_time = frappe.utils.get_datetime(scheduled_time)
		changed = True
	elif action == "Redirect to Another Host":
		if not new_host or not frappe.db.exists("Employee", new_host):
			frappe.throw(_("Choose the host to redirect to."))
		if new_host == doc.custom_meet_with:
			frappe.throw(_("Choose a different host."))
		doc.custom_meet_with = new_host
		changed = True
	if changed:
		doc.save()

	apply_workflow({"doctype": DOCTYPE, "name": name}, action)
	note = (note or "").strip()
	if note:
		frappe.get_doc(DOCTYPE, name).add_comment("Comment", action + ": " + note)

	return frappe.db.get_value(DOCTYPE, name, ["name", "workflow_state", "scheduled_time", "custom_meet_with"], as_dict=True)
