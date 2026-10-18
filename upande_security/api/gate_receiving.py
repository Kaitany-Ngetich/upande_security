# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Gate-side identity/paperwork check for inbound supplier deliveries against
Purchase Order, mirroring how Gate Dispatch Verification (api/gate_dispatch.py)
checks outbound trucks against Dispatch Form.

This is deliberately narrow in scope: confirm a PO exists for an active
supplier, and log vehicle + driver. The guard never inspects or judges
cargo contents — that's the stock team's job at receiving (Purchase
Receipt), a separate step this never touches.

Unlike dispatch, kept single-doctype and hardcoded to Purchase Order rather
than config-driven across a Security Ops Settings child table — there's
exactly one clear source of inbound delivery authorization in this system,
not several competing ones to plan a config layer around.

Read-only against Purchase Order. Security's own record of having checked a
delivery lives entirely in Gate Receiving Verification, a doctype this app
owns outright.
"""

import urllib.parse

import frappe
from frappe import _

from upande_security.api.feature_flags import is_feature_enabled, require_feature
from upande_security.api.gate_belongings import clean_items, item_rows, mark_exit, replace_items
from upande_security.api.security_alerts import log_unauthorized_access
from upande_security.utils.notifications import resolve_notification_users

# PO statuses where goods are still genuinely expected to arrive — anything
# else (Draft, To Bill, Completed, Cancelled, Closed, Delivered) means either
# nothing was formally/fully ordered yet, or there's nothing left to check
# at the gate for this PO.
AUTHORIZED_PO_STATUSES = ("To Receive", "To Receive and Bill")


def _build_items_summary(po_name):
	items = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": po_name},
		fields=["item_code", "item_name", "qty", "uom", "received_qty"],
		order_by="idx asc",
	)
	parts = []
	for it in items:
		pending = (it.qty or 0) - (it.received_qty or 0)
		label = it.item_name or it.item_code
		parts.append(label + " (" + str(pending) + " " + (it.uom or "") + " pending)")
	return ", ".join(parts)


def _resolve_purchase_order(reference):
	"""reference may be the PO number itself (what the driver's paperwork
	usually carries), or a supplier name/fragment when it doesn't — falls
	back to that supplier's most recent still-open PO."""
	if frappe.db.exists("Purchase Order", reference):
		return reference

	supplier = frappe.db.get_value(
		"Supplier",
		{"disabled": 0, "supplier_name": ["like", "%" + reference + "%"]},
		"name",
	)
	if not supplier:
		return None

	po = frappe.get_all(
		"Purchase Order",
		filters={
			"supplier": supplier,
			"status": ["in", list(AUTHORIZED_PO_STATUSES)],
			"docstatus": 1,
		},
		fields=["name"],
		order_by="transaction_date desc",
		limit=1,
	)
	return po[0].name if po else None


def _lookup(reference):
	po_name = _resolve_purchase_order(reference)
	if not po_name:
		return None

	po = frappe.db.get_value(
		"Purchase Order",
		po_name,
		["name", "supplier", "supplier_name", "status", "docstatus", "transaction_date", "schedule_date"],
		as_dict=True,
	)
	if not po:
		return None

	supplier_active = not frappe.db.get_value("Supplier", po.supplier, "disabled")
	authorized = po.docstatus == 1 and po.status in AUTHORIZED_PO_STATUSES and supplier_active

	return {
		"purchase_order": po.name,
		"supplier": po.supplier,
		"supplier_name": po.supplier_name,
		"po_status": po.status,
		"supplier_active": supplier_active,
		"transaction_date": str(po.transaction_date) if po.transaction_date else None,
		"schedule_date": str(po.schedule_date) if po.schedule_date else None,
		"items_summary": _build_items_summary(po.name),
		"is_authorized": authorized,
	}


