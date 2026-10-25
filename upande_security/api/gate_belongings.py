# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Passenger names for a gate visit, and carried items for everyone who
comes through the gate.

Two independent Security Ops Settings flags:

- feature_passenger_names: instead of only a head count, the guard records
  each passenger's name / ID / phone when a visitor arrives by Vehicle or
  Motorcycle (Appointment.custom_passengers). custom_number_of_passengers
  is kept equal to the list length so every existing count display - the
  "+N pax" chips, daily summary - keeps working unchanged.
- feature_carried_items: the guard notes what each person brings in, and
  ticks each item off at exit. Anything not ticked is marked "Not seen
  leaving". Every item - visitor, customer, contractor, supplier, staff -
  is one Registered Personal Item linked to the gate record it came in on
  (Appointment, Gate Receiving Verification, Gate Movement or
  Attendance), so all of them are in one list.

Passenger child rows are written directly rather than through
Appointment.save(): a full save fires every Appointment doc_event in
hooks.py (visitor SMS, host notifications, badge release) - none of which
should go off just because a guard added a passenger's name.

The existing booking / check-in / check-out server scripts are untouched.
The app calls these alongside them, so older app builds keep working.
"""

import frappe
from frappe import _

from upande_security.api.feature_flags import is_feature_enabled, require_feature
from upande_security.api.identity import GUARD_LEVEL_ROLES

PASSENGER_FIELD = "custom_passengers"
PASSENGER_DOCTYPE = "Appointment Passenger"
ITEM_DOCTYPE = "Registered Personal Item"

EXIT_INSIDE = "Inside"
EXIT_LEFT = "Left with owner"
EXIT_NOT_SEEN = "Not seen leaving"
EXIT_WITH_DOCUMENT = "Left with document"

_ITEM_FIELDS = [
	"name", "carried_by", "item", "qty", "serial_notes", "declared_at", "exit_status",
	"exit_time", "exit_checked_by", "supporting_document", "supporting_document_file",
]


# --- Registered Personal Item, shared by every kind of gate record ------------------


def item_rows(reference_doctype, reference_names):
	"""Carried items of one gate record (or several - one supplier truck)."""
	if isinstance(reference_names, str):
		reference_names = [reference_names]
	return frappe.get_all(
		ITEM_DOCTYPE,
		filters={"reference_doctype": reference_doctype, "reference_name": ["in", reference_names or [""]]},
		fields=_ITEM_FIELDS,
		order_by="creation asc",
	)


def clean_items(items):
	"""[{item, qty?, serial_notes?, carried_by?}] from the app, blanks dropped."""
	rows = []
	for it in _as_list(items) or []:
		item = _clean(it.get("item"))
		if not item:
			continue
		try:
			qty = int(it.get("qty") or 1)
		except (TypeError, ValueError):
			qty = 1
		rows.append(
			{
				"item": item,
				"qty": max(qty, 1),
				"serial_notes": _clean(it.get("serial_notes")),
				"carried_by": _clean(it.get("carried_by")),
			}
		)
	return rows


def replace_items(reference_doctype, reference_name, rows, party):
	"""Replace what was declared on the way in for this gate record. party:
	party_type, carried_by (default owner), and optionally employee,
	supplier, farm, company."""
	frappe.db.delete(
		ITEM_DOCTYPE,
		{"reference_doctype": reference_doctype, "reference_name": reference_name, "declared_at": "Entry"},
	)
	now = frappe.utils.now_datetime()
	for row in rows:
		doc = frappe.new_doc(ITEM_DOCTYPE)
		doc.update({k: v for k, v in party.items() if v})
		doc.update({k: v for k, v in row.items() if v})
		doc.carried_by = row.get("carried_by") or party.get("carried_by")
		doc.reference_doctype = reference_doctype
		doc.reference_name = reference_name
		doc.declared_at = "Entry"
		doc.exit_status = EXIT_INSIDE
		doc.entry_time = now
		doc.recorded_by = frappe.session.user
		doc.insert(ignore_permissions=True)


def mark_exit(rows, items_out):
	"""Exit check: rows still Inside become "Left with owner" when named in
	items_out, else "Not seen leaving". Returns the rows not seen leaving."""
	items_out = set(items_out or [])
	now = frappe.utils.now_datetime()
	not_seen = []
	for row in rows:
		if row.exit_status != EXIT_INSIDE:
			continue
		status = EXIT_LEFT if row.name in items_out else EXIT_NOT_SEEN
		frappe.db.set_value(
			ITEM_DOCTYPE,
			row.name,
			{"exit_status": status, "exit_time": now, "exit_checked_by": frappe.session.user},
			update_modified=False,
		)
		if status == EXIT_NOT_SEEN:
			not_seen.append(row)
	return not_seen


# Proof a document number can be checked against: a staff member buying from
# the company leaves with a delivery note or sales invoice.
EXIT_PROOF_DOCTYPES = ("Delivery Note", "Sales Invoice")


def record_exit_extras(reference_doctype, reference_name, party, extra_items):
	"""Items leaving that were not registered on the way in - something
	bought from the company, a return, a gate pass. Each needs proof: a
	document number (scanned or typed) or a photo of it. A number that is a
	Delivery Note or Sales Invoice here must be a submitted one. Recorded as
	Registered Personal Items "Left with document" on the gate record, and
	goods leaving on a Delivery Note also get a Dispatch Check (see
	_dispatch_checks_for_exit). Returns the item names recorded."""
	recorded = []
	by_delivery_note = {}
	now = frappe.utils.now_datetime()
	for it in _as_list(extra_items) or []:
		item = _clean(it.get("item"))
		if not item:
			continue
		doc_ref = _clean(it.get("supporting_document"))
		doc_file = _clean(it.get("supporting_document_file"))
		if not doc_ref and not doc_file:
			frappe.throw(
				_("{0} was not registered on the way in. Scan or enter its delivery note / document number, or photograph the document.").format(
					frappe.bold(item)
				)
			)
		for dt in EXIT_PROOF_DOCTYPES:
			status = frappe.db.get_value(dt, doc_ref, "docstatus") if doc_ref else None
			if status is not None and int(status) != 1:
				frappe.throw(_("{0} {1} is not submitted - it cannot cover goods leaving.").format(dt, doc_ref))
		try:
			qty = max(int(it.get("qty") or 1), 1)
		except (TypeError, ValueError):
			qty = 1
		row = frappe.new_doc(ITEM_DOCTYPE)
		row.update({k: v for k, v in party.items() if v})
		row.update(
			{
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"item": item,
				"qty": qty,
				"serial_notes": _clean(it.get("serial_notes")),
				"declared_at": "Exit",
				"entry_time": now,
				"recorded_by": frappe.session.user,
				"exit_status": EXIT_WITH_DOCUMENT,
				"exit_time": now,
				"exit_checked_by": frappe.session.user,
				"supporting_document": doc_ref,
				"supporting_document_file": doc_file,
			}
		)
		row.insert(ignore_permissions=True)
		recorded.append(item)
		if doc_ref and frappe.db.exists("Delivery Note", doc_ref):
			by_delivery_note.setdefault(doc_ref, []).append(row)
	_dispatch_checks_for_exit(by_delivery_note, reference_doctype, reference_name, party)
	return recorded


def _dispatch_checks_for_exit(by_delivery_note, reference_doctype, reference_name, party):
	"""Goods walking out on a Delivery Note are a dispatch like any truck's,
	so each note also gets a Gate Dispatch Verification (Dispatch Checks) -
	the same record a guard makes at the truck gate, built by the same code
	from the note itself, with the person carrying the goods as the driver.

	One check per note, however many items it covered. A note already
	verified at the truck gate is left alone (_verify_dispatch_one refuses a
	second Verified record). Never stops the person leaving: if the check
	cannot be made - Gate Dispatch off, Delivery Note not a configured
	Dispatch Source - the Registered Personal Items still stand and the
	reason is logged."""
	if not by_delivery_note or not is_feature_enabled("feature_gate_dispatch"):
		return
	from upande_security.api.gate_dispatch import _verify_dispatch_one

	vehicle = None
	if reference_doctype == "Appointment" and frappe.get_meta("Appointment").has_field("custom_vehicles_number_plate"):
		vehicle = frappe.db.get_value("Appointment", reference_name, "custom_vehicles_number_plate")

	who = party.get("carried_by") or ""
	for note, rows in by_delivery_note.items():
		declared = ", ".join("{0} x{1}".format(r.item, r.qty) for r in rows)
		remarks = "Carried out at the gate by {0} ({1}, {2} {3}). Declared: {4}. {5}: {6}.".format(
			who or "unknown", party.get("party_type") or "", reference_doctype, reference_name,
			declared, ITEM_DOCTYPE, ", ".join(r.name for r in rows),
		)
		try:
			frappe.db.savepoint("exit_dispatch_check")
			result = _verify_dispatch_one(
				note, "Verified", remarks=remarks, vehicle_no=vehicle, driver_name=who, commit=False,
				farm=party.get("farm"),
			)
			if result.get("error") and "already verified" not in result["error"]:
				frappe.log_error("Exit dispatch check for " + note, result["error"])
		except Exception:
			frappe.db.rollback(save_point="exit_dispatch_check")
			frappe.log_error("Exit dispatch check for " + note, frappe.get_traceback())


def _visit_party(appt):
	party_type = appt.custom_visitor_type if appt.custom_visitor_type in ("Visitor", "Customer", "Contractor") else "Visitor"
	farm = appt.custom_farmunit or appt.custom_meet_with_farm
	if farm and not frappe.db.exists("Farm", farm):
		farm = None
	return {
		"party_type": party_type,
		"carried_by": appt.customer_name,
		"farm": farm,
		"company": appt.custom_company or appt.custom_meet_with_company or (frappe.db.get_value("Farm", farm, "company") if farm else None),
	}


def _require_gate_user():
	"""Guard-tier roles, or anyone who can write Appointments. The second
	half matters: on live, Gate Guard / Security Guard have no Appointment
	DocPerm at all (the gate server scripts never check one), and some
	busy gate accounts hold neither guard role - they reach the gate
	through Visit Approver, which does have Appointment write."""
	roles = frappe.get_roles()
	if "System Manager" in roles or any(r in roles for r in GUARD_LEVEL_ROLES):
		return
	if frappe.has_permission("Appointment", "write"):
		return
	frappe.throw(_("Only gate staff can record passengers and items."), frappe.PermissionError)


def _get_appointment(appointment):
	appointment = (appointment or "").strip()
	if not appointment:
		frappe.throw(_("appointment is required"))
	appt = frappe.db.get_value(
		"Appointment",
		appointment,
		[
			"name", "customer_name", "custom_visitor_type", "custom_check_out_time",
			"custom_farmunit", "custom_meet_with_farm", "custom_company", "custom_meet_with_company",
		],
		as_dict=True,
	)
	if not appt:
		frappe.throw(_("Appointment {0} not found").format(appointment))
	return appt


def _as_list(value):
	if value is None or value == "":
		return None
	if isinstance(value, str):
		value = frappe.parse_json(value)
	if not isinstance(value, list):
		frappe.throw(_("Expected a list"))
	return value


def _clean(value):
	return str(value or "").strip()


def _passenger_rows(appointment):
	return frappe.get_all(
		PASSENGER_DOCTYPE,
		filters={"parent": appointment, "parenttype": "Appointment", "parentfield": PASSENGER_FIELD},
		fields=["name", "full_name", "id_number", "phone"],
		order_by="idx asc",
	)


def _item_rows(appointment):
	return item_rows("Appointment", appointment)


def _known_people(appt, passenger_names):
	"""Everyone an item may be assigned to: the visitor, their passengers,
	and - for a contractor - the personnel the contractor sent."""
	people = [appt.customer_name] + list(passenger_names)
	if appt.custom_visitor_type == "Contractor":
		people += frappe.get_all(
			"Contractor Personnel",
			filters={"parent": appt.name, "parenttype": "Appointment"},
			pluck="full_name",
		)
	return [p for p in people if p]


def _replace_child_rows(appointment, doctype, parentfield, rows):
	frappe.db.delete(doctype, {"parent": appointment, "parenttype": "Appointment", "parentfield": parentfield})
	for idx, row in enumerate(rows, start=1):
		child = frappe.new_doc(doctype)
		child.update(row)
		child.parent = appointment
		child.parenttype = "Appointment"
		child.parentfield = parentfield
		child.idx = idx
		child.db_insert()


@frappe.whitelist()
def get_visit_people_and_items(appointment):
	"""Passengers and carried items for one visit - what the gate shows at
	check-out. Returns empty lists (not an error) when a flag is off, so a
	caller never has to special-case that."""
	_require_gate_user()
	appt = _get_appointment(appointment)
	passengers_on = is_feature_enabled("feature_passenger_names")
	items_on = is_feature_enabled("feature_carried_items")
	passengers = _passenger_rows(appt.name) if passengers_on else []
	return {
		"appointment": appt.name,
		"visitor_name": appt.customer_name,
		"checked_out": bool(appt.custom_check_out_time),
		"passengers": passengers,
		"items": _item_rows(appt.name) if items_on else [],
		"people": _known_people(appt, [p.full_name for p in passengers]),
	}


@frappe.whitelist()
def save_visit_people_and_items(appointment, passengers=None, items=None):
	"""Replace this visit's passenger list and/or carried-item list.

	Either argument may be left out to keep what is already saved. Only
	allowed while the visitor is still on site - once they have checked
	out, the exit record must not be rewritten.

	passengers: [{full_name, id_number?, phone?}]
	items:      [{carried_by, item, qty?, serial_notes?}] - carried_by must
	            be the visitor, one of the passengers, or (contractors) one
	            of the personnel sent.
	"""
	_require_gate_user()
	appt = _get_appointment(appointment)
	if appt.custom_check_out_time:
		frappe.throw(_("{0} has already checked out - passengers and items can no longer be changed.").format(appt.name))

	passengers = _as_list(passengers)
	items = _as_list(items)

	if passengers is not None:
		require_feature("feature_passenger_names")
		clean_passengers = []
		for p in passengers:
			full_name = _clean(p.get("full_name"))
			if not full_name:
				continue
			clean_passengers.append(
				{"full_name": full_name, "id_number": _clean(p.get("id_number")), "phone": _clean(p.get("phone"))}
			)
		_replace_child_rows(appt.name, PASSENGER_DOCTYPE, PASSENGER_FIELD, clean_passengers)
		frappe.db.set_value("Appointment", appt.name, "custom_number_of_passengers", len(clean_passengers))
		passenger_names = [p["full_name"] for p in clean_passengers]
	else:
		passenger_names = [p.full_name for p in _passenger_rows(appt.name)]

	if items is not None:
		require_feature("feature_carried_items")
		people = {p.casefold(): p for p in _known_people(appt, passenger_names)}
		rows = clean_items(items)
		for row in rows:
			carried_by = row["carried_by"] or appt.customer_name
			if carried_by.casefold() not in people:
				frappe.throw(
					_("{0} is not part of this visit - add them as a passenger first.").format(frappe.bold(carried_by))
				)
			row["carried_by"] = people[carried_by.casefold()]
		replace_items("Appointment", appt.name, rows, _visit_party(appt))

	frappe.db.commit()
	return get_visit_people_and_items(appt.name)


@frappe.whitelist()
def check_out_items(appointment, items_out=None, extra_items=None):
	"""Exit check: items_out is the list of carried-item row names the guard
	saw leaving. Every other item still marked Inside becomes "Not seen
	leaving". extra_items: unregistered items leaving, each with proof
	(record_exit_extras). Call this before check_out_visitor."""
	_require_gate_user()
	require_feature("feature_carried_items")
	appt = _get_appointment(appointment)
	extras = record_exit_extras("Appointment", appt.name, _visit_party(appt), extra_items)
	not_seen = mark_exit(_item_rows(appt.name), _as_list(items_out))
	frappe.db.commit()
	return {
		"appointment": appt.name,
		"not_seen_leaving": [r.item + " (" + r.carried_by + ")" for r in not_seen],
		"left_with_document": extras,
	}


# --- Staff -------------------------------------------------------------------
# Staff have no Appointment: staff check-in creates a Gate Movement or
# an HR Attendance depending on the company's Staff Gate Mode. Their items are
# Registered Personal Items linked to whichever of the two it was, with the same exit
# check as a visit. Gated by the same feature_carried_items flag.


def _staff_record(record):
	"""The staff gate record (movement or attendance) as one shape."""
	record = (record or "").strip()
	if not record:
		frappe.throw(_("record is required"))
	mv = frappe.db.get_value(
		"Gate Movement",
		record,
		["name", "employee", "employee_name", "company", "farm", "movement_date", "time_out"],
		as_dict=True,
	)
	if mv:
		return frappe._dict(
			doctype="Gate Movement",
			name=mv.name,
			employee=mv.employee,
			employee_name=mv.employee_name,
			company=mv.company,
			farm=mv.farm,
			date=mv.movement_date,
			checked_out=mv.time_out is not None,
		)
	att = frappe.db.get_value(
		"Attendance",
		record,
		["name", "employee", "employee_name", "company", "custom_farm", "attendance_date", "out_time"],
		as_dict=True,
	)
	if att:
		return frappe._dict(
			doctype="Attendance",
			name=att.name,
			employee=att.employee,
			employee_name=att.employee_name,
			company=att.company,
			farm=att.custom_farm,
			date=att.attendance_date,
			checked_out=bool(att.out_time),
		)
	frappe.throw(_("Staff gate record {0} not found").format(record))


def _employee_name(rec):
	return rec.employee_name or frappe.db.get_value("Employee", rec.employee, "employee_name") or rec.employee


def _staff_item_rows(rec):
	return item_rows(rec.doctype, rec.name)


@frappe.whitelist()
def get_staff_items(record):
	"""Items a staff member brought in on this gate record. Empty (not an
	error) when feature_carried_items is off."""
	_require_gate_user()
	rec = _staff_record(record)
	return {
		"record": rec.name,
		"employee_name": _employee_name(rec),
		"checked_out": rec.checked_out,
		"items": _staff_item_rows(rec) if is_feature_enabled("feature_carried_items") else [],
	}


@frappe.whitelist()
def save_staff_items(record, items=None):
	"""Replace the items a staff member brought in - only while they are
	still on site. items: [{item, qty?, serial_notes?}]."""
	_require_gate_user()
	require_feature("feature_carried_items")
	rec = _staff_record(record)
	if rec.checked_out:
		frappe.throw(_("{0} has already checked out - items can no longer be changed.").format(_employee_name(rec)))

	rows = clean_items(items)
	for row in rows:
		row["carried_by"] = ""  # always the staff member themselves
	replace_items(
		rec.doctype,
		rec.name,
		rows,
		{
			"party_type": "Staff",
			"carried_by": _employee_name(rec),
			"employee": rec.employee,
			"farm": rec.farm,
			"company": rec.company,
		},
	)
	frappe.db.commit()
	return get_staff_items(rec.name)


def _staff_party(rec):
	return {
		"party_type": "Staff",
		"carried_by": _employee_name(rec),
		"employee": rec.employee,
		"farm": rec.farm,
		"company": rec.company,
	}


@frappe.whitelist()
def step_out_staff_items(record, items_out=None, extra_items=None):
	"""A staff member stepping out for a while: the items they take with them
	(ticked) become "Left with owner"; the rest stay inside - it is not a
	check-out. extra_items: unregistered items going out, each with proof."""
	_require_gate_user()
	require_feature("feature_carried_items")
	rec = _staff_record(record)
	going = set(_as_list(items_out) or [])
	now = frappe.utils.now_datetime()
	for row in _staff_item_rows(rec):
		if row.name in going and row.exit_status == EXIT_INSIDE:
			frappe.db.set_value(
				ITEM_DOCTYPE, row.name,
				{"exit_status": EXIT_LEFT, "exit_time": now, "exit_checked_by": frappe.session.user},
				update_modified=False,
			)
	extras = record_exit_extras(rec.doctype, rec.name, _staff_party(rec), extra_items)
	frappe.db.commit()
	return {"record": rec.name, "taken_out": len(going), "left_with_document": extras}


@frappe.whitelist()
def step_in_staff_items(record, items_in=None, new_items=None):
	"""A staff member returning from a step-out: ticked items they took out
	are back inside; new_items are registered as brought in now."""
	_require_gate_user()
	require_feature("feature_carried_items")
	rec = _staff_record(record)
	coming = set(_as_list(items_in) or [])
	for row in _staff_item_rows(rec):
		if row.name in coming and row.exit_status == EXIT_LEFT:
			frappe.db.set_value(
				ITEM_DOCTYPE, row.name, {"exit_status": EXIT_INSIDE, "exit_time": None, "exit_checked_by": None},
				update_modified=False,
			)
	added = []
	now = frappe.utils.now_datetime()
	for row in clean_items(new_items):
		doc = frappe.new_doc(ITEM_DOCTYPE)
		doc.update({k: v for k, v in _staff_party(rec).items() if v})
		doc.update(
			{
				"reference_doctype": rec.doctype,
				"reference_name": rec.name,
				"item": row["item"],
				"qty": row["qty"],
				"serial_notes": row["serial_notes"],
				"declared_at": "Entry",
				"entry_time": now,
				"recorded_by": frappe.session.user,
				"exit_status": EXIT_INSIDE,
			}
		)
		doc.insert(ignore_permissions=True)
		added.append(row["item"])
	frappe.db.commit()
	return {"record": rec.name, "back_inside": len(coming), "added": added}


@frappe.whitelist()
def check_out_staff_items(record, items_out=None, extra_items=None):
	"""Exit check for staff, like check_out_items: items_out names the items
	seen leaving; every other item still Inside becomes "Not seen leaving".
	extra_items: things leaving that were not registered - e.g. bought from
	the company - each with its delivery note / document or a photo.
	Call this before staff_gate_checkout."""
	_require_gate_user()
	require_feature("feature_carried_items")
	rec = _staff_record(record)
	extras = record_exit_extras(rec.doctype, rec.name, _staff_party(rec), extra_items)
	not_seen = mark_exit(_staff_item_rows(rec), _as_list(items_out))
	frappe.db.commit()
	return {"record": rec.name, "not_seen_leaving": [r.item for r in not_seen], "left_with_document": extras}
