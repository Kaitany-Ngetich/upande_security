# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Who does this plate belong to? Resolve a camera read against the records
the Security app already keeps, instead of a separate vehicle master.

Order of trust (first that matches well enough wins, the rest become the
guard's alternatives in the review queue):

	1. Appointment         booked visitor / customer / contractor, today, this site
	2. Gate Receiving      a supplier delivery not yet departed
	3. Gate Dispatch       an outgoing load not yet out
	4. Gate Vehicle Verif. a fleet / asset trip between sites
	5. Staff Vehicle Sticker
	6. CCTV Known Vehicle  regular contractors, fleet without an ERPNext Vehicle
	7. ERPNext Vehicle     company fleet

The watchlist is NOT in this list: it is always checked, whatever matches
(vehicles.py), because a booked visitor can still be watch-listed.

Every source is read for a small window (today, this site) and scored in
Python, so look-alike reads (KDA 123A vs KDA 12BA) still find their record -
a SQL equality would miss them.
"""

import frappe
from frappe.utils import add_to_date, get_datetime, getdate

from upande_security.cctv import plates
from upande_security.cctv.settings import get_settings

APPROVED_STATES = {"Approved by Host", "Approved by Secretary", "Visitor Checked In", "Open", None, ""}
PENDING_STATES = {"Pending Secretary Review", "Pending Host Review", "Rescheduled by Secretary", "Rescheduled by Host", "Redirected to Another Host"}
REJECTED_STATES = {"Rejected by Secretary", "Rejected by Host"}


def _cand(source, doctype, name, label, party_type, plate, score, **extra):
	return frappe._dict(source=source, doctype=doctype, name=name, label=label, party_type=party_type,
		plate=plate, score=round(score, 3), **extra)


def _site_company(farm):
	return frappe.db.get_value("Farm", farm, "company") if farm else None


def _appointments(read, farm, at, fuzzy):
	s = get_settings()
	tol = s.match_tolerance_minutes
	start = add_to_date(at, minutes=-(tol + s.default_visit_minutes))
	end = add_to_date(at, minutes=tol)
	stops = frappe.get_all("Appointment Farm Stop", filters={"farm": farm, "parenttype": "Appointment"}, pluck="parent") if farm else []
	or_filters = [["custom_meet_with_farm", "=", farm]] + ([["name", "in", stops]] if stops else [])
	rows = frappe.get_all(
		"Appointment",
		filters=[["scheduled_time", "between", [start, end]]],
		or_filters=or_filters if farm else None,
		fields=["name", "customer_name", "custom_visitor_type", "custom_vehicles_number_plate", "custom_motorcycles_plate",
			"custom_vehicles_colour", "scheduled_time", "custom_expected_exit", "custom_meet_with", "custom_meet_with_farm",
			"workflow_state", "custom_check_in_time", "custom_check_out_time", "customer_organization"],
		limit=500,
	)
	out = []
	for r in rows:
		if r.workflow_state in REJECTED_STATES:
			continue
		# Already checked out before this read: that visit is over.
		if r.custom_check_out_time and get_datetime(r.custom_check_out_time) < add_to_date(at, minutes=-5):
			continue
		best = max(plates.similarity(read, r.custom_vehicles_number_plate, fuzzy),
			plates.similarity(read, r.custom_motorcycles_plate, fuzzy))
		if not best:
			continue
		minutes_off = abs((get_datetime(r.scheduled_time) - at).total_seconds()) / 60
		time_weight = 1.0 if minutes_off <= tol else max(0.6, 1 - (minutes_off - tol) / (tol * 4 or 1))
		label = r.customer_name + (f" ({r.customer_organization})" if r.customer_organization else "")
		out.append(_cand("Appointment", "Appointment", r.name, label, r.custom_visitor_type or "Visitor",
			r.custom_vehicles_number_plate or r.custom_motorcycles_plate, best * time_weight,
			appointment=r.name, host=r.custom_meet_with, colour=r.custom_vehicles_colour,
			expected_arrival=r.scheduled_time, expected_exit=r.custom_expected_exit,
			approved=r.workflow_state in APPROVED_STATES, pending=r.workflow_state in PENDING_STATES,
			booked_site=r.custom_meet_with_farm, workflow_state=r.workflow_state))
	return out


def _receiving(read, farm, at, fuzzy):
	rows = frappe.get_all("Gate Receiving Verification",
		filters={"farm": farm, "gate_departure_time": ["is", "not set"], "creation": [">=", add_to_date(at, days=-3)]},
		fields=["name", "vehicle_no", "supplier", "purchase_order", "driver_name"], limit=200)
	return [_cand("Gate Receiving Verification", "Gate Receiving Verification", r.name,
		(r.supplier or "Supplier") + (f" – PO {r.purchase_order}" if r.purchase_order else ""), "Supplier", r.vehicle_no, sc,
		driver=r.driver_name)
		for r in rows if (sc := plates.similarity(read, r.vehicle_no, fuzzy))]


def _dispatch(read, farm, at, fuzzy):
	rows = frappe.get_all("Gate Dispatch Verification",
		filters={"farm": farm, "gate_exit_time": ["is", "not set"], "dispatch_datetime": [">=", add_to_date(at, days=-2)]},
		fields=["name", "vehicle_no", "driver_name"], limit=200)
	return [_cand("Gate Dispatch Verification", "Gate Dispatch Verification", r.name,
		"Dispatch" + (f" – {r.driver_name}" if r.driver_name else ""), "Fleet", r.vehicle_no, sc)
		for r in rows if (sc := plates.similarity(read, r.vehicle_no, fuzzy))]


def _fleet_trips(read, farm, at, fuzzy):
	rows = frappe.get_all("Gate Vehicle Verification",
		filters={"creation": [">=", add_to_date(at, days=-3)], "gate_entry_time": ["is", "not set"]},
		or_filters=[["from_farm", "=", farm], ["to_farm", "=", farm]],
		fields=["name", "vehicle_no", "task_description", "from_farm", "to_farm", "asset"], limit=200)
	return [_cand("Gate Vehicle Verification", "Gate Vehicle Verification", r.name,
		"Fleet trip" + (f" – {r.asset}" if r.asset else "") + (f" {r.from_farm} → {r.to_farm}" if r.to_farm else ""),
		"Fleet", r.vehicle_no, sc)
		for r in rows if (sc := plates.similarity(read, r.vehicle_no, fuzzy))]


def _registry_rows(doctype, plate_field, filters, fields):
	return frappe.get_all(doctype, filters=filters, fields=fields + [plate_field], limit=5000)


def _stickers(read, company, fuzzy):
	key = plates.skeleton(read)
	out = []
	for r in _registry_rows("Staff Vehicle Sticker", "plate_number",
			{"status": "Active", **({"company": company} if company else {})}, ["name", "employee", "vehicle_type", "color"]):
		if plates.skeleton(r.plate_number)[:3] != key[:3]:
			continue
		sc = plates.similarity(read, r.plate_number, fuzzy)
		if sc:
			name = frappe.db.get_value("Employee", r.employee, "employee_name") if r.employee else None
			out.append(_cand("Staff Vehicle Sticker", "Staff Vehicle Sticker", r.name, "Staff – " + (name or r.employee or "unassigned"),
				"Staff", r.plate_number, sc, employee=r.employee, colour=r.color))
	return out


def _known(read, farm, company, at, fuzzy):
	key = plates.skeleton(read)
	out = []
	for r in _registry_rows("CCTV Known Vehicle", "display_plate", {"status": "Active"},
			["name", "category", "owner_label", "owner_name", "company", "valid_from", "valid_to", "allowed_sites", "colour"]):
		if r.company and company and r.company != company:
			continue
		if (r.valid_from and getdate(at) < r.valid_from) or (r.valid_to and getdate(at) > r.valid_to):
			continue
		sites = [s.strip() for s in (r.allowed_sites or "").splitlines() if s.strip()]
		if sites and farm not in sites:
			continue
		if plates.skeleton(r.display_plate)[:3] != key[:3]:
			continue
		sc = plates.similarity(read, r.display_plate, fuzzy)
		if sc:
			out.append(_cand("CCTV Known Vehicle", "CCTV Known Vehicle", r.name, f"{r.category} – {r.owner_label or r.owner_name or r.display_plate}",
				r.category if r.category in ("Fleet", "Staff", "Contractor", "Supplier", "Customer") else "Unknown",
				r.display_plate, sc, colour=r.colour))
	return out


def _erp_vehicles(read, fuzzy):
	if not frappe.db.exists("DocType", "Vehicle"):
		return []
	key = plates.skeleton(read)
	out = []
	for r in _registry_rows("Vehicle", "license_plate", {}, ["name", "make", "model", "employee", "color"]):
		if plates.skeleton(r.license_plate)[:3] != key[:3]:
			continue
		sc = plates.similarity(read, r.license_plate, fuzzy)
		if sc:
			out.append(_cand("Vehicle", "Vehicle", r.name, "Fleet – " + (" ".join(filter(None, [r.make, r.model])) or r.name),
				"Fleet", r.license_plate, sc, employee=r.employee, colour=r.color))
	return out


def find_candidates(read, farm, at=None):
	"""All plausible owners of a plate read, best first."""
	s = get_settings()
	at = get_datetime(at) if at else frappe.utils.now_datetime()
	company = _site_company(farm)
	fuzzy = bool(s.fuzzy_matching)
	found = []
	for fn, args in (
		(_appointments, (read, farm, at, fuzzy)),
		(_receiving, (read, farm, at, fuzzy)),
		(_dispatch, (read, farm, at, fuzzy)),
		(_fleet_trips, (read, farm, at, fuzzy)),
		(_stickers, (read, company, fuzzy)),
		(_known, (read, farm, company, at, fuzzy)),
		(_erp_vehicles, (read, fuzzy)),
	):
		try:
			found.extend(fn(*args))
		except Exception:
			frappe.log_error(title=f"CCTV plate matching: {fn.__name__} failed")
	order = {k: i for i, k in enumerate(["Appointment", "Gate Receiving Verification", "Gate Dispatch Verification",
		"Gate Vehicle Verification", "Staff Vehicle Sticker", "CCTV Known Vehicle", "Vehicle"])}
	found.sort(key=lambda c: (-c.score, order.get(c.source, 99)))
	return found


def decide(candidates, read_confidence):
	"""(best, needs_review, reason).

	Auto-match only when the read itself is confident, the best candidate's
	plate agrees closely, and no other record is equally plausible. Anything
	else is the guard's call."""
	s = get_settings()
	if not candidates:
		return None, True, "Unmatched"
	best = candidates[0]
	read_ok = (read_confidence or 0) * 100 >= s.auto_match_confidence if read_confidence is not None else False
	tie = len(candidates) > 1 and candidates[1].score >= best.score - 0.05 and candidates[1].name != best.name
	if best.score >= 0.9 and read_ok and not tie:
		if best.source == "Appointment" and best.get("pending"):
			return best, True, "Arrived Before Approval"
		return best, False, None
	return best, True, "Low Confidence"