@frappe.whitelist()
def search_receiving_for_gate(reference):
	"""Guard types/scans the PO number off the delivery paperwork, or the
	supplier's name if that's all they have. Read-only — never touches the
	Purchase Order."""
	require_feature("feature_gate_receiving")
	reference = (reference or "").strip()
	if not reference:
		frappe.response["message"] = {"found": False, "error": "A PO number or supplier name is required."}
		return

	try:
		match = _lookup(reference)
	except Exception as e:
		frappe.log_error("search_receiving_for_gate", str(e))
		match = None

	if match:
		match["found"] = True
		frappe.response["message"] = match
	else:
		frappe.response["message"] = {
			"found": False,
			"error": "No active Purchase Order found for that reference.",
		}


@frappe.whitelist()
def search_receiving_by_supplier_badge(reference):
	"""Guard scans a Supplier Badge's QR instead of typing a PO number.
	Unlike search_receiving_for_gate (which resolves to that supplier's
	single most-recent open PO for a quick manual reference lookup), this
	returns EVERY currently open PO for the badge's supplier - a badge
	holder can easily have more than one delivery in flight at once, and
	the guard needs to pick the right one for the truck actually at the
	gate, not have one silently guessed for them."""
	require_feature("feature_gate_receiving")
	require_feature("feature_supplier_badges")
	reference = (reference or "").strip()
	if not reference:
		frappe.response["message"] = {"found": False, "error": "A badge reference is required."}
		return

	# A badge's printed QR now encodes a public info-page URL (see
	# supplier_badge_qr.py) rather than the bare doctype name, so a scan
	# from either the gate app's own scanner or someone's plain camera
	# resolves the same badge. Pull the "badge" query param back out if
	# that's what we got; fall through to treating it as a bare name
	# otherwise, for any badge printed before this change.
	if "supplier-badge?" in reference:
		parsed = urllib.parse.urlparse(reference)
		qs = urllib.parse.parse_qs(parsed.query)
		reference = (qs.get("badge") or [reference])[0]

	badge = frappe.db.get_value(
		"Supplier Badge", reference, ["name", "status", "supplier"], as_dict=True
	)
	if not badge:
		log_unauthorized_access(
			"Invalid Badge Scan",
			reference,
			"Supplier Badge scan at gate receiving found no Supplier Badge record for '" + reference + "'.",
		)
		frappe.response["message"] = {"found": False, "error": "No Supplier Badge found for that reference."}
		return
	if badge.status != "Issued" or not badge.supplier:
		log_unauthorized_access(
			"Invalid Badge Scan",
			badge.name,
			"Supplier Badge " + badge.name + " scanned at gate receiving is not Issued/assigned to a supplier (status: "
			+ (badge.status or "Available") + ").",
		)
		frappe.response["message"] = {
			"found": False,
			"error": "This badge is not currently assigned to a supplier (status: " + (badge.status or "Available") + ").",
		}
		return

	po_names = frappe.get_all(
		"Purchase Order",
		filters={
			"supplier": badge.supplier,
			"status": ["in", list(AUTHORIZED_PO_STATUSES)],
			"docstatus": 1,
		},
		fields=["name"],
		order_by="transaction_date desc",
	)

	matches = []
	for row in po_names:
		try:
			m = _lookup(row.name)
		except Exception as e:
			frappe.log_error("search_receiving_by_supplier_badge", str(e))
			m = None
		if m:
			matches.append(m)

	supplier_name = frappe.db.get_value("Supplier", badge.supplier, "supplier_name") or badge.supplier
	frappe.response["message"] = {
		"found": bool(matches),
		"badge": badge.name,
		"supplier": badge.supplier,
		"supplier_name": supplier_name,
		"matches": matches,
		"error": None if matches else "No open Purchase Orders for " + supplier_name + " right now.",
	}


def _resolve_receiving_recipients(warehouse):
	"""Who to tell that a PO's delivery just cleared the gate. The target
	Warehouse's own contact email (a native ERPNext field, Warehouse ->
	Contact Info -> Email Address) is the accurate, specific signal when
	it's set - and it only gets more accurate over time as stores fill
	theirs in, with zero code change needed here. Falls back to whoever
	Security Ops Settings' Notification Rules configure for "receiving"
	(Stock User role, if left unconfigured) when the PO has no target
	warehouse set, or that warehouse has no contact email configured yet -
	real PO data checked on this site shows both cases happen regularly
	(~30% of open POs have no set_warehouse at all), so this can't be the
	only path."""
	if warehouse:
		email = frappe.db.get_value("Warehouse", warehouse, "email_id")
		if email:
			return [email]

	return resolve_notification_users("receiving")


