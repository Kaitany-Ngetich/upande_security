# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Who is actually driving a staff vehicle through the gate.

A Staff Vehicle Sticker names its owner, but staff lend their car or
motorcycle. After a sticker scan the guard confirms the driver:

- the owner: recorded as before;
- another staff member: their own check-in/out is recorded (they pass the
  sticker to create_staff_attendance / staff_gate_checkout), noting the
  vehicle and whose it is - the owner is not marked in or out;
- someone not on staff: record_sticker_driver logs their own entry or exit
  in Gate Movement as a Driver, with name, ID and phone, the vehicle and
  its owner.

Recorded only - no alert (by request).
"""

import frappe
from frappe import _

MOVEMENT = "Gate Movement"


def sticker_details(sticker):
	"""Owner and vehicle of a sticker, or None."""
	sticker = (sticker or "").strip()
	if not sticker:
		return None
	row = frappe.db.get_value(
		"Staff Vehicle Sticker", sticker, ["name", "employee", "plate_number", "vehicle_type"], as_dict=True
	)
	if not row:
		return None
	row.owner_name = frappe.db.get_value("Employee", row.employee, "employee_name") if row.employee else None
	return row


def borrowed(sticker, driver):
	"""The sticker's details when `driver` (an Employee) is not its owner."""
	row = sticker_details(sticker)
	if row and row.employee and row.employee != driver:
		return row
	return None


def note(direction, row):
	vehicle = (row.vehicle_type or "Vehicle").lower()
	return (
		("Came in" if direction == "in" else "Left")
		+ " on "
		+ (row.owner_name or row.employee)
		+ "'s "
		+ vehicle
		+ (" " + row.plate_number if row.plate_number else "")
	)


@frappe.whitelist(methods=["POST"])
def record_sticker_driver(sticker, driver_name, id_number=None, phone=None, gate=None):
	"""Someone not on staff driving a staff vehicle: their entry or exit at
	this guard's farm - exit when they are recorded inside here with this
	vehicle, otherwise entry."""
	from upande_security.api.gate_movement import resolve_gate
	from upande_security.api.gate_vehicle import _resolve_checking_farm

	driver_name = (driver_name or "").strip()
	if not driver_name:
		frappe.throw(_("Enter the driver's name."))
	row = sticker_details(sticker)
	if not row:
		frappe.throw(_("Vehicle sticker {0} not found.").format(sticker))
	farm = _resolve_checking_farm(frappe.session.user)
	if not farm:
		frappe.throw(_("Could not tell which farm's gate you are at."))

	now = frappe.utils.now_datetime()
	clock = now.strftime("%H:%M:%S")
	open_here = frappe.get_all(
		MOVEMENT,
		filters={"party_type": "Driver", "vehicle_sticker": row.name, "farm": farm, "time_out": ["is", "not set"]},
		pluck="name",
		order_by="creation desc",
		limit=1,
	)
	if open_here:
		frappe.db.set_value(
			MOVEMENT,
			open_here[0],
			{"time_out": clock, "exit_gate": resolve_gate(gate, farm)},
			update_modified=True,
		)
		direction, name = "Exit", open_here[0]
	else:
		doc = frappe.new_doc(MOVEMENT)
		doc.update(
			{
				"party_type": "Driver",
				"employee_name": driver_name,
				"id_number": (id_number or "").strip(),
				"phone": (phone or "").strip(),
				"company": frappe.db.get_value("Farm", farm, "company"),
				"farm": farm,
				"movement_date": now.date(),
				"time_in": clock,
				"entry_gate": resolve_gate(gate, farm),
				"vehicle_plate": row.plate_number,
				"vehicle_sticker": row.name,
				"sticker_owner": row.employee,
				"sticker_owner_name": row.owner_name,
				"recorded_by": frappe.session.user,
			}
		)
		doc.insert(ignore_permissions=True)
		direction, name = "Entry", doc.name
	frappe.db.commit()
	return {
		"direction": direction,
		"movement": name,
		"farm": farm,
		"driver_name": driver_name,
		"plate_number": row.plate_number,
		"owner_name": row.owner_name,
	}
