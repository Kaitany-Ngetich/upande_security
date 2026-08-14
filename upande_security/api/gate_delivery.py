# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Gate-side lookup and verification for inbound supplier deliveries against
Purchase Order — the authorization a truck's cargo should match, mirroring
how Gate Dispatch Verification (api/gate_dispatch.py) checks outbound trucks
against Dispatch Form.

Unlike dispatch, kept single-doctype and hardcoded to Purchase Order rather
than config-driven across a Security Ops Settings child table — there's
exactly one clear source of inbound delivery authorization in this system,
not several competing ones to plan a config layer around.

Read-only against Purchase Order. Security's own record of having checked a
delivery lives entirely in Gate Delivery Verification, a doctype this app
owns outright. Whether/when a real Purchase Receipt gets created against the
PO is a separate warehouse/procurement step this never touches.
"""

import frappe
from frappe import _

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
def search_delivery_for_gate(reference):
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
		frappe.log_error("search_delivery_for_gate", str(e))
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
def verify_delivery_at_gate(reference, gate_verification_status, vehicle_no=None, driver_name=None, remarks=None):
	"""Creates the actual audit record — a NEW Gate Delivery Verification
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

	doc = frappe.new_doc("Gate Delivery Verification")
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

	frappe.response["message"] = {
		"name": doc.name,
		"purchase_order": doc.purchase_order,
		"gate_verification_status": doc.gate_verification_status,
		"is_authorized": match.get("is_authorized"),
	}


@frappe.whitelist()
def confirm_delivery_departure(name):
	"""Confirms the truck has left after dropping off goods — offloading
	takes time, so this is a separate call from verify_delivery_at_gate,
	not a field set at arrival. name here is the Gate Delivery
	Verification record's own name, not the Purchase Order's."""
	if not frappe.db.exists("Gate Delivery Verification", name):
		frappe.response["message"] = {"error": "Gate Delivery Verification " + str(name) + " not found."}
		return

	frappe.db.set_value(
		"Gate Delivery Verification", name, "gate_departure_time", frappe.utils.now_datetime()
	)
	frappe.db.commit()
	frappe.response["message"] = {"name": name, "gate_departure_time": str(frappe.utils.now_datetime())}