def _notify_receiving_team(doc, match):
	"""Best-effort - a notification failure must never undo or block the
	gate verification that already happened; the audit record is what
	matters most, this is a courtesy heads-up on top of it."""
	try:
		warehouse = frappe.db.get_value("Purchase Order", doc.purchase_order, "set_warehouse")
		recipients = _resolve_receiving_recipients(warehouse)
		if not recipients:
			return

		# Every value below is guard-entered or supplier-controlled free
		# text (vehicle_no/driver_name are plain, unvalidated Data fields)
		# landing directly in an HTML email - escape_html on all of them,
		# same convention the wider Frappe/ERPNext codebase already uses
		# for exactly this (e.g. erpnext/stock/reorder_item.py) - unescaped
		# string concatenation here would let anyone who can call this
		# whitelisted method inject arbitrary HTML into every recipient's
		# inbox (a phishing link, a tracking pixel, or just broken markup).
		esc = frappe.utils.escape_html
		supplier_name = esc(match.get("supplier_name") or doc.supplier)
		po_name = esc(doc.purchase_order)
		warehouse_esc = esc(warehouse) if warehouse else None

		subject = "Incoming delivery: " + po_name + " from " + supplier_name
		body = (
			"<p><strong>" + supplier_name + "</strong> has cleared the gate "
			+ "for <strong>" + po_name + "</strong>"
			+ (" and is headed to <strong>" + warehouse_esc + "</strong>." if warehouse_esc else ".")
			+ "</p>"
		)
		if doc.vehicle_no or doc.driver_name:
			body = body + "<p>"
			if doc.vehicle_no:
				body = body + "Vehicle: " + esc(doc.vehicle_no) + "<br>"
			if doc.driver_name:
				body = body + "Driver: " + esc(doc.driver_name)
			body = body + "</p>"
		if doc.items_summary:
			body = body + "<p>Items: " + esc(doc.items_summary) + "</p>"
		body = body + "<p>Gate record: " + esc(doc.name) + "</p>"

		# Queued (not now=True) deliberately - the guard's verify request
		# shouldn't wait on a live SMTP round-trip, and queuing degrades
		# gracefully (retried by Frappe's own scheduler) instead of a
		# synchronous send failure right here if the outgoing mail server
		# is briefly unreachable.
		frappe.sendmail(recipients=recipients, subject=subject, message=body)
	except Exception as e:
		frappe.log_error("gate_receiving _notify_receiving_team failed for " + doc.name, str(e))


def _farm_for_this_guard():
	from upande_security.api.gate_vehicle import _resolve_checking_farm

	return _resolve_checking_farm(frappe.session.user)


def _supplier_party(doc, match):
	"""Who a delivery's carried items belong to: the driver, for the supplier."""
	return {
		"party_type": "Supplier",
		"carried_by": doc.driver_name or match.get("supplier_name") or doc.supplier,
		"supplier": doc.supplier,
		"farm": doc.farm,
		"company": (frappe.db.get_value("Farm", doc.farm, "company") if doc.farm else None)
		or frappe.db.get_value("Purchase Order", doc.purchase_order, "company"),
	}


def _gate_for_this_guard(gate):
	"""The gate picked in the app, else the calling guard's farm's main gate,
	else "Main Gate"."""
	from upande_security.api.gate_movement import resolve_gate
	from upande_security.api.gate_vehicle import _resolve_checking_farm

	return resolve_gate(gate, _resolve_checking_farm(frappe.session.user))


