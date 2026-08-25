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


def _lookup_expected_items(source, name):
	"""Per-item expected quantities from the source doc's own item child
	table, per this source's Dispatch Source config — empty list when no
	per-item breakdown is configured (items_child_table blank), which is
	the honest answer for a source doctype that only carries a single
	aggregate count (or nothing at all), not an error condition. Requires
	a full frappe.get_doc load (unlike the rest of this file's frappe.db.
	get_value lookups) since child tables aren't reachable any other way."""
	if not (source.items_child_table and source.item_code_field and source.item_qty_field):
		return []

	doc = frappe.get_doc(source.source_doctype, name)
	child_rows = doc.get(source.items_child_table) or []

	# row_id (the child row's own name, not item_code) is what the guard's
	# actual_qty gets matched back against in verify_dispatch_at_gate. A
	# real source document can have the same item_code appear on more than
	# one row - e.g. Dispatch Form groups dispatch_form_item rows by
	# (customer, delivery point), so the same rose variety legitimately
	# shows up twice for two different destinations. Keying on item_code
	# alone would collapse those into one shared actual_qty and misreport
	# a correctly-counted split shipment as short on one row and untouched
	# on the other. Each child row already has a unique own name - use it.
	items = []
	for row in child_rows:
		code = row.get(source.item_code_field)
		if not code:
			continue
		name_value = row.get(source.item_name_field) if source.item_name_field else None
		items.append({
			"row_id": row.get("name"),
			"item_code": code,
			"item_name": name_value or code,
			"qty": row.get(source.item_qty_field) or 0,
			"uom": row.get(source.item_uom_field) if source.item_uom_field else None,
		})
	return items


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
		"expected_items": _lookup_expected_items(source, name),
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
def verify_dispatch_at_gate(
	reference, gate_verification_status, remarks=None, item_checks=None, gate_arrival_time=None
):
	"""Creates the actual audit record — a NEW Gate Dispatch Verification
	document, never an edit to the source. Re-resolves the source fresh
	(rather than trusting whatever the client cached from the search call)
	so the snapshot reflects the document at the moment of the actual gate
	decision, not whenever the guard first looked it up. Same freshness
	logic applies to expected_items below - the guard's actual_qty counts
	(item_checks) are matched against a just-now re-fetched expected list,
	never whatever the search call handed the client earlier.

	item_checks: optional JSON string (or list, if called internally) of
	{"item_code": ..., "actual_qty": ...} - one entry per item the guard
	actually counted. Items the guard didn't get to are left "Not Checked"
	rather than assumed to match or fail.

	gate_arrival_time: optional, client-supplied timestamp of when the
	truck/driver first presented at the gate (captured on the client the
	moment search_dispatch_for_gate returned a match) - distinct from
	gate_exit_time below, which is stamped server-side at the moment this
	call is made (i.e. when the guard actually clears the truck to leave).
	Never backfilled/defaulted if omitted - a blank arrival time is the
	honest answer when the client didn't send one, not something to fake."""
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

	# Keyed by row_id (the source's own child-row name), not item_code -
	# the same item_code can legitimately appear on more than one expected
	# row (see _lookup_expected_items's comment on why), and a code-keyed
	# dict would silently collapse two real, independently-counted rows
	# into one shared actual_qty.
	actual_by_row = {}
	if item_checks:
		parsed = frappe.parse_json(item_checks) if isinstance(item_checks, str) else item_checks
		for row in parsed or []:
			row_id = row.get("row_id")
			if row_id:
				actual_by_row[row_id] = row.get("actual_qty")

	doc = frappe.new_doc("Gate Dispatch Verification")
	doc.reference_doctype = match["reference_doctype"]
	doc.reference_name = match["reference_name"]
	doc.farm = match.get("farm")
	doc.vehicle_no = match.get("vehicle_no")
	doc.driver_name = match.get("driver_name")
	doc.dispatch_datetime = match.get("dispatch_datetime")
	doc.items_summary = match.get("items_summary")
	doc.source_status = match.get("source_status")

	for expected in match.get("expected_items") or []:
		# Rounded to 2dp before comparing - the source's own qty field can
		# carry binary-float noise (e.g. 12.000000000000002) picked up from
		# upstream arithmetic that has nothing to do with what the guard
		# actually counted; comparing exact floats would misreport a real
		# match as "Short"/"Over" over a difference no human typed in.
		expected_qty = frappe.utils.flt(expected.get("qty"), 2)
		actual_raw = actual_by_row.get(expected.get("row_id"))
		if actual_raw is None:
			match_status = "Not Checked"
			actual_qty = None
		else:
			actual_qty = frappe.utils.flt(actual_raw, 2)
			if actual_qty == expected_qty:
				match_status = "Matches"
			elif actual_qty < expected_qty:
				match_status = "Short"
			else:
				match_status = "Over"
		doc.append("item_checks", {
			"item_code": expected["item_code"],
			"item_name": expected.get("item_name"),
			"uom": expected.get("uom"),
			"expected_qty": expected_qty,
			# Float fields cast None -> 0.0 at the DB layer regardless of
			# what's assigned here (Frappe's get_valid_dict), so a
			# "Not Checked" row persists actual_qty=0.0 in the database
			# even though it's correctly None in this response - the two
			# are distinguishable via match_status, never via actual_qty
			# alone, for any future report/consumer of this table.
			"actual_qty": actual_qty,
			"match_status": match_status,
		})

	doc.gate_verification_status = gate_verification_status
	doc.gate_verified_by = frappe.session.user
	doc.gate_arrival_time = frappe.utils.get_datetime(gate_arrival_time) if gate_arrival_time else None
	doc.gate_exit_time = frappe.utils.now_datetime()
	doc.remarks = remarks
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	frappe.response["message"] = {
		"name": doc.name,
		"reference_name": doc.reference_name,
		"gate_verification_status": doc.gate_verification_status,
		"is_authorized": match.get("is_authorized"),
		"item_checks": [
			{
				"item_code": r.item_code,
				"item_name": r.item_name,
				"expected_qty": r.expected_qty,
				"actual_qty": r.actual_qty,
				"match_status": r.match_status,
			}
			for r in doc.item_checks
		],
	}


