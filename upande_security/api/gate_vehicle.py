# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Gate-side lookup and verification for company vehicle/tractor tasks —
replaces the old Tractor Daily Task gate flow (create_gate_timesheet /
submit_gate_timesheet / mark_vehicle_task_completed), which was built
against custom_gate_entry_time / custom_gate_exit_time / custom_gate_status
/ custom_completion_note fields that were never actually added to Tractor
Daily Task. That's the root cause "the vehicles feature in the mobile app"
has never worked.

Mirrors api/gate_dispatch.py's architecture closely — config-driven via
Security Ops Settings' `vehicle_task_sources` child table (Vehicle Task
Source), read-only against the source, a dedicated audit-trail doctype
(Gate Vehicle Verification) rather than writing back to the source. Only
scoped down (no per-item content checks, no bulk/related-by-vehicle
grouping) — these are internal company vehicles, not external trucks
carrying goods under someone else's paperwork, so none of that
goods-shipment machinery applies here.

One Gate Vehicle Verification record per LEG of a trip, not per single
gate event: the exiting guard's scan CREATES the record (from_farm, exit
time/verifier/status); the entering guard's later scan at a DIFFERENT
gate — possibly hours later, possibly a different farm than anyone
expected, always a different login — finds that same open record (exit
recorded, entry still blank) and COMPLETES it (to_farm, entry time/
verifier/status), rather than creating a second record. A vehicle's full
round trip (Farm A -> Farm B -> back to Farm A) is therefore exactly two
records, each showing its own departure and arrival side by side.

