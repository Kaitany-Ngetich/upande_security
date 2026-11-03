# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Visitors who go on to other farms of the same company on one badge.

A visit booked at one farm can list further farms ("Also Visiting",
Appointment.custom_also_visiting). The visitor is checked in once, at the
booking farm, and gets that farm's visitor badge as usual. From then on every
gate of a listed farm just scans the badge:

- scan_visitor_badge: records the visitor's entry or exit at this farm in
  Gate Movement (party_type "Visitor", linked to the visit) - the same log as
  staff and contractors, using the contractor badge engine. The visit stays
  open. A badge scanned at a farm not on the visit, at another company, after
  the visit's last day, or on a visit that is not checked in is refused and
  reported as an Invalid Badge Scan.
- final_exit_visitor: the visitor leaves for good at this gate. Any open
  movement is closed, the visit is checked out (security_api.check_out_visitor,
  the same check-out as a single-farm visit), and the badge is collected here.
  Collected at another farm, the badge is "Held at Other Farm" until it is
  back home: scanning it at its own farm's gate returns it to stock.
- visit_route: where the visitor has been and which listed farms remain.
"""

import urllib.parse

import frappe
from frappe import _

from upande_security.api.contractor_badge import _guard_farm
from upande_security.api.security_alerts import log_unauthorized_access

BADGE = "Gate Badge"
MOVEMENT = "Gate Movement"
HELD = "Held at Other Farm"


# --- Booking: the listed farms stay within the visit's company --------------
def validate_farm_stops(doc, method=None):
	"""Appointment validate: every "Also Visiting" farm belongs to the same
	company as the booking farm; no farm twice; the booking farm itself is not
	repeated."""
	rows = doc.get("custom_also_visiting") or []
	if not rows:
		return
	home = (doc.get("custom_farmunit") or "").strip()
	company = _visit_company(doc)
	seen = set()
	keep = []
	for row in rows:
		if not row.farm or row.farm == home or row.farm in seen:
			continue
		farm_company = frappe.db.get_value("Farm", row.farm, "company")
		if company and farm_company and farm_company != company:
			frappe.throw(
				_("{0} belongs to {1}; a visit can only go on to farms of {2}.").format(row.farm, farm_company, company)
			)
		seen.add(row.farm)
		keep.append(row)
	for i, row in enumerate(keep, 1):
		row.idx = i
	doc.set("custom_also_visiting", keep)


def _visit_company(appt):
	if appt.get("custom_company"):
		return appt.get("custom_company")
	farm = (appt.get("custom_farmunit") or "").strip()
	return frappe.db.get_value("Farm", farm, "company") if farm and frappe.db.exists("Farm", farm) else None


# --- Lookups ------------------------------------------------------------------
def _badge_name(reference, farm=None):
	"""Visitor badge from a scan - its QR is /visitor-received?company=&farm=
	&badge=<n> - or a typed reference: the badge name, or a bare number at
	this guard's farm."""
	reference = (reference or "").strip()
	if "visitor-received" in reference and "?" in reference:
		q = urllib.parse.parse_qs(reference.split("?", 1)[1])
		company, bfarm, number = (q.get(k, [""])[0] for k in ("company", "farm", "badge"))
		if company and bfarm and number.isdigit():
			return frappe.db.get_value(
				BADGE, {"badge_type": "Visitor", "company": company, "farm": bfarm, "badge_number": int(number)}, "name"
			)
		return None
	if "/gate-badge/" in reference:
		reference = urllib.parse.unquote(reference.split("/gate-badge/", 1)[1].split("?", 1)[0].strip("/"))
	if frappe.db.exists(BADGE, {"name": reference, "badge_type": "Visitor"}):
		return reference
	if reference.isdigit() and farm:
		return frappe.db.get_value(BADGE, {"badge_type": "Visitor", "farm": farm, "badge_number": int(reference)}, "name")
	return None


def _appointment(name):
	return frappe.db.get_value(
		"Appointment",
		name,
		[
			"name", "customer_name", "customer_phone_number", "custom_company", "custom_farmunit",
			"custom_check_in_time", "custom_check_out_time", "scheduled_time", "custom_expected_exit",
			"custom_meet_with", "custom_visitor_badge", "workflow_state",
		],
		as_dict=True,
	)


def _home_farm(appt, badge=None):
	return (appt.custom_farmunit or "").strip() or (badge.farm if badge else None)


def allowed_farms(appt, badge=None):
	"""The booking farm first, then the listed farms in their order."""
	farms = []
	home = _home_farm(appt, badge)
	if home:
		farms.append(home)
	for f in frappe.get_all(
		"Appointment Farm Stop",
		filters={"parent": appt.name, "parenttype": "Appointment", "parentfield": "custom_also_visiting"},
		pluck="farm",
		order_by="idx asc",
	):
		if f and f not in farms:
			farms.append(f)
	return farms


