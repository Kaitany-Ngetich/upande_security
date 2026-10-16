# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Passenger names and carried items for a gate visit (Appointment), and
carried items for staff (see Staff, at the end).

Two independent Security Ops Settings flags:

- feature_passenger_names: instead of only a head count, the guard records
  each passenger's name / ID / phone when a visitor arrives by Vehicle or
  Motorcycle (Appointment.custom_passengers). custom_number_of_passengers
  is kept equal to the list length so every existing count display - the
  "+N pax" chips, daily summary - keeps working unchanged.
- feature_carried_items: the guard notes what each person brings in
  (Appointment.custom_carried_items), and ticks each item off at exit.
  Anything not ticked is marked "Not seen leaving".

Child rows are written directly rather than through Appointment.save():
a full save fires every Appointment doc_event in hooks.py (visitor SMS,
host notifications, badge release) - none of which should go off just
because a guard added a passenger's name.

The existing booking / check-in / check-out server scripts are untouched.
The app calls these alongside them, so older app builds keep working.
"""

import frappe
from frappe import _

from upande_security.api.feature_flags import is_feature_enabled, require_feature
from upande_security.api.identity import GUARD_LEVEL_ROLES

PASSENGER_FIELD = "custom_passengers"
ITEM_FIELD = "custom_carried_items"
PASSENGER_DOCTYPE = "Appointment Passenger"
ITEM_DOCTYPE = "Appointment Carried Item"

EXIT_INSIDE = "Inside"
EXIT_LEFT = "Left with owner"
EXIT_NOT_SEEN = "Not seen leaving"


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
		["name", "customer_name", "custom_visitor_type", "custom_check_out_time"],
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
	return frappe.get_all(
		ITEM_DOCTYPE,
		filters={"parent": appointment, "parenttype": "Appointment", "parentfield": ITEM_FIELD},
		fields=["name", "carried_by", "item", "qty", "serial_notes", "exit_status", "exit_time", "exit_checked_by"],
		order_by="idx asc",
	)


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
		clean_items = []
		for it in items:
			item = _clean(it.get("item"))
			if not item:
				continue
			carried_by = _clean(it.get("carried_by")) or appt.customer_name
			if carried_by.casefold() not in people:
				frappe.throw(
					_("{0} is not part of this visit - add them as a passenger first.").format(frappe.bold(carried_by))
				)
			try:
				qty = int(it.get("qty") or 1)
			except (TypeError, ValueError):
				qty = 1
			clean_items.append(
				{
					"carried_by": people[carried_by.casefold()],
					"item": item,
					"qty": max(qty, 1),
					"serial_notes": _clean(it.get("serial_notes")),
					"exit_status": EXIT_INSIDE,
				}
			)
		_replace_child_rows(appt.name, ITEM_DOCTYPE, ITEM_FIELD, clean_items)

	frappe.db.commit()
	return get_visit_people_and_items(appt.name)


@frappe.whitelist()
def check_out_items(appointment, items_out=None):
	"""Exit check: items_out is the list of carried-item row names the guard
	saw leaving. Every other item still marked Inside becomes "Not seen
	leaving". Call this before check_out_visitor."""
	_require_gate_user()
	require_feature("feature_carried_items")
	appt = _get_appointment(appointment)
	items_out = set(_as_list(items_out) or [])

	now = frappe.utils.now_datetime()
	not_seen = []
	for row in _item_rows(appt.name):
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
			not_seen.append(row.item + " (" + row.carried_by + ")")

	frappe.db.commit()
	return {"appointment": appt.name, "not_seen_leaving": not_seen}


# --- Staff -------------------------------------------------------------------
# Staff have no Appointment: staff check-in creates a Staff Gate Movement or
# an HR Attendance depending on the company's Staff Gate Mode. Their items are
# Staff Carried Item records pointing at whichever of the two it was, with the
# same exit check as a visit. Gated by the same feature_carried_items flag.

STAFF_ITEM_DOCTYPE = "Staff Carried Item"


def _staff_record(record):
	"""The staff gate record (movement or attendance) as one shape."""
	record = (record or "").strip()
	if not record:
		frappe.throw(_("record is required"))
	mv = frappe.db.get_value(
		"Staff Gate Movement",
		record,
		["name", "employee", "employee_name", "farm", "movement_date", "time_out"],
		as_dict=True,
	)
	if mv:
		return frappe._dict(
			doctype="Staff Gate Movement",
			name=mv.name,
			employee=mv.employee,
			employee_name=mv.employee_name,
			farm=mv.farm,
			date=mv.movement_date,
			checked_out=mv.time_out is not None,
		)
	att = frappe.db.get_value(
		"Attendance",
		record,
		["name", "employee", "employee_name", "custom_farm", "attendance_date", "out_time"],
		as_dict=True,
	)
	if att:
		return frappe._dict(
			doctype="Attendance",
			name=att.name,
			employee=att.employee,
			employee_name=att.employee_name,
			farm=att.custom_farm,
			date=att.attendance_date,
			checked_out=bool(att.out_time),
		)
	frappe.throw(_("Staff gate record {0} not found").format(record))


def _employee_name(rec):
	return rec.employee_name or frappe.db.get_value("Employee", rec.employee, "employee_name") or rec.employee


def _staff_item_rows(rec):
	return frappe.get_all(
		STAFF_ITEM_DOCTYPE,
		filters={"reference_doctype": rec.doctype, "reference_name": rec.name},
		fields=["name", "employee_name as carried_by", "item", "qty", "serial_notes", "exit_status", "exit_time", "exit_checked_by"],
		order_by="creation asc",
	)


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

	clean = []
	for it in _as_list(items) or []:
		item = _clean(it.get("item"))
		if not item:
			continue
		try:
			qty = int(it.get("qty") or 1)
		except (TypeError, ValueError):
			qty = 1
		clean.append({"item": item, "qty": max(qty, 1), "serial_notes": _clean(it.get("serial_notes"))})

	frappe.db.delete(STAFF_ITEM_DOCTYPE, {"reference_doctype": rec.doctype, "reference_name": rec.name})
	for row in clean:
		doc = frappe.new_doc(STAFF_ITEM_DOCTYPE)
		doc.update(row)
		doc.employee = rec.employee
		doc.employee_name = _employee_name(rec)
		doc.reference_doctype = rec.doctype
		doc.reference_name = rec.name
		doc.movement_date = rec.date
		doc.farm = rec.farm
		doc.recorded_by = frappe.session.user
		doc.exit_status = EXIT_INSIDE
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return get_staff_items(rec.name)


@frappe.whitelist()
def check_out_staff_items(record, items_out=None):
	"""Exit check for staff, like check_out_items: items_out names the items
	seen leaving; every other item still Inside becomes "Not seen leaving".
	Call this before staff_gate_checkout."""
	_require_gate_user()
	require_feature("feature_carried_items")
	rec = _staff_record(record)
	items_out = set(_as_list(items_out) or [])

	now = frappe.utils.now_datetime()
	not_seen = []
	for row in _staff_item_rows(rec):
		if row.exit_status != EXIT_INSIDE:
			continue
		status = EXIT_LEFT if row.name in items_out else EXIT_NOT_SEEN
		frappe.db.set_value(
			STAFF_ITEM_DOCTYPE,
			row.name,
			{"exit_status": status, "exit_time": now, "exit_checked_by": frappe.session.user},
			update_modified=False,
		)
		if status == EXIT_NOT_SEEN:
			not_seen.append(row.item)

	frappe.db.commit()
	return {"record": rec.name, "not_seen_leaving": not_seen}
