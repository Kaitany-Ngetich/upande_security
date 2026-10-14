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

WHAT THE GUARD CAN SCAN (two kinds of reference, either works):
- An Asset's QR label (the "Asset QR Label" print format encodes
  https://<site>/app/asset/<name>). Every vehicle and machine is an Asset,
  but not every one leaving a farm has a task. The asset's open task is
  looked up in the configured sources (via the source's Link-to-Asset
  field, e.g. Tractor Task.tractor); with none, the movement is still
  logged against the Asset itself, marked "No task assigned".
- A task's own reference (its name, its QR URL, or the source's configured
  Reference Field, e.g. a plate).
When an Asset is known, legs are keyed on it, so a vehicle that left on a
task scan can come back on an asset-label scan and still close its leg.

This is the gate's MOVEMENT log. Patrol sightings of assets (is it still
there?) go to Asset Scan Log via security_api.scan_asset instead - the two
are separate on purpose: one records a vehicle crossing a gate, the other
records an asset seen in place.

from_farm/to_farm are resolved from the CALLING GUARD's own company/farm
(same resolution order as get_security_head_contact.py / issue_visitor_
badge.py: Employee linked to this login first, then Security Guard
matched by full name) — never from the source document's own farm field,
which only describes the task's "home" farm and would be identical
regardless of which gate is actually doing the check."""

import urllib.parse

import frappe
from frappe import _

from upande_security.api.feature_flags import require_feature
from upande_security.api.gate_movement import resolve_gate
from upande_security.api.security_alerts import log_unauthorized_access

_RETIRED_ASSET_STATUSES = ("Sold", "Scrapped", "Cancelled")


def _enabled_vehicle_task_sources():
	settings = frappe.get_single("Security Ops Settings")
	return [row for row in settings.vehicle_task_sources if row.enabled]


def _resolve_checking_farm(current_user, linked_only=False):
	"""Which farm's gate the CALLING guard is physically stationed at -
	same resolution order as issue_visitor_badge.py / get_security_head_
	contact.py: Employee linked to this login first, then Security Guard
	matched by full name (Security Guard has no user_id field), then -
	unless linked_only - the farm the guard chose in the app
	(gate_movement.requested_farm), for logins linked to no farm at all."""
	employee = frappe.db.get_value("Employee", {"user_id": current_user}, "custom_farm")
	if employee:
		return employee
	user_full = frappe.db.get_value("User", current_user, "full_name") or ""
	if user_full:
		guard_farm = frappe.db.get_value("Security Guard", {"full_name": user_full}, "farm")
		if guard_farm:
			return guard_farm
	if linked_only:
		return None
	from upande_security.api.gate_movement import requested_farm

	return requested_farm()


def _parse_scan(reference):
	"""(doctype or None, name) from what the camera read.

	A Desk URL (https://<site>/app/<doctype-slug>/<name>) names its own
	doctype; anything else is a bare reference with no doctype implied.
	"""
	reference = (reference or "").strip()
	if "/app/" in reference:
		path = reference.split("/app/", 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")
		parts = path.split("/")
		if len(parts) >= 2:
			doctype = frappe.unscrub(parts[0])
			return doctype, urllib.parse.unquote(parts[1]).strip()
	return None, reference


def _asset_link_field(source):
	"""The source doctype's field that links to Asset - its configured Vehicle
	Field when that is one, else the first Link-to-Asset field (Tractor
	Task.tractor). None when the source has no such field."""
	meta = frappe.get_meta(source.source_doctype)
	if source.vehicle_field:
		df = meta.get_field(source.vehicle_field)
		if df and df.fieldtype == "Link" and df.options == "Asset":
			return df.fieldname
	for df in meta.fields:
		if df.fieldtype == "Link" and df.options == "Asset":
			return df.fieldname
	return None


def _valid_field(meta, fieldname):
	"""fieldname if it is a real column on this doctype, else None - a
	mistyped setting (e.g. a field's label instead of its name) is skipped
	rather than failing every lookup."""
	if fieldname and (fieldname == "name" or meta.has_field(fieldname)):
		return fieldname
	return None


def _task_match(source, name):
	"""Normalised match dict for one source document."""
	meta = frappe.get_meta(source.source_doctype)
	vehicle_field = _valid_field(meta, source.vehicle_field)
	status_field = _valid_field(meta, source.status_field)
	description_field = _valid_field(meta, source.description_field)
	asset_field = _asset_link_field(source)

	fields = ["name"] + [f for f in (vehicle_field, status_field, description_field, asset_field) if f]
	values = frappe.db.get_value(source.source_doctype, name, list(dict.fromkeys(fields)), as_dict=True)
	if not values:
		return None

	status_value = values.get(status_field) if status_field else None
	authorized = True
	if status_field and source.authorized_status_values:
		allowed = [v.strip() for v in source.authorized_status_values.split(",") if v.strip()]
		authorized = str(status_value) in allowed

	asset = values.get(asset_field) if asset_field else None
	vehicle_no = values.get(vehicle_field) if vehicle_field else None
	if not vehicle_no and asset:
		vehicle_no = frappe.db.get_value("Asset", asset, "asset_name") or asset

	return {
		"reference_doctype": source.source_doctype,
		"reference_name": values.name,
		"asset": asset,
		"has_task": True,
		"vehicle_no": vehicle_no or values.name,
		"task_description": values.get(description_field) if description_field else None,
		"source_status": status_value,
		"is_authorized": authorized,
	}


def _lookup_in_source(source, doctype_hint, name):
	"""Find `name` in this one source: as the document's own name, then by the
	configured Reference Field. A URL for a different doctype is skipped."""
	if doctype_hint and doctype_hint != source.source_doctype:
		return None
	if frappe.db.exists(source.source_doctype, name):
		return _task_match(source, name)
	if doctype_hint:
		return None
	meta = frappe.get_meta(source.source_doctype)
	reference_field = _valid_field(meta, source.reference_field)
	if not reference_field or reference_field == "name":
		return None
	found = frappe.db.get_value(source.source_doctype, {reference_field: name}, "name")
	return _task_match(source, found) if found else None


def _open_task_for_asset(source, asset):
	"""This asset's most recent task in one source. Restricted to the source's
	Authorized Status Values when those are configured, so a finished task
	is not picked up for today's trip."""
	asset_field = _asset_link_field(source)
	if not asset_field:
		return None
	meta = frappe.get_meta(source.source_doctype)
	filters = {asset_field: asset}
	status_field = _valid_field(meta, source.status_field)
	if status_field and source.authorized_status_values:
		allowed = [v.strip() for v in source.authorized_status_values.split(",") if v.strip()]
		filters[status_field] = ["in", allowed]
	found = frappe.db.get_value(source.source_doctype, filters, "name", order_by="modified desc")
	return _task_match(source, found) if found else None


def _asset_only_match(asset):
	"""A vehicle with no task: the movement is logged against the Asset."""
	status_label = "Cancelled" if asset.docstatus == 2 else asset.status
	return {
		"reference_doctype": "Asset",
		"reference_name": asset.name,
		"asset": asset.name,
		"has_task": False,
		"vehicle_no": asset.asset_name or asset.name,
		"task_description": "No task assigned",
		"source_status": status_label,
		"is_authorized": not (asset.docstatus == 2 or asset.status in _RETIRED_ASSET_STATUSES),
	}


def _resolve_vehicle(reference):
	"""Asset label or task reference -> match dict, or None."""
	doctype_hint, name = _parse_scan(reference)
	if not name:
		return None
	sources = _enabled_vehicle_task_sources()

	if doctype_hint in (None, "Asset"):
		asset = frappe.db.get_value(
			"Asset", name, ["name", "asset_name", "status", "docstatus"], as_dict=True
		)
		if asset:
			for source in sources:
				try:
					match = _open_task_for_asset(source, asset.name)
				except Exception as e:
					frappe.log_error("vehicle gate task-for-asset lookup: " + source.source_doctype, str(e))
					continue
				if match:
					return match
			return _asset_only_match(asset)
		if doctype_hint == "Asset":
			return None

	for source in sources:
		try:
			match = _lookup_in_source(source, doctype_hint, name)
		except Exception as e:
			frappe.log_error("vehicle gate source lookup: " + source.source_doctype, str(e))
			continue
		if match:
			return match
	return None


def _leg_filters(match):
	"""Legs belong to the Asset when one is known - so a vehicle that left on a
	task scan and returns on its asset label is the same trip - else to the
	task reference."""
	if match.get("asset"):
		return {"asset": match["asset"]}
	return {"reference_doctype": match["reference_doctype"], "reference_name": match["reference_name"]}


def _recent_legs(match, limit=5):
	"""Most recent Gate Vehicle Verification legs for this vehicle, newest
	first - the guard's view into "where has this vehicle actually been"."""
	return frappe.db.get_all(
		"Gate Vehicle Verification",
		filters=_leg_filters(match),
		fields=[
			"name", "from_farm", "to_farm", "task_description",
			"gate_exit_time", "gate_exit_verified_by", "gate_exit_status",
			"gate_entry_time", "gate_entry_verified_by", "gate_entry_status",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=limit,
	)


def _open_leg(match):
	"""The most recent leg with an exit recorded but no entry yet - what an
	Entry scan should complete. None if every leg is already closed."""
	filters = dict(_leg_filters(match))
	filters["gate_entry_time"] = ["is", "not set"]
	return frappe.db.get_value("Gate Vehicle Verification", filters, "name", order_by="creation desc")


@frappe.whitelist()
def search_vehicle_task_for_gate(reference):
	"""Guard scans an Asset's QR label, or a task's QR / plate / reference.
	Returns the vehicle's open task (or the Asset alone when it has none) plus
	its recent legs. Read-only."""
	require_feature("feature_vehicle_gate_tracking")
	reference = (reference or "").strip()
	if not reference:
		frappe.response["message"] = {"found": False, "error": "Scan the vehicle's asset label or its task."}
		return

	match = _resolve_vehicle(reference)
	if not match:
		frappe.response["message"] = {"found": False, "error": "No vehicle asset or task found for that reference."}
		return

	match["found"] = True
	match["recent_legs"] = _recent_legs(match)
	frappe.response["message"] = match


@frappe.whitelist()
def verify_vehicle_task_at_gate(reference, movement_type, gate_verification_status, remarks=None, gate=None):
	"""Exit: always creates a NEW leg record - from_farm, exit time/
	verifier/status set, everything on the entry side left blank.

	Entry: finds the most recent OPEN leg for this vehicle (exit recorded,
	entry still blank) and completes it in place - to_farm, entry time/
	verifier/status. If no open leg exists (the vehicle's exit was never
	scanned anywhere, or every leg on file is already closed), creates a new
	leg with only the entry side filled in rather than silently dropping the
	scan - an "arrived with no logged departure" leg is itself useful
	information, not an error to hide.

	Re-resolves the vehicle fresh each call (rather than trusting whatever the
	client cached from the search call) so the snapshot reflects the moment
	of the actual gate decision."""
	require_feature("feature_vehicle_gate_tracking")
	reference = (reference or "").strip()
	movement_type = (movement_type or "").strip()
	gate_verification_status = (gate_verification_status or "").strip()
	if movement_type not in ("Exit", "Entry"):
		frappe.throw(_("movement_type must be 'Exit' or 'Entry'."))
	if gate_verification_status not in ("Verified", "Rejected"):
		frappe.throw(_("gate_verification_status must be 'Verified' or 'Rejected'."))

	match = _resolve_vehicle(reference)
	if not match:
		frappe.response["message"] = {"reference": reference, "error": "No vehicle asset or task found for that reference."}
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
	gate_name = resolve_gate(gate, farm)
	note = remarks.strip() if remarks else ""
	stamped_note = (
		("[" + movement_type + " @ " + farm + ", " + frappe.utils.format_datetime(now) + "] " + note)
		if note else ""
	)

	def new_leg():
		doc = frappe.new_doc("Gate Vehicle Verification")
		doc.reference_doctype = match["reference_doctype"]
		doc.reference_name = match["reference_name"]
		doc.asset = match.get("asset")
		doc.vehicle_no = match.get("vehicle_no")
		doc.task_description = match.get("task_description")
		doc.source_status = match.get("source_status")
		return doc

	if movement_type == "Exit":
		doc = new_leg()
		doc.from_farm = farm
		doc.exit_gate = gate_name
		doc.gate_exit_time = now
		doc.gate_exit_verified_by = frappe.session.user
		doc.gate_exit_status = gate_verification_status
		doc.remarks = stamped_note
		doc.insert(ignore_permissions=True)
		leg_result = {"name": doc.name, "leg_complete": False}
	else:
		open_leg = _open_leg(match)
		if open_leg:
			doc = frappe.get_doc("Gate Vehicle Verification", open_leg)
			doc.to_farm = farm
			doc.entry_gate = gate_name
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
			doc = new_leg()
			doc.to_farm = farm
			doc.entry_gate = gate_name
			doc.gate_entry_time = now
			doc.gate_entry_verified_by = frappe.session.user
			doc.gate_entry_status = gate_verification_status
			doc.remarks = ("No matching Exit found on file for this arrival. " + stamped_note).strip()
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
		"asset": match.get("asset"),
		"has_task": match.get("has_task"),
		"farm": farm,
		"gate": gate_name,
		"movement_type": movement_type,
		"gate_verification_status": gate_verification_status,
		"is_authorized": match.get("is_authorized"),
		"leg_complete": leg_result["leg_complete"],
		"unmatched_entry": leg_result.get("unmatched_entry", False),
	}