def _verify_receiving_one(
	reference,
	gate_verification_status,
	vehicle_no=None,
	driver_name=None,
	remarks=None,
	gate=None,
	items=None,
	delivery_group=None,
):
	"""Core single-PO verification: creates the actual audit record — a NEW
	Gate Receiving Verification document, never an edit to the Purchase
	Order. Re-resolves the PO fresh (rather than trusting whatever the
	client cached from the search call) so the snapshot reflects the
	document at the moment of the actual gate decision, not whenever the
	guard first looked it up.

	Returns a result dict rather than writing frappe.response directly, so
	both the single-PO and bulk (multi-PO, one badge scan) verify endpoints
	share this exact logic instead of drifting apart over time."""
	match = _lookup(reference)
	if not match:
		return {"reference": reference, "error": "No active Purchase Order found for that reference."}

	doc = frappe.new_doc("Gate Receiving Verification")
	doc.purchase_order = match["purchase_order"]
	doc.supplier = match["supplier"]
	doc.po_status = match["po_status"]
	doc.supplier_active = 1 if match["supplier_active"] else 0
	doc.items_summary = match["items_summary"]
	doc.vehicle_no = vehicle_no
	doc.driver_name = driver_name
	doc.gate_verification_status = gate_verification_status
	doc.gate_verified_by = frappe.session.user
	doc.gate = _gate_for_this_guard(gate)
	doc.farm = _farm_for_this_guard()
	doc.gate_arrival_time = frappe.utils.now_datetime()
	doc.remarks = remarks
	doc.delivery_group = delivery_group
	doc.insert(ignore_permissions=True)
	if not doc.delivery_group:
		doc.db_set("delivery_group", doc.name, update_modified=False)
	rows = clean_items(items) if items and is_feature_enabled("feature_carried_items") else []
	if rows:
		replace_items("Gate Receiving Verification", doc.name, rows, _supplier_party(doc, match))
	frappe.db.commit()

	# Only a genuinely cleared truck is worth telling the store about - a
	# Rejected one never reaches them, there's nothing incoming to expect.
	if gate_verification_status == "Verified":
		_notify_receiving_team(doc, match)
	elif gate_verification_status == "Rejected":
		# Best-effort, never raises - see log_unauthorized_access's own
		# docstring. Farm is resolved best-effort via the PO's own target
		# Warehouse -> Warehouse.custom_farm (an upande_kaitet custom
		# field, not native ERPNext) - Purchase Order itself carries no
		# direct Farm link, so this is a real gap when set_warehouse is
		# blank or its Warehouse has no farm set (real PO data on this site
		# shows both cases happen - see _resolve_receiving_recipients'
		# own docstring on the ~30% figure).
		company = frappe.db.get_value("Purchase Order", doc.purchase_order, "company")
		farm = None
		warehouse = frappe.db.get_value("Purchase Order", doc.purchase_order, "set_warehouse")
		if warehouse:
			farm = frappe.db.get_value("Warehouse", warehouse, "custom_farm")
		detail = (
			"Gate Receiving Verification " + doc.name + " for Purchase Order " + doc.purchase_order
			+ " (supplier " + (match.get("supplier_name") or doc.supplier or "") + ") was rejected at the gate."
		)
		if doc.po_status:
			detail = detail + " PO status at verification: " + doc.po_status + "."
		if remarks:
			detail = detail + " Remarks: " + remarks
		log_unauthorized_access("Gate Receiving Rejected", doc.purchase_order, detail, company, farm)

	return {
		"name": doc.name,
		"purchase_order": doc.purchase_order,
		"gate_verification_status": doc.gate_verification_status,
		"is_authorized": match.get("is_authorized"),
		"supplier": doc.supplier,
		"supplier_name": match.get("supplier_name"),
		# Whether this supplier already has a badge in circulation - drives
		# the mobile "Issue a badge for next time" prompt after a Verified
		# decision. Always true for a bulk (badge-scan-originated) verify,
		# since reaching that path already required an Issued badge.
		"has_badge": bool(
			frappe.db.exists("Supplier Badge", {"supplier": doc.supplier, "status": "Issued"})
		),
	}


@frappe.whitelist()
def verify_receiving_at_gate(
	reference, gate_verification_status, vehicle_no=None, driver_name=None, remarks=None, gate=None, items=None
):
	require_feature("feature_gate_receiving")
	reference = (reference or "").strip()
	gate_verification_status = (gate_verification_status or "").strip()
	if gate_verification_status not in ("Verified", "Rejected"):
		frappe.throw(_("gate_verification_status must be 'Verified' or 'Rejected'."))

	frappe.response["message"] = _verify_receiving_one(
		reference, gate_verification_status, vehicle_no, driver_name, remarks, gate, items=items
	)