from_farm/to_farm are resolved from the CALLING GUARD's own company/farm
(same resolution order as get_security_head_contact.py / issue_visitor_
badge.py: Employee linked to this login first, then Security Guard
matched by full name) — never from the source document's own farm field,
which only describes the task's "home" farm and would be identical
regardless of which gate is actually doing the check."""

import frappe
from frappe import _

from upande_security.api.feature_flags import require_feature
from upande_security.api.security_alerts import log_unauthorized_access


def _enabled_vehicle_task_sources():
	settings = frappe.get_single("Security Ops Settings")
	return [row for row in settings.vehicle_task_sources if row.enabled]


def _resolve_checking_farm(current_user):
	"""Which farm's gate the CALLING guard is physically stationed at -
	same resolution order as issue_visitor_badge.py / get_security_head_
	contact.py: Employee linked to this login first, then Security Guard
	matched by full name (Security Guard has no user_id field)."""
	employee = frappe.db.get_value("Employee", {"user_id": current_user}, "custom_farm")
	if employee:
		return employee
	user_full = frappe.db.get_value("User", current_user, "full_name") or ""
	if user_full:
		guard_farm = frappe.db.get_value("Security Guard", {"full_name": user_full}, "farm")
		if guard_farm:
			return guard_farm
	return None


def _recent_legs(reference_doctype, reference_name, limit=5):
	"""Most recent Gate Vehicle Verification legs for this reference,
	newest first - the guard's view into "where has this vehicle actually
	been", not a single verified/not-verified flag."""
	return frappe.db.get_all(
		"Gate Vehicle Verification",
		filters={"reference_doctype": reference_doctype, "reference_name": reference_name},
		fields=[
			"name", "from_farm", "to_farm", "task_description",
			"gate_exit_time", "gate_exit_verified_by", "gate_exit_status",
			"gate_entry_time", "gate_entry_verified_by", "gate_entry_status",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=limit,
	)


def _open_leg(reference_doctype, reference_name):
	"""The most recent leg for this reference that has an exit recorded
	but no entry yet - what an Entry scan should complete. None if every
	leg on file is already closed (or there are no legs at all), in which
	case an Entry scan starts a fresh leg of its own rather than attaching
	to something that was already finished."""
	return frappe.db.get_value(
		"Gate Vehicle Verification",
		{
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"gate_entry_time": ["is", "not set"],
		},
		"name",
		order_by="creation desc",
	)


def _lookup_in_source(source, reference):
	"""Try to find `reference` in this one configured source doctype.
	Returns a normalized dict, or None if nothing matched here."""
	filters = {source.reference_field: reference}
	name = frappe.db.get_value(source.source_doctype, filters, "name")
	if not name:
		return None

	fields = ["name"]
	field_map = {
		"vehicle": source.vehicle_field,
		"status": source.status_field,
		"description": source.description_field,
	}
	for f in field_map.values():
		if f:
			fields.append(f)

	doc_values = frappe.db.get_value(source.source_doctype, name, fields, as_dict=True)
	if not doc_values:
		return None

	status_value = doc_values.get(source.status_field) if source.status_field else None
	authorized = True
	if source.status_field and source.authorized_status_values:
		allowed = [v.strip() for v in source.authorized_status_values.split(",") if v.strip()]
		authorized = str(status_value) in allowed

	return {
		"reference_doctype": source.source_doctype,
		"reference_name": doc_values.get("name"),
		"vehicle_no": doc_values.get(source.vehicle_field) if source.vehicle_field else reference,
		"task_description": doc_values.get(source.description_field) if source.description_field else None,
		"source_status": status_value,
		"is_authorized": authorized,
		"recent_legs": _recent_legs(source.source_doctype, doc_values.get("name")),
	}


@frappe.whitelist()
def search_vehicle_task_for_gate(reference):
	"""Guard scans/types the vehicle's plate/serial number. Checks every
	enabled Vehicle Task Source in turn, returns the first match plus its
	recent leg history. Read-only — never touches the source document."""
	require_feature("feature_vehicle_gate_tracking")
	reference = (reference or "").strip()
	if not reference:
		frappe.response["message"] = {"found": False, "error": "A vehicle plate/serial number is required."}
		return

	for source in _enabled_vehicle_task_sources():
		try:
			match = _lookup_in_source(source, reference)
		except Exception as e:
			frappe.log_error("search_vehicle_task_for_gate source lookup: " + source.source_doctype, str(e))
			continue
		if match:
			match["found"] = True
			frappe.response["message"] = match
			return

	frappe.response["message"] = {"found": False, "error": "No vehicle task found for that reference."}


@frappe.whitelist()
def verify_vehicle_task_at_gate(reference, movement_type, gate_verification_status, remarks=None):
	"""Exit: always creates a NEW leg record - from_farm, exit time/
	verifier/status set, everything on the entry side left blank.

	Entry: finds the most recent OPEN leg for this reference (exit
	recorded, entry still blank) and completes it in place - to_farm,
	entry time/verifier/status. If no open leg exists (the vehicle's exit
	was never scanned anywhere, or every leg on file is already closed),
	creates a new leg with only the entry side filled in rather than
	silently dropping the scan - an "arrived with no logged departure" leg
	is itself useful information, not an error to hide.

	Re-resolves the source fresh each call (rather than trusting whatever
	the client cached from the search call) so the snapshot reflects the
	document at the moment of the actual gate decision."""
	require_feature("feature_vehicle_gate_tracking")
	reference = (reference or "").strip()
	movement_type = (movement_type or "").strip()
	gate_verification_status = (gate_verification_status or "").strip()
	if movement_type not in ("Exit", "Entry"):
		frappe.throw(_("movement_type must be 'Exit' or 'Entry'."))
	if gate_verification_status not in ("Verified", "Rejected"):
		frappe.throw(_("gate_verification_status must be 'Verified' or 'Rejected'."))

	match = None
	for source in _enabled_vehicle_task_sources():
		try:
			match = _lookup_in_source(source, reference)
		except Exception as e:
			frappe.log_error("verify_vehicle_task_at_gate source lookup: " + source.source_doctype, str(e))
			continue
		if match:
			break

	if not match:
		frappe.response["message"] = {"reference": reference, "error": "No vehicle task found for that reference."}
		return

	farm = _resolve_checking_farm(frappe.session.user)
	if not farm:
		frappe.response["message"] = {
			"reference": reference,
			"error": "Could not determine which farm's gate you're checking at - no Employee or "
			"Security Guard record linked to this login with a farm set.",
		}
		return

	now = frappe.utils.now_datetime()
	note = remarks.strip() if remarks else ""
	stamped_note = (
		("[" + movement_type + " @ " + farm + ", " + frappe.utils.format_datetime(now) + "] " + note)
		if note else ""
	)

	if movement_type == "Exit":
		doc = frappe.new_doc("Gate Vehicle Verification")
		doc.reference_doctype = match["reference_doctype"]
		doc.reference_name = match["reference_name"]
		doc.vehicle_no = match.get("vehicle_no")
		doc.task_description = match.get("task_description")
		doc.from_farm = farm
		doc.source_status = match.get("source_status")
		doc.gate_exit_time = now
		doc.gate_exit_verified_by = frappe.session.user
		doc.gate_exit_status = gate_verification_status
		doc.remarks = stamped_note
		doc.insert(ignore_permissions=True)
		leg_result = {"name": doc.name, "leg_complete": False}
	else:
		open_leg = _open_leg(match["reference_doctype"], match["reference_name"])
		if open_leg:
			doc = frappe.get_doc("Gate Vehicle Verification", open_leg)
			doc.to_farm = farm
			doc.gate_entry_time = now
			doc.gate_entry_verified_by = frappe.session.user
			doc.gate_entry_status = gate_verification_status
			if stamped_note:
				doc.remarks = ((doc.remarks + "\n") if doc.remarks else "") + stamped_note
			doc.save(ignore_permissions=True)
			leg_result = {"name": doc.name, "leg_complete": True}
		else:
			# Arrived with no logged departure anywhere - still record it,
			# as its own informative leg, rather than silently dropping
			# the scan or blocking the guard.
			doc = frappe.new_doc("Gate Vehicle Verification")
			doc.reference_doctype = match["reference_doctype"]
			doc.reference_name = match["reference_name"]
			doc.vehicle_no = match.get("vehicle_no")
			doc.task_description = match.get("task_description")
			doc.to_farm = farm
			doc.source_status = match.get("source_status")
			doc.gate_entry_time = now
			doc.gate_entry_verified_by = frappe.session.user
			doc.gate_entry_status = gate_verification_status
			doc.remarks = (
				"No matching Exit found on file for this arrival. " + stamped_note
			).strip()
			doc.insert(ignore_permissions=True)
			leg_result = {"name": doc.name, "leg_complete": False, "unmatched_entry": True}

	frappe.db.commit()

	if gate_verification_status == "Rejected":
		# Best-effort, never raises - see log_unauthorized_access's own
		# docstring. A guard actively turning a vehicle away at the gate is
		# the clearest "unauthorized access attempt" signal here.
		detail = (
			"Gate Vehicle Verification " + leg_result["name"] + " (" + movement_type + ") for "
			+ match["reference_doctype"] + " " + match["reference_name"] + " was rejected at the gate ("
			+ farm + ")."
		)
		if match.get("source_status"):
			detail = detail + " Source status: " + str(match["source_status"]) + "."
		if note:
			detail = detail + " Remarks: " + note
		log_unauthorized_access(
			"Gate Vehicle Rejected",
			match["reference_name"],
			detail,
			frappe.db.get_value("Farm", farm, "company") if farm else None,
			farm,
		)

	frappe.response["message"] = {
		"name": leg_result["name"],
		"reference_name": match["reference_name"],
		"farm": farm,
		"movement_type": movement_type,
		"gate_verification_status": gate_verification_status,
		"is_authorized": match.get("is_authorized"),
		"leg_complete": leg_result["leg_complete"],
		"unmatched_entry": leg_result.get("unmatched_entry", False),
	}
