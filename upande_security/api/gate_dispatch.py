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


def _latest_verification(reference_doctype, reference_name):
	"""Most recent Gate Dispatch Verification for this reference, or None.
	Shared by search (so the guard sees "already verified" before they even
	try to submit) and verify (which uses it to actually block a duplicate
	Verified record)."""
	return frappe.db.get_value(
		"Gate Dispatch Verification",
		{"reference_doctype": reference_doctype, "reference_name": reference_name},
		["name", "gate_verification_status", "gate_verified_by", "gate_exit_time"],
		order_by="creation desc",
		as_dict=True,
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

	latest = _latest_verification(source.source_doctype, doc_values.get("name"))
	already_verified = bool(latest and latest.gate_verification_status == "Verified")
	verified_by_name = None
	if already_verified:
		verified_by_name = frappe.db.get_value("User", latest.gate_verified_by, "full_name") or latest.gate_verified_by

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
		"already_verified": already_verified,
		"already_verified_at": latest.gate_exit_time if already_verified else None,
		"already_verified_by": verified_by_name,
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
	reference,
	gate_verification_status,
	remarks=None,
	item_checks=None,
	gate_arrival_time=None,
	vehicle_no=None,
	driver_name=None,
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
	honest answer when the client didn't send one, not something to fake.

	vehicle_no/driver_name: optional, guard-entered at the moment of
	verification - deliberately AUTHORITATIVE over whatever the source
	document says (not just a fallback for when the source is blank). The
	guard is looking at the actual truck; the source's own vehicle/driver
	fields reflect what was planned when the document was created, which
	can legitimately differ (a truck swap, a driver change) from what
	actually shows up at the gate. Falls back to the source's value only
	when the guard's field is left blank."""
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

	# Block a second Verified record for the same reference - re-checking
	# after a Rejected attempt is a legitimate, intentional flow (the issue
	# gets fixed, the guard re-verifies), so only the MOST RECENT attempt
	# matters here, not "has this ever been verified." Without this check,
	# nothing stops the same truck being verified twice in a row, silently
	# creating two audit records for one gate exit. Re-resolved fresh here
	# (not trusting match["already_verified"] from a stale search result)
	# for the same freshness reasoning as everything else in this function.
	latest = _latest_verification(match["reference_doctype"], match["reference_name"])
	if latest and latest.gate_verification_status == "Verified":
		verified_by_name = frappe.db.get_value("User", latest.gate_verified_by, "full_name") or latest.gate_verified_by
		frappe.response["message"] = {
			"error": (
				"This dispatch was already verified at "
				+ frappe.utils.format_datetime(latest.gate_exit_time)
				+ " by "
				+ (verified_by_name or "another guard")
				+ "."
			)
		}
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
	vehicle_no = (vehicle_no or "").strip()
	driver_name = (driver_name or "").strip()
	doc.vehicle_no = vehicle_no or match.get("vehicle_no")
	doc.driver_name = driver_name or match.get("driver_name")
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
	# The client sends new Date().toISOString(), which is always UTC/"Z"
	# suffixed. frappe.utils.get_datetime() correctly parses that into a
	# timezone-AWARE datetime, but Datetime fields need a naive one - left
	# as-is, the tz-aware value round-trips through str() with a "+00:00"
	# offset that MariaDB's strict mode rejects outright, failing this
	# insert() entirely (not just the arrival-time field). Convert to the
	# site's own timezone and strip tzinfo, same idiom Frappe itself uses
	# internally (frappe.utils.data.convert_utc_to_system_timezone).
	arrival_dt = None
	if gate_arrival_time:
		arrival_dt = frappe.utils.get_datetime(gate_arrival_time)
		if arrival_dt.tzinfo is not None:
			arrival_dt = frappe.utils.convert_utc_to_system_timezone(arrival_dt).replace(tzinfo=None)
	doc.gate_arrival_time = arrival_dt
	doc.gate_exit_time = frappe.utils.now_datetime()
	doc.remarks = remarks
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	shortfall_incident = _auto_file_shortfall_incident(doc)

	frappe.response["message"] = {
		"name": doc.name,
		"reference_name": doc.reference_name,
		"gate_verification_status": doc.gate_verification_status,
		"is_authorized": match.get("is_authorized"),
		"shortfall_incident": shortfall_incident,
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


def _auto_file_shortfall_incident(doc):
	"""A truck cleared the gate short of what its own dispatch paperwork
	says it was carrying - that's the textbook definition of pilferage in
	transit, and it should never depend on the guard remembering to file a
	separate Incident Report by hand. Fires for any farm's gate, in either
	direction (a farm-to-farm transfer's arrival end included, once that
	side is verified through this same Dispatch Checks flow rather than
	Receiving Checks - Receiving stays scoped to the stock team's own
	Purchase Order checks, untouched by this).

	Best-effort: a failure here must never undo or block the verification
	that already happened - the Gate Dispatch Verification record is the
	authoritative audit trail either way, this is a courtesy escalation on
	top of it, same reasoning as _notify_receiving_team.
	"""
	short_rows = [r for r in doc.item_checks if r.match_status == "Short"]
	if not short_rows:
		return None

	try:
		lines = []
		for r in short_rows:
			expected = frappe.utils.flt(r.expected_qty, 2)
			actual = frappe.utils.flt(r.actual_qty, 2)
			short_by = frappe.utils.flt(expected - actual, 2)
			lines.append(
				(r.item_name or r.item_code)
				+ ": expected "
				+ str(expected)
				+ " "
				+ (r.uom or "")
				+ ", received "
				+ str(actual)
				+ " "
				+ (r.uom or "")
				+ " (short "
				+ str(short_by)
				+ ")"
			)

		incident = frappe.new_doc("Incident Report")
		incident.flags.ignore_links = True
		incident.flags.ignore_mandatory = True
		incident.incident_datetime = doc.gate_exit_time or frappe.utils.now_datetime()
		incident.location = doc.farm or ""
		incident.farm = doc.farm
		incident.nature_of_incident = "Theft"
		incident.severity = "High"
		incident.status = "Open"
		incident.reported_by = frappe.session.user
		incident.description = (
			"Auto-opened: dispatch "
			+ doc.reference_name
			+ " (vehicle "
			+ (doc.vehicle_no or "unknown")
			+ ", driver "
			+ (doc.driver_name or "unknown")
			+ ") cleared the gate short of its own paperwork.\n"
			+ "\n".join(lines)
			+ "\n[auto-dispatch-shortfall:" + doc.name + "]"
		)
		incident.insert(ignore_permissions=True)
		frappe.db.commit()
		return incident.name
	except Exception as e:
		frappe.log_error("_auto_file_shortfall_incident for " + doc.name, str(e))
		return None


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