@frappe.whitelist()
def get_gate_dispatch_verification_summary(reference_doctype, reference_name):
	"""Read-only lookup for a source document's own UI (e.g. Delivery
	Note's "Security Check" tab) to show whatever gate verification has
	already happened for it, without Delivery Note ever storing a copy of
	that data itself — Gate Dispatch Verification stays the sole owner,
	same "read-only against the source" principle as the rest of this
	file, just mirrored: here the source is reading from us instead of us
	reading from the source.

	Returns None if no verification exists yet for this document. If more
	than one verification attempt exists (a guard re-checked after a
	Rejected first pass, say), returns only the most recent one.

	Deliberately built entirely on frappe.db.get_value / frappe.get_all,
	neither of which enforce doctype permissions the way frappe.get_doc /
	frappe.get_list do - no explicit ignore_permissions needed. That's the
	right call here, not an oversight: Gate Guard's own read access on
	Gate Dispatch Verification is if_owner=1 (a guard can only read
	verifications *they personally* created), so a different guard - or a
	Sales/Stock user with no Security role at all - legitimately can't
	read someone else's verification row directly through the doctype
	itself. But anyone who can already open this Delivery Note in Desk
	should be able to see whether/how it was checked at the gate; that's
	guard-entered operational metadata about a document they can already
	see in full, not a new exposure of anything sensitive (no PII beyond
	a guard's own name, which is also visible via the record's owner/
	modified_by on any other doctype)."""
	reference_doctype = (reference_doctype or "").strip()
	reference_name = (reference_name or "").strip()
	if not reference_doctype or not reference_name:
		frappe.response["message"] = None
		return

	# The precondition the rest of this function relies on ("anyone who can
	# already open this Delivery Note in Desk should be able to see whether
	# it was checked") is NOT enforced by frappe.db.get_value/get_all below
	# - both bypass doctype permissions entirely, so without this explicit
	# check any logged-in user could pass an arbitrary reference_doctype/
	# reference_name and read another guard's verification (including
	# flagged shortages) despite having no read access to either doctype.
	# Fails soft (None, same as "no verification found") rather than
	# frappe.throw, so a permission gap here just hides the tab instead of
	# surfacing a scary error on someone's Delivery Note page.
	if not frappe.has_permission(reference_doctype, "read", doc=reference_name):
		frappe.response["message"] = None
		return

	name = frappe.db.get_value(
		"Gate Dispatch Verification",
		{"reference_doctype": reference_doctype, "reference_name": reference_name},
		"name",
		order_by="creation desc",
	)
	if not name:
		frappe.response["message"] = None
		return

	# frappe.db.get_value never checks permissions to begin with (it's a
	# raw SQL read, unlike frappe.get_doc) - no ignore_permissions kwarg
	# exists on it, and passing one would raise a TypeError. Safe here only
	# because the has_permission gate above already confirmed the caller
	# can read the source document this verification is about.
	verification = frappe.db.get_value(
		"Gate Dispatch Verification",
		name,
		["gate_verification_status", "gate_verified_by", "gate_arrival_time", "gate_exit_time", "remarks"],
		as_dict=True,
	)

	verified_by_name = None
	if verification.gate_verified_by:
		verified_by_name = frappe.db.get_value("User", verification.gate_verified_by, "full_name")

	# frappe.get_all already ignores permissions internally (unlike
	# frappe.get_list) - no need to pass ignore_permissions here either.
	item_checks = frappe.get_all(
		"Dispatch Item Check",
		filters={"parenttype": "Gate Dispatch Verification", "parent": name},
		fields=["item_code", "item_name", "uom", "expected_qty", "actual_qty", "match_status"],
		order_by="idx asc",
	)

	frappe.response["message"] = {
		"name": name,
		"gate_verification_status": verification.gate_verification_status,
		"gate_verified_by": verification.gate_verified_by,
		"gate_verified_by_name": verified_by_name or verification.gate_verified_by,
		"gate_arrival_time": verification.gate_arrival_time,
		"gate_exit_time": verification.gate_exit_time,
		"remarks": verification.remarks,
		"item_checks": item_checks,
	}