@frappe.whitelist()
def verify_receiving_at_gate_bulk(
	references, gate_verification_status, vehicle_no=None, driver_name=None, remarks=None, gate=None, items=None
):
	"""Same as verify_receiving_at_gate, but for every PO the guard selected
	off one Supplier Badge scan in one action — one driver can be carrying
	goods for several open POs, so instead of scanning/verifying each PO
	one at a time, the guard picks all of them and this releases the lot
	together against the one truck/driver at the gate.

	Each PO still gets its OWN Gate Receiving Verification record — the
	full per-PO audit trail is unchanged, this only collapses the guard's
	taps, not the underlying data model."""
	require_feature("feature_gate_receiving")
	gate_verification_status = (gate_verification_status or "").strip()
	if gate_verification_status not in ("Verified", "Rejected"):
		frappe.throw(_("gate_verification_status must be 'Verified' or 'Rejected'."))

	if isinstance(references, str):
		try:
			references = frappe.parse_json(references)
		except Exception:
			references = [references]

	if not references:
		frappe.response["message"] = {"results": [], "error": "At least one reference is required."}
		return

	# One truck: its items go on the first record, and every record shares
	# that record's name as delivery_group so they leave together.
	results = []
	group = None
	for ref in references:
		ref = (ref or "").strip()
		if not ref:
			continue
		try:
			result = _verify_receiving_one(
				ref,
				gate_verification_status,
				vehicle_no,
				driver_name,
				remarks,
				gate,
				items=None if group else items,
				delivery_group=group,
			)
			if not group and result.get("name"):
				group = result["name"]
			results.append(result)
		except Exception as e:
			frappe.log_error("verify_receiving_at_gate_bulk for " + str(ref), str(e))
			results.append({"reference": ref, "error": str(e)})

	frappe.response["message"] = {"results": results}


def _delivery_records(name):
	"""Every Gate Receiving Verification released together with this one off
	the same truck (same delivery_group), this one included."""
	group = frappe.db.get_value("Gate Receiving Verification", name, "delivery_group")
	if not group:
		return [name] if frappe.db.exists("Gate Receiving Verification", name) else []
	return frappe.get_all(
		"Gate Receiving Verification", filters={"delivery_group": group}, pluck="name", order_by="creation asc"
	)


def _delivery_items(names):
	return item_rows("Gate Receiving Verification", names)


@frappe.whitelist()
def list_receivings_awaiting_departure():
	"""Supplier trucks checked in (Verified) at this guard's farm in the last
	7 days and not yet departed - one entry per truck. Read from the server,
	so whichever guard is at the gate when the truck leaves sees it."""
	require_feature("feature_gate_receiving")
	farm = _farm_for_this_guard()
	filters = {
		"gate_verification_status": "Verified",
		"gate_departure_time": ["is", "not set"],
		"creation": [">=", frappe.utils.add_days(frappe.utils.now_datetime(), -7)],
	}
	if farm:
		filters["farm"] = farm
	rows = frappe.get_all(
		"Gate Receiving Verification",
		filters=filters,
		fields=["name", "purchase_order", "supplier", "vehicle_no", "driver_name", "gate_arrival_time", "delivery_group"],
		order_by="gate_arrival_time desc",
	)
	trucks = {}
	for r in rows:
		key = r.delivery_group or r.name
		t = trucks.setdefault(
			key,
			{
				"name": key,
				"purchase_orders": [],
				"supplier": r.supplier,
				"supplier_name": frappe.db.get_value("Supplier", r.supplier, "supplier_name") or r.supplier,
				"vehicle_no": r.vehicle_no,
				"driver_name": r.driver_name,
				"arrived_at": str(r.gate_arrival_time or ""),
			},
		)
		t["purchase_orders"].append(r.purchase_order)
	for key, t in trucks.items():
		t["items_inside"] = len(
			[i for i in _delivery_items(_delivery_records(key)) if i.exit_status == "Inside"]
		)
	return list(trucks.values())