def _last_day(appt):
	days = [
		frappe.utils.getdate(v)
		for v in (appt.custom_check_in_time, appt.scheduled_time, appt.custom_expected_exit)
		if v
	]
	return max(days) if days else frappe.utils.getdate()


def _movements(badge, appt, farm=None, open_only=False):
	filters = {"party_type": "Visitor", "contractor_badge": badge, "appointment": appt}
	if farm:
		filters["farm"] = farm
	if open_only:
		filters["time_out"] = ["is", "not set"]
	return frappe.get_all(
		MOVEMENT,
		filters=filters,
		fields=["name", "farm", "movement_date", "time_in", "time_out", "entry_gate", "exit_gate", "remarks"],
		order_by="creation asc",
	)


def _record_entry(badge, appt, farm, gate=None, at=None):
	"""A visitor's entry at a farm - the contractor engine's Gate Movement
	row, for a visitor."""
	from upande_security.api.gate_movement import resolve_gate

	at = frappe.utils.get_datetime(at) if at else frappe.utils.now_datetime()
	doc = frappe.new_doc(MOVEMENT)
	doc.update(
		{
			"party_type": "Visitor",
			"employee_name": appt.customer_name,
			"phone": appt.customer_phone_number,
			"contractor_badge": badge.name,
			"appointment": appt.name,
			"company": badge.company or frappe.db.get_value("Farm", farm, "company"),
			"farm": farm,
			"movement_date": at.date(),
			"time_in": at.strftime("%H:%M:%S"),
			"entry_gate": resolve_gate(gate, farm),
			"recorded_by": frappe.session.user,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _close(movement, gate=None, farm=None, remarks=None):
	from upande_security.api.gate_movement import resolve_gate

	now = frappe.utils.now_datetime()
	values = {"time_out": now.strftime("%H:%M:%S") if str(movement.movement_date) == str(now.date()) else "23:59:59"}
	if farm:
		values["exit_gate"] = resolve_gate(gate, farm)
	if remarks:
		values["remarks"] = remarks
	frappe.db.set_value(MOVEMENT, movement.name, values, update_modified=True)


def _ensure_check_in_entry(badge, appt, farm, gate=None):
	"""The visitor went in at the booking farm through the ordinary check-in,
	which records no movement: the first scan there is their exit, so record
	that entry at the check-in time first."""
	if farm != _home_farm(appt, badge) or _movements(badge.name, appt.name):
		return False
	_record_entry(badge, appt, farm, gate, at=appt.custom_check_in_time)
	return True


def _route(badge_name, appt, badge=None):
	moves = _movements(badge_name, appt.name)
	visited = []
	for m in moves:
		if m.farm not in visited:
			visited.append(m.farm)
	return {
		"route": [
			{
				"farm": m.farm,
				"date": str(m.movement_date or ""),
				"time_in": str(m.time_in or ""),
				"time_out": str(m.time_out or ""),
				"remarks": m.remarks or "",
			}
			for m in moves
		],
		"remaining": [f for f in allowed_farms(appt, badge) if f not in visited],
		"farms": allowed_farms(appt, badge),
	}


def _visit_info(badge, appt):
	host = frappe.db.get_value("Employee", appt.custom_meet_with, "employee_name") if appt.custom_meet_with else None
	info = {
		"badge": badge.name,
		"badge_number": badge.badge_number,
		"badge_farm": badge.farm,
		"appointment": appt.name,
		"visitor": appt.customer_name,
		"phone": appt.customer_phone_number,
		"host": host,
		"home_farm": _home_farm(appt, badge),
	}
	info.update(_route(badge.name, appt, badge))
	return info


def _refuse(reference, reason, badge=None, farm=None, appt=None):
	company = frappe.db.get_value("Farm", farm, "company") if farm else None
	detail = "Visitor badge " + (badge.name if badge else str(reference)) + " refused at " + (farm or "the gate") + ": " + reason
	if appt and appt.customer_name:
		detail += " (visitor " + appt.customer_name + ", " + appt.name + ")"
	log_unauthorized_access("Invalid Badge Scan", badge.name if badge else str(reference), detail, company, farm)
	frappe.db.commit()
	return {"accepted": False, "error": reason}


def _checked_badge(reference, farm):
	"""(badge, appt, refusal) for a badge on a visit that may pass this gate."""
	name = _badge_name(reference, farm)
	if not name:
		return None, None, _refuse(reference, "Not a visitor badge we know.", farm=farm)
	badge = frappe.get_doc(BADGE, name)
	company = frappe.db.get_value("Farm", farm, "company")
	if badge.status != "Issued" or not badge.current_appointment:
		return badge, None, _refuse(reference, "Badge " + str(badge.badge_number) + " (" + badge.farm + ") is not issued to a visitor (" + badge.status + ").", badge, farm)
	appt = _appointment(badge.current_appointment)
	if not appt or not appt.custom_check_in_time or appt.custom_check_out_time:
		return badge, appt, _refuse(reference, "The visit on badge " + str(badge.badge_number) + " is not checked in.", badge, farm, appt)
	if company and badge.company != company:
		return badge, appt, _refuse(reference, "Badge " + str(badge.badge_number) + " belongs to " + badge.company + ", not " + company + ".", badge, farm, appt)
	if farm not in allowed_farms(appt, badge):
		return badge, appt, _refuse(
			reference,
			appt.customer_name + " is not booked to visit " + farm + ". Booked: " + ", ".join(allowed_farms(appt, badge)) + ".",
			badge,
			farm,
			appt,
		)
	if frappe.utils.getdate() > _last_day(appt):
		return badge, appt, _refuse(reference, "This visit ended on " + frappe.utils.formatdate(_last_day(appt)) + ".", badge, farm, appt)
	return badge, appt, None


# --- Gate actions -------------------------------------------------------------
@frappe.whitelist(methods=["POST"])
def scan_visitor_badge(reference, gate=None):
	"""A visitor's badge scanned at a gate: their entry or exit at this
	guard's farm. A badge collected at another farm and scanned at its own
	farm goes back to stock."""
	farm = _guard_farm()
	if not farm:
		return {"accepted": False, "error": "Could not tell which farm's gate you are at."}

	held = _badge_name(reference, farm)
	if held and frappe.db.get_value(BADGE, held, "status") == HELD:
		badge = frappe.get_doc(BADGE, held)
		if badge.farm != farm:
			return {
				"accepted": False,
				"error": "Badge " + str(badge.badge_number) + " belongs to " + badge.farm + " (collected at " + (badge.held_at_farm or "another farm") + "). Send it back to " + badge.farm + ".",
			}
		badge.status = "Available"
		badge.save(ignore_permissions=True)
		frappe.db.commit()
		return {"accepted": True, "direction": "Returned", "badge": badge.name, "badge_number": badge.badge_number, "farm": farm}

	badge, appt, refusal = _checked_badge(reference, farm)
	if refusal:
		return refusal

	_ensure_check_in_entry(badge, appt, farm, gate)
	here = _movements(badge.name, appt.name, farm, open_only=True)
	if here:
		_close(here[-1], gate, farm)
		direction, movement = "Exit", here[-1].name
	else:
		# Still recorded inside another farm: no exit scan there - close it.
		for other in _movements(badge.name, appt.name, open_only=True):
			_close(other, remarks="No exit scan - next seen entering " + farm)
		movement = _record_entry(badge, appt, farm, gate).name
		direction = "Entry"
	frappe.db.commit()

	info = _visit_info(badge, appt)
	info.update({"accepted": True, "direction": direction, "movement": movement, "farm": farm})
	return info


@frappe.whitelist(methods=["POST"])
def final_exit_visitor(reference=None, appointment=None, gate=None):
	"""The visitor leaves for good at this gate: close their movements, check
	the visit out and collect the badge here."""
	from upande_security.api.security_api import check_out_visitor

	farm = _guard_farm()
	if not farm:
		return {"accepted": False, "error": "Could not tell which farm's gate you are at."}
	if not reference and appointment:
		reference = frappe.db.get_value("Appointment", appointment, "custom_visitor_badge")
	badge, appt, refusal = _checked_badge(reference, farm)
	if refusal:
		return refusal

	_ensure_check_in_entry(badge, appt, farm, gate)
	for m in _movements(badge.name, appt.name, open_only=True):
		if m.farm == farm:
			_close(m, gate, farm)
		else:
			_close(m, remarks="No exit scan - left for good from " + farm)
	frappe.db.commit()

	info = _visit_info(badge, appt)
	result = check_out_visitor(appt.name)
	if isinstance(result, dict) and result.get("error"):
		return {"accepted": False, "error": result["error"]}

	# check_out_visitor put the badge back in stock; it is physically here.
	if farm != badge.farm:
		doc = frappe.get_doc(BADGE, badge.name)
		doc.held_at_farm = farm
		doc.save(ignore_permissions=True)
		frappe.db.commit()
	info.update(
		{
			"accepted": True,
			"direction": "Final Exit",
			"farm": farm,
			"visit_checked_out": True,
			"badge_status": frappe.db.get_value(BADGE, badge.name, "status"),
			"return_badge_to": badge.farm if farm != badge.farm else None,
		}
	)
	return info


@frappe.whitelist()
def visit_route(appointment):
	"""For the gate screen: the visitor's badge, where they have been and
	which booked farms remain."""
	appt = _appointment(appointment)
	if not appt:
		frappe.throw(_("Visit {0} not found.").format(appointment))
	if not appt.custom_visitor_badge:
		return {"appointment": appt.name, "farms": allowed_farms(appt), "route": [], "remaining": allowed_farms(appt)}
	return _visit_info(frappe.get_doc(BADGE, appt.custom_visitor_badge), appt)
