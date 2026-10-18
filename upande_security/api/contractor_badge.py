# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Contractor badges: book a contractor once, then track them across every
farm of the company by scanning their badge.

- issue_contractor_badge: at contractor check-in the guard gives each crew
  member a numbered pool badge (Gate Badge of type Contractor) for the job - holder,
  contractor, the visit, valid_until (default: the visit's expected exit).
- scan_contractor_badge: at any gate of the issuing company, a scan records
  the holder's movement in Staff Gate Movement (party_type "Contractor") -
  the same log as staff. The direction is worked out: inside this farm ->
  exit, otherwise -> entry. Entering a farm while still recorded inside
  another closes that one first ("no exit scan"). A badge that is not
  issued, expired or from another company is refused and reported as an
  Unauthorized Access Attempt.
- return_contractor_badge: back to the pool at the end of the job; also done
  for every badge of a visit by contractor_gate_checkout.
"""

import urllib.parse

import frappe
from frappe import _

from upande_security.api.security_alerts import log_unauthorized_access

BADGE = "Gate Badge"
TYPE = "Contractor"
MOVEMENT = "Staff Gate Movement"
DEFAULT_VALID_DAYS = 7


def _guard_farm():
	from upande_security.api.gate_vehicle import _resolve_checking_farm

	return _resolve_checking_farm(frappe.session.user)


def _badge_name(reference):
	"""Contractor badge name from a scan (its QR is .../app/gate-badge/<name>)
	or a typed reference - the name itself, or a bare number at this guard's
	company."""
	reference = (reference or "").strip()
	for marker in ("/gate-badge/", "/contractor-badge/"):
		if marker in reference:
			reference = urllib.parse.unquote(reference.split(marker, 1)[1].split("?", 1)[0].strip("/"))
	if frappe.db.exists(BADGE, {"name": reference, "badge_type": TYPE}):
		return reference
	if reference.isdigit():
		farm = _guard_farm()
		company = frappe.db.get_value("Farm", farm, "company") if farm else None
		if company:
			return frappe.db.get_value(BADGE, {"badge_type": TYPE, "company": company, "badge_number": int(reference)}, "name")
	return None


def _open_movement(badge, farm=None):
	filters = {"party_type": "Contractor", "contractor_badge": badge, "time_out": ["is", "not set"]}
	if farm:
		filters["farm"] = farm
	return frappe.get_all(
		MOVEMENT, filters=filters, fields=["name", "farm", "movement_date", "time_in"], order_by="creation desc"
	)


def _visit(appointment):
	appt = frappe.db.get_value(
		"Appointment",
		appointment,
		["name", "custom_visitor_type", "custom_contractor_ref", "custom_company", "custom_expected_exit", "customer_name"],
		as_dict=True,
	)
	if not appt:
		frappe.throw(_("Visit {0} not found.").format(appointment))
	return appt


def _visit_company(appt):
	if appt.custom_company:
		return appt.custom_company
	farm = _guard_farm()
	return frappe.db.get_value("Farm", farm, "company") if farm else None


def _valid_until(appt, valid_until=None):
	until = frappe.utils.getdate(valid_until) if valid_until else None
	if not until and appt.custom_expected_exit:
		until = frappe.utils.getdate(appt.custom_expected_exit)
	if not until or until < frappe.utils.getdate():
		until = frappe.utils.add_days(frappe.utils.getdate(), DEFAULT_VALID_DAYS)
	return until


def _crew(appt):
	crew = frappe.get_all(
		"Contractor Personnel",
		filters={"parent": appt.name, "parenttype": "Appointment"},
		fields=["full_name", "id_number", "is_team_leader"],
		order_by="idx asc",
	)
	crew = [c for c in crew if (c.full_name or "").strip()]
	if not crew and appt.customer_name:
		crew = [frappe._dict(full_name=appt.customer_name, id_number="", is_team_leader=1)]
	return crew


def _issued_on(appt):
	return frappe.get_all(
		BADGE,
		filters={"badge_type": TYPE, "current_appointment": appt.name, "status": "Issued"},
		fields=["name", "badge_number", "holder_name"],
		order_by="badge_number asc",
	)


def _assign(badge, appt, holder_name, holder_id_number=None, valid_until=None):
	"""Give one pool badge to one crew member of this visit."""
	if badge.status == "Lost":
		frappe.throw(_("Badge {0} is marked Lost.").format(badge.badge_number))
	if badge.status == "Issued" and (badge.holder_name or "").casefold() != holder_name.casefold():
		frappe.throw(_("Badge {0} is already with {1}.").format(badge.badge_number, badge.holder_name))
	badge.update(
		{
			"status": "Issued",
			"holder_name": holder_name,
			"holder_id_number": (holder_id_number or "").strip(),
			"supplier": appt.custom_contractor_ref,
			"current_appointment": appt.name,
			"valid_until": _valid_until(appt, valid_until),
			"issued_at": frappe.utils.now_datetime(),
			"issued_by": frappe.session.user,
		}
	)
	badge.save(ignore_permissions=True)
	return badge


@frappe.whitelist(methods=["POST"])
def issue_contractor_badge(appointment, badge_number, holder_name, holder_id_number=None, valid_until=None):
	"""Assign a pool badge (by its number) to one crew member of a contractor
	visit. The badge must be Available, or already held by this same person
	(re-issuing extends it)."""
	holder_name = (holder_name or "").strip()
	if not holder_name:
		frappe.throw(_("Who is the badge for?"))
	appt = _visit(appointment)
	company = _visit_company(appt)
	if not company:
		frappe.throw(_("Could not tell which company's badges to use for this visit."))
	try:
		number = int(str(badge_number).strip())
	except (TypeError, ValueError):
		frappe.throw(_("Badge number must be a number."))
	name = frappe.db.get_value(BADGE, {"badge_type": TYPE, "company": company, "badge_number": number}, "name")
	if not name:
		frappe.throw(_("There is no contractor badge {0} for {1}.").format(number, company))
	badge = _assign(frappe.get_doc(BADGE, name), appt, holder_name, holder_id_number, valid_until)
	frappe.db.commit()
	return _badge_info(badge)


@frappe.whitelist(methods=["POST"])
def issue_badges_to_crew(appointment):
	"""Give every crew member of this visit who has no badge yet the lowest
	numbered Available contractor badge of the company. Returns who got
	which number, and how many are still without one if the pool ran out."""
	appt = _visit(appointment)
	company = _visit_company(appt)
	if not company:
		frappe.throw(_("Could not tell which company's badges to use for this visit."))
	have = {(b.holder_name or "").casefold() for b in _issued_on(appt)}
	need = [c for c in _crew(appt) if c.full_name.casefold() not in have]
	free = frappe.get_all(
		BADGE,
		filters={"badge_type": TYPE, "company": company, "status": "Available"},
		pluck="name",
		order_by="badge_number asc",
		limit=len(need) or 1,
	)
	issued = []
	for person, name in zip(need, free):
		badge = _assign(frappe.get_doc(BADGE, name), appt, person.full_name, person.id_number)
		issued.append({"holder_name": person.full_name, "badge_number": badge.badge_number})
	frappe.db.commit()
	return {"issued": issued, "still_needed": max(len(need) - len(free), 0) if need else 0}


def has_badge_pool(company):
	return bool(company) and bool(frappe.db.exists(BADGE, {"badge_type": TYPE, "company": company}))


def crew_without_badges(appointment):
	"""Names on a contractor visit's crew list with no badge yet - empty when
	it is not a contractor visit or the company keeps no contractor badges
	(nothing to enforce there)."""
	appt = _visit(appointment)
	if appt.custom_visitor_type != "Contractor" or not has_badge_pool(_visit_company(appt)):
		return []
	have = {(b.holder_name or "").casefold() for b in _issued_on(appt)}
	return [c.full_name for c in _crew(appt) if c.full_name.casefold() not in have]


def record_check_in_entries(appointment, gate=None):
	"""At contractor check-in, every badge holder on the visit has entered this
	farm - record it, so their next scan here is their exit."""
	appt = _visit(appointment)
	farm = _guard_farm()
	if not farm:
		return
	for b in _issued_on(appt):
		if not _open_movement(b.name, farm):
			_record_entry(frappe.get_doc(BADGE, b.name), farm, gate)


def _badge_info(badge):
	return {
		"badge": badge.name,
		"badge_number": badge.badge_number,
		"company": badge.company,
		"holder_name": badge.holder_name,
		"holder_id_number": badge.holder_id_number,
		"contractor": badge.supplier,
		"contractor_name": frappe.db.get_value("Supplier", badge.supplier, "supplier_name") if badge.supplier else None,
		"valid_until": str(badge.valid_until or ""),
	}


def _refuse(reference, reason, badge=None, farm=None):
	company = frappe.db.get_value("Farm", farm, "company") if farm else None
	detail = "Contractor badge " + (badge.name if badge else str(reference)) + " refused at " + (farm or "the gate") + ": " + reason
	if badge and badge.holder_name:
		detail += " (holder " + badge.holder_name + ")"
	log_unauthorized_access("Contractor Badge Refused", badge.name if badge else str(reference), detail, company, farm)
	frappe.db.commit()
	return {"accepted": False, "error": reason}


@frappe.whitelist(methods=["POST"])
def scan_contractor_badge(reference, gate=None):
	"""A contractor's badge scanned at a gate: record their entry or exit at
	this guard's farm. Soft-fails with {accepted: False, error} when the
	badge must not pass - that refusal is also reported."""
	from upande_security.api.gate_movement import resolve_gate

	farm = _guard_farm()
	if not farm:
		return {"accepted": False, "error": "Could not tell which farm's gate you are at."}

	name = _badge_name(reference)
	if not name:
		return _refuse(reference, "Not a contractor badge we know.", farm=farm)
	badge = frappe.get_doc(BADGE, name)
	company = frappe.db.get_value("Farm", farm, "company")
	if badge.status != "Issued" or not badge.holder_name:
		return _refuse(reference, "Badge " + str(badge.badge_number) + " is not issued to anyone (" + badge.status + ").", badge, farm)
	if badge.company != company:
		where = company or farm
		return _refuse(
			reference,
			"Badge " + str(badge.badge_number) + " belongs to " + badge.company + ", not " + where + ("" if where.endswith(".") else "."),
			badge,
			farm,
		)
	if badge.valid_until and frappe.utils.getdate(badge.valid_until) < frappe.utils.getdate():
		return _refuse(reference, "Badge " + str(badge.badge_number) + " expired on " + frappe.utils.formatdate(badge.valid_until) + ".", badge, farm)

	now = frappe.utils.now_datetime()
	clock = now.strftime("%H:%M:%S")
	here = _open_movement(badge.name, farm)
	if here:
		mv = here[0]
		frappe.db.set_value(
			MOVEMENT, mv.name, {"time_out": clock, "exit_gate": resolve_gate(gate, farm)}, update_modified=True
		)
		direction, movement = "Exit", mv.name
	else:
		# Still recorded inside another farm: that visit ended without an
		# exit scan - close it at the time of this entry.
		for other in _open_movement(badge.name):
			frappe.db.set_value(
				MOVEMENT,
				other.name,
				{"time_out": clock if str(other.movement_date) == str(now.date()) else "23:59:59", "remarks": "No exit scan - next seen entering " + farm},
				update_modified=True,
			)
		doc = _record_entry(badge, farm, gate, company)
		direction, movement = "Entry", doc.name

	frappe.db.commit()
	info = _badge_info(badge)
	info.update({"accepted": True, "direction": direction, "movement": movement, "farm": farm})
	return info


def _record_entry(badge, farm, gate=None, company=None):
	from upande_security.api.gate_movement import resolve_gate

	now = frappe.utils.now_datetime()
	doc = frappe.new_doc(MOVEMENT)
	doc.update(
		{
			"party_type": "Contractor",
			"employee_name": badge.holder_name,
			"id_number": badge.holder_id_number,
			"contractor": badge.supplier,
			"contractor_badge": badge.name,
			"company": company or frappe.db.get_value("Farm", farm, "company"),
			"farm": farm,
			"movement_date": now.date(),
			"time_in": now.strftime("%H:%M:%S"),
			"entry_gate": resolve_gate(gate, farm),
			"recorded_by": frappe.session.user,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


@frappe.whitelist(methods=["POST"])
def return_contractor_badge(badge):
	"""Back to the pool. Any visit still open on it is closed now."""
	name = _badge_name(badge)
	if not name:
		frappe.throw(_("Contractor badge {0} not found.").format(badge))
	_close_and_release(name)
	frappe.db.commit()
	return {"badge": name, "status": "Available"}


def _close_and_release(name):
	clock = frappe.utils.nowtime()
	for mv in _open_movement(name):
		frappe.db.set_value(MOVEMENT, mv.name, {"time_out": clock, "remarks": "Badge returned"}, update_modified=True)
	doc = frappe.get_doc(BADGE, name)
	if doc.status != "Lost":
		doc.status = "Available"
		doc.save(ignore_permissions=True)


def release_badges_for_visit(appointment):
	"""Every contractor badge issued on this visit back to the pool - called
	when the contractor visit is checked out."""
	for name in frappe.get_all(BADGE, filters={"badge_type": TYPE, "current_appointment": appointment, "status": "Issued"}, pluck="name"):
		_close_and_release(name)


@frappe.whitelist()
def badges_for_visit(appointment):
	"""For the check-in screen: the crew on a contractor visit, the badges
	already issued on it, the default valid-until date, and whether badges
	are required before check-in (the company keeps a contractor badge pool)."""
	appt = _visit(appointment)
	company = _visit_company(appt)
	return {
		"crew": _crew(appt),
		"badges": [_badge_info(frappe.get_doc(BADGE, b.name)) for b in _issued_on(appt)],
		"valid_until": str(_valid_until(appt)),
		"required": has_badge_pool(company),
		"available": frappe.db.count(BADGE, {"badge_type": TYPE, "company": company, "status": "Available"}) if company else 0,
	}
