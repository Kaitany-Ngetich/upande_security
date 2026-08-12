# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Gate-side lookup and verification for dispatch documents (trucks leaving
the farm with goods already authorized by someone else's system — an
avocado export container, a general sales dispatch, whatever else shows up
later).

Deliberately config-driven, not hardcoded to one doctype: which doctype(s)
count as "a dispatch to check" — and which field on each is the vehicle,
driver, date, etc. — lives in Security Ops Settings' `dispatch_sources`
child table (Dispatch Source). Adding support for another dispatch doctype
is a config row, not a code change.

Read-only against the source doctype. Nothing here ever writes back to
Dispatch Form (or whatever else gets configured) — Security's own record of
having checked a truck lives entirely in Gate Dispatch Verification, a
doctype this app owns outright. The source's own team keeps full control
of their own document.
"""

import frappe
from frappe import _


def _enabled_dispatch_sources():
	settings = frappe.get_single("Security Ops Settings")
	return [row for row in settings.dispatch_sources if row.enabled]


def _combine_date_time(date_val, time_val):
	"""date_val may already be a full datetime (time_val blank) or a plain
	date that needs time_val added to it, per the source's own config."""
	if not date_val:
		return None
	if not time_val:
		return frappe.utils.get_datetime(date_val)
	try:
		return frappe.utils.get_datetime(date_val) + frappe.utils.get_timedelta(time_val)
	except Exception:
		return frappe.utils.get_datetime(date_val)


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
		"driver": source.driver_field,
		"date": source.date_field,
		"time": source.time_field,
		"farm": source.farm_field,
		"items_summary": source.items_summary_field,
		"status": source.status_field,
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
		authorized = status_value in allowed

	return {
		"reference_doctype": source.source_doctype,
		"reference_name": doc_values.get("name"),
		"vehicle_no": doc_values.get(source.vehicle_field) if source.vehicle_field else None,
		"driver_name": doc_values.get(source.driver_field) if source.driver_field else None,
		"dispatch_datetime": _combine_date_time(
			doc_values.get(source.date_field) if source.date_field else None,
			doc_values.get(source.time_field) if source.time_field else None,
		),
		"farm": doc_values.get(source.farm_field) if source.farm_field else None,
		"items_summary": doc_values.get(source.items_summary_field) if source.items_summary_field else None,
		"source_status": status_value,
		"is_authorized": authorized,
	}


@frappe.whitelist()
def search_dispatch_for_gate(reference):
	"""Guard types/scans whatever reference is on the physical dispatch
	note. Checks every enabled Dispatch Source in turn, returns the first
	match. Read-only — never touches the source document."""
	reference = (reference or "").strip()
	if not reference:
		frappe.response["message"] = {"found": False, "error": "A dispatch reference is required."}
		return

	for source in _enabled_dispatch_sources():
		try:
			match = _lookup_in_source(source, reference)
		except Exception as e:
			frappe.log_error("search_dispatch_for_gate source lookup: " + source.source_doctype, str(e))
			continue
		if match:
			match["found"] = True
			frappe.response["message"] = match
			return

	frappe.response["message"] = {"found": False, "error": "No dispatch document found for that reference."}


@frappe.whitelist()
def verify_dispatch_at_gate(reference, gate_verification_status, remarks=None):
	"""Creates the actual audit record — a NEW Gate Dispatch Verification
	document, never an edit to the source. Re-resolves the source fresh
	(rather than trusting whatever the client cached from the search call)
	so the snapshot reflects the document at the moment of the actual gate
	decision, not whenever the guard first looked it up."""
	reference = (reference or "").strip()
	gate_verification_status = (gate_verification_status or "").strip()
	if gate_verification_status not in ("Verified", "Rejected"):
		frappe.throw(_("gate_verification_status must be 'Verified' or 'Rejected'."))

	match = None
	for source in _enabled_dispatch_sources():
		try:
			match = _lookup_in_source(source, reference)
		except Exception as e:
			frappe.log_error("verify_dispatch_at_gate source lookup: " + source.source_doctype, str(e))
			continue
		if match:
			break

	if not match:
		frappe.response["message"] = {"error": "No dispatch document found for that reference."}
		return

	doc = frappe.new_doc("Gate Dispatch Verification")
	doc.reference_doctype = match["reference_doctype"]
	doc.reference_name = match["reference_name"]
	doc.farm = match.get("farm")
	doc.vehicle_no = match.get("vehicle_no")
	doc.driver_name = match.get("driver_name")
	doc.dispatch_datetime = match.get("dispatch_datetime")
	doc.items_summary = match.get("items_summary")
	doc.source_status = match.get("source_status")
	doc.gate_verification_status = gate_verification_status
	doc.gate_verified_by = frappe.session.user
	doc.gate_exit_time = frappe.utils.now_datetime()
	doc.remarks = remarks
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	frappe.response["message"] = {
		"name": doc.name,
		"reference_name": doc.reference_name,
		"gate_verification_status": doc.gate_verification_status,
		"is_authorized": match.get("is_authorized"),
	}


@frappe.whitelist()
def confirm_dispatch_return(name):
	"""Not every dispatch returns to the farm (an export truck headed to
	port doesn't) — this is only called for the ones that do. name here is
	the Gate Dispatch Verification record's own name, not the source's."""
	if not frappe.db.exists("Gate Dispatch Verification", name):
		frappe.response["message"] = {"error": "Gate Dispatch Verification " + str(name) + " not found."}
		return

	frappe.db.set_value(
		"Gate Dispatch Verification", name, "gate_return_time", frappe.utils.now_datetime()
	)
	frappe.db.commit()
	frappe.response["message"] = {"name": name, "gate_return_time": str(frappe.utils.now_datetime())}
