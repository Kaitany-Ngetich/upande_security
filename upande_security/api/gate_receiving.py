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
		frappe.response["message"] = {"found": False, "error": "No Supplier Badge found for that reference."}
		return
	if badge.status != "Active" or not badge.supplier:
		frappe.response["message"] = {
			"found": False,
			"error": "This badge is not currently assigned to a supplier (status: " + (badge.status or "Unassigned") + ").",
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


@frappe.whitelist()
def verify_receiving_at_gate(reference, gate_verification_status, vehicle_no=None, driver_name=None, remarks=None):
	"""Creates the actual audit record — a NEW Gate Receiving Verification
	document, never an edit to the Purchase Order. Re-resolves the PO fresh
	(rather than trusting whatever the client cached from the search call)
	so the snapshot reflects the document at the moment of the actual gate
	decision, not whenever the guard first looked it up."""
	reference = (reference or "").strip()
	gate_verification_status = (gate_verification_status or "").strip()
	if gate_verification_status not in ("Verified", "Rejected"):
		frappe.throw(_("gate_verification_status must be 'Verified' or 'Rejected'."))

	match = _lookup(reference)
	if not match:
		frappe.response["message"] = {"error": "No active Purchase Order found for that reference."}
		return

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
	doc.gate_arrival_time = frappe.utils.now_datetime()
	doc.remarks = remarks
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	# Only a genuinely cleared truck is worth telling the store about - a
	# Rejected one never reaches them, there's nothing incoming to expect.
	if gate_verification_status == "Verified":
		_notify_receiving_team(doc, match)

	frappe.response["message"] = {
		"name": doc.name,
		"purchase_order": doc.purchase_order,
		"gate_verification_status": doc.gate_verification_status,
		"is_authorized": match.get("is_authorized"),
	}


@frappe.whitelist()
def confirm_receiving_departure(name):
	"""Confirms the truck has left after dropping off goods — offloading
	takes time, so this is a separate call from verify_receiving_at_gate,
	not a field set at arrival. name here is the Gate Receiving
	Verification record's own name, not the Purchase Order's."""
	if not frappe.db.exists("Gate Receiving Verification", name):
		frappe.response["message"] = {"error": "Gate Receiving Verification " + str(name) + " not found."}
		return

	frappe.db.set_value(
		"Gate Receiving Verification", name, "gate_departure_time", frappe.utils.now_datetime()
	)
	frappe.db.commit()
	frappe.response["message"] = {"name": name, "gate_departure_time": str(frappe.utils.now_datetime())}