@frappe.whitelist()
def get_receiving_departure(name):
	"""What the exit check needs for one truck: its delivery records and the
	items declared at entry that are still inside."""
	require_feature("feature_gate_receiving")
	names = _delivery_records(name)
	if not names:
		frappe.throw(_("Gate Receiving Verification {0} not found.").format(name))
	first = frappe.db.get_value(
		"Gate Receiving Verification", names[0], ["supplier", "vehicle_no", "driver_name", "gate_departure_time"], as_dict=True
	)
	items = _delivery_items(names) if is_feature_enabled("feature_carried_items") else []
	return {
		"name": names[0],
		"records": names,
		"supplier_name": frappe.db.get_value("Supplier", first.supplier, "supplier_name") or first.supplier,
		"vehicle_no": first.vehicle_no,
		"driver_name": first.driver_name,
		"departed": bool(first.gate_departure_time),
		"items": [i for i in items if i.exit_status == "Inside"],
	}


@frappe.whitelist()
def confirm_receiving_departure(name, items_out=None, extra_items=None):
	"""Confirms the truck has left after dropping off goods — offloading
	takes time, so this is a separate call from verify_receiving_at_gate,
	not a field set at arrival. name here is the Gate Receiving
	Verification record's own name, not the Purchase Order's. Every record
	released with it off the same truck departs too.

	Exit check (feature_carried_items) - sent by app builds that have it;
	an older build sends neither and items stay as they were:
	- items_out: the declared items the guard saw leave. Every other
	  declared item still Inside becomes "Not seen leaving".
	- extra_items: anything leaving that was NOT declared at entry -
	  [{item, qty?, serial_notes?, supporting_document?, supporting_document_file?}].
	  Each needs a supporting document (a reference, a file, or both);
	  without one the departure is refused, so nothing leaves unaccounted."""
	require_feature("feature_gate_receiving")
	names = _delivery_records(name)
	if not names:
		frappe.response["message"] = {"error": "Gate Receiving Verification " + str(name) + " not found."}
		return

	if isinstance(items_out, str):
		items_out = frappe.parse_json(items_out) if items_out.strip() else None
	if isinstance(extra_items, str):
		extra_items = frappe.parse_json(extra_items) if extra_items.strip() else None

	now = frappe.utils.now_datetime()
	not_seen = []
	recorded_extra = []
	if is_feature_enabled("feature_carried_items") and (items_out is not None or extra_items):
		extras = []
		for it in extra_items or []:
			item = str(it.get("item") or "").strip()
			if not item:
				continue
			doc_ref = str(it.get("supporting_document") or "").strip()
			doc_file = str(it.get("supporting_document_file") or "").strip()
			if not doc_ref and not doc_file:
				frappe.throw(
					_("{0} was not declared on the way in. Record its supporting document (reference or photo) before the truck leaves.").format(
						frappe.bold(item)
					)
				)
			try:
				qty = max(int(it.get("qty") or 1), 1)
			except (TypeError, ValueError):
				qty = 1
			extras.append((item, qty, str(it.get("serial_notes") or "").strip(), doc_ref, doc_file))

		if items_out is not None:
			not_seen = [r.item for r in mark_exit(_delivery_items(names), items_out)]

		if extras:
			grv = frappe.get_doc("Gate Receiving Verification", names[0])
			party = _supplier_party(grv, {"supplier_name": frappe.db.get_value("Supplier", grv.supplier, "supplier_name")})
			for item, qty, notes, doc_ref, doc_file in extras:
				extra = frappe.new_doc("Gate Carried Item")
				extra.update({k: v for k, v in party.items() if v})
				extra.update(
					{
						"reference_doctype": "Gate Receiving Verification",
						"reference_name": grv.name,
						"item": item,
						"qty": qty,
						"serial_notes": notes,
						"declared_at": "Exit",
						"entry_time": now,
						"recorded_by": frappe.session.user,
						"exit_status": "Left with document",
						"exit_time": now,
						"exit_checked_by": frappe.session.user,
						"supporting_document": doc_ref,
						"supporting_document_file": doc_file,
					}
				)
				extra.insert(ignore_permissions=True)
				recorded_extra.append(item)

	for record in names:
		grv = frappe.db.get_value("Gate Receiving Verification", record, ["name", "supplier_badge"], as_dict=True)
		frappe.db.set_value("Gate Receiving Verification", record, "gate_departure_time", now)
		# Release any badge issued for this delivery back into the pool, same
		# mechanic as Contractor Gate Checkout releasing a Supplier Badge on
		# the contractor side - reusable across many different suppliers, not
		# permanently tied to this one.
		if grv.supplier_badge:
			frappe.db.set_value(
				"Supplier Badge",
				grv.supplier_badge,
				{"status": "Available", "current_receiving": None, "supplier": None},
			)

	frappe.db.commit()
	frappe.response["message"] = {
		"name": name,
		"records": names,
		"gate_departure_time": str(now),
		"not_seen_leaving": not_seen,
		"left_with_document": recorded_extra,
	}


@frappe.whitelist()
def issue_supplier_badge_for_receiving(name, badge_number):
	"""Issues/assigns a Supplier Badge to the supplier behind an already-
	verified Gate Receiving Verification record, so a future delivery from
	the same supplier can be found by scanning the badge instead of typing
	the PO/name again (see search_receiving_by_supplier_badge). Mirrors
	Issue Supplier Badge's contractor-side logic exactly, but keyed to a
	Gate Receiving Verification record instead of an Appointment - there is
	no Appointment anywhere in this flow.

	Released back to Available by confirm_receiving_departure above,
	exactly like Contractor Gate Checkout releases the contractor-side
	one."""
	require_feature("feature_gate_receiving")
	require_feature("feature_supplier_badges")
	name = (name or "").strip()
	if not name:
		frappe.response["message"] = {"error": "name is required"}
		return

	try:
		badge_number = int(badge_number)
	except Exception:
		frappe.response["message"] = {"error": "badge_number must be a number"}
		return

	grv = frappe.db.get_value(
		"Gate Receiving Verification",
		name,
		["name", "supplier", "purchase_order", "supplier_badge"],
		as_dict=True,
	)
	if not grv:
		frappe.response["message"] = {"error": "Gate Receiving Verification " + name + " not found"}
		return
	if grv.supplier_badge:
		frappe.response["message"] = {
			"error": "A badge is already issued for this delivery (" + grv.supplier_badge + ")"
		}
		return

	company = frappe.db.get_value("Purchase Order", grv.purchase_order, "company")
	if not company:
		frappe.response["message"] = {
			"error": "Could not determine the company for this Purchase Order"
		}
		return

	badge = frappe.db.get_value(
		"Supplier Badge",
		{"company": company, "badge_number": badge_number},
		["name", "status", "current_receiving"],
		as_dict=True,
	)
	if not badge:
		frappe.response["message"] = {
			"error": "Badge " + str(badge_number) + " does not exist for " + company
		}
		return
	if badge.status == "Issued" and badge.current_receiving != name:
		frappe.response["message"] = {
			"error": "Badge " + str(badge_number) + " (" + company + ") is already issued elsewhere"
		}
		return

	# Same optimistic-concurrency protection as issue_supplier_badge /
	# issue_visitor_badge - load + save, not a raw set_value.
	badge_doc = frappe.get_doc("Supplier Badge", badge.name)
	badge_doc.status = "Issued"
	badge_doc.current_receiving = name
	badge_doc.current_appointment = None
	badge_doc.supplier = grv.supplier
	try:
		badge_doc.save(ignore_permissions=True)
	except frappe.TimestampMismatchError:
		frappe.response["message"] = {
			"error": "Badge "
			+ str(badge_number)
			+ " ("
			+ company
			+ ") was just issued elsewhere - rescan or pick a different badge."
		}
		return

	frappe.db.set_value("Gate Receiving Verification", name, "supplier_badge", badge.name)
	frappe.db.commit()

	supplier_name = frappe.db.get_value("Supplier", grv.supplier, "supplier_name") or grv.supplier
	frappe.response["message"] = {
		"badge_number": badge_number,
		"company": company,
		"supplier": grv.supplier,
		"supplier_name": supplier_name,
	}
