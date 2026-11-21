# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Plate reads -> sightings -> vehicle visits.

One visit per stay: an entry read opens it, later reads (parking, dock) move
its "last seen", an exit read closes it and the time inside is computed.
Five cameras passed is still one visit.

The camera does not check anyone in. The guard's existing check-in stays
the record; a matched entry read is offered to the guard as a suggestion
(get_gate_suggestions) and the guard's confirmation - or the normal
check-in of that appointment - marks the visit confirmed. Business records
(Appointment, Gate Receiving, Dispatch, fleet trips) are read, never written
to automatically.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime, time_diff_in_seconds

from upande_security.cctv import matching, plates
from upande_security.cctv.alerts import find_rule, raise_alert
from upande_security.cctv.settings import get_settings, is_on

OPEN_STATES = ("On Premises", "Overstayed", "Expected")
ENTRY_ROLES = ("Gate", "Entry")
EXIT_ROLES = ("Exit",)


def _camera(name):
	return frappe.db.get_value("CCTV Camera", name, ["name", "camera_name", "farm", "zone", "gate", "role", "company"], as_dict=True) or frappe._dict()


def _direction(data, cam):
	d = (data.get("direction") or "").lower()
	if d in ("in", "out"):
		return d
	if cam.role in ENTRY_ROLES and cam.role != "Gate":
		return "in"
	if cam.role in EXIT_ROLES:
		return "out"
	return "unknown"


def _open_visit(plate_norm, farm):
	"""The open visit at this site whose plate agrees with the read."""
	rows = frappe.get_all("CCTV Vehicle Visit", filters={"farm": farm, "status": ["in", OPEN_STATES]},
		fields=["name", "plate_normalized"], order_by="entry_time desc", limit=500)
	best, best_score = None, 0
	for r in rows:
		sc = plates.similarity(plate_norm, r.plate_normalized)
		if sc > best_score:
			best, best_score = r.name, sc
	return best if best_score >= 0.9 else None


def _duplicate(plate_norm, camera, direction, when, window):
	if not window:
		return None
	rows = frappe.get_all("CCTV Vehicle Sighting",
		filters={"camera": camera, "sighting_time": [">=", add_to_date(when, seconds=-window)], "direction": direction or ""},
		fields=["name", "plate_normalized", "vehicle_visit"], limit=50)
	for r in rows:
		if plates.similarity(plate_norm, r.plate_normalized) >= 0.9:
			return r
	return None


def handle_plate_read(ev):
	"""Process one plate_read CCTV Event (called from engine.process_event)."""
	if not is_on("anpr_enabled"):
		return "anpr off"
	s = get_settings()
	data = frappe._dict(ev.get("payload_dict") or {})
	cam = _camera(ev.camera)
	farm = ev.farm or cam.farm
	when = get_datetime(ev.event_time)
	raw = data.get("plate") or data.get("plate_normalized") or ""
	norm, swaps = plates.repair(raw, s.plate_formats or None)
	if not norm:
		return "empty plate"
	conf = data.get("confidence") if data.get("confidence") is not None else (ev.confidence or 0) / 100
	direction = _direction(data, cam)

	dup = _duplicate(norm, ev.camera, direction, when, s.duplicate_window_seconds)
	if dup:
		return f"duplicate of {dup.name}"

	sighting = frappe.get_doc({
		"doctype": "CCTV Vehicle Sighting",
		"plate_read": raw,
		"plate_normalized": norm,
		"sighting_time": when,
		"direction": direction,
		"confidence": round(conf * 100, 1),
		"camera": ev.camera,
		"farm": farm,
		"zone": cam.zone,
		"gate": cam.gate,
		"event": ev.name,
		"vehicle_type": data.get("vehicle_type"),
		"colour": data.get("colour"),
		"plate_image": data.get("plate_image_url"),
		"vehicle_image": data.get("vehicle_image_url") or ev.snapshot,
		"match_status": "Pending",
	})
	sighting.flags.ignore_permissions = True
	sighting.flags.ignore_links = True
	sighting.insert()

	_check_watchlist(sighting, cam, direction)

	if conf * 100 < s.min_read_confidence:
		sighting.db_set("match_status", "Ignored")
		return "below minimum confidence"

	visit = _open_visit(norm, farm)
	if direction == "out":
		return _on_exit(sighting, cam, visit, conf)
	if visit:
		_touch(visit, sighting, cam)
		sighting.db_set({"match_status": "Matched", "vehicle_visit": visit})
		return f"seen again on {visit}"
	return _on_entry(sighting, cam, conf, internal=cam.role not in ENTRY_ROLES and direction != "in")


# ------------------------------------------------------------------ watchlist

def _check_watchlist(sighting, cam, direction):
	try:
		from upande_security.api import watchlist
	except ImportError:
		return
	try:
		company = frappe.db.get_value("Farm", sighting.farm, "company") if sighting.farm else None
		hits = watchlist._matches({"plate": sighting.plate_normalized}, company)
		for entry, matched_on in hits:
			watchlist._record(entry, matched_on, "Vehicle Exit" if direction == "out" else "Vehicle Entry",
				"CCTV Vehicle Sighting", sighting.name, farm=sighting.farm, gate=cam.gate,
				details=f"Camera read {sighting.plate_read} ({sighting.confidence}%)", when=sighting.sighting_time)
			sighting.db_set("watchlist_hit", entry["name"])
			raise_alert("Watchlisted Vehicle", farm=sighting.farm, camera=sighting.camera, zone=cam.zone,
				event_time=sighting.sighting_time, source_event=sighting.event, plate=plates.display(sighting.plate_normalized),
				summary=f"Watch-listed: {entry.get('full_name') or entry['name']} (matched on {matched_on}).",
				confidence=sighting.confidence, snapshot=sighting.vehicle_image)
	except Exception:
		frappe.log_error(title="CCTV watchlist check failed")


# ------------------------------------------------------------------ entry / exit

def _touch(visit_name, sighting, cam):
	frappe.db.set_value("CCTV Vehicle Visit", visit_name, {
		"last_seen_time": sighting.sighting_time, "last_seen_camera": sighting.camera, "last_seen_zone": cam.zone,
	})


def _visit_from(best, sighting, cam, entry=True):
	s = get_settings()
	exp_exit = None
	if best and best.get("expected_exit"):
		exp_exit = best.expected_exit
	elif best and best.get("expected_arrival"):
		exp_exit = add_to_date(best.expected_arrival, minutes=s.default_visit_minutes)
	elif entry:
		exp_exit = add_to_date(sighting.sighting_time, minutes=s.default_visit_minutes) if best else None
	doc = frappe.get_doc({
		"doctype": "CCTV Vehicle Visit",
		"plate": plates.display(sighting.plate_normalized),
		"plate_normalized": sighting.plate_normalized,
		"status": "On Premises",
		"farm": sighting.farm,
		"company": frappe.db.get_value("Farm", sighting.farm, "company") if sighting.farm else None,
		"party_type": best.party_type if best else "Unknown",
		"party_name": best.label if best else "Unregistered vehicle",
		"source": best.source if best else "Unregistered",
		"reference_doctype": best.doctype if best else None,
		"reference_name": best.name if best else None,
		"appointment": best.get("appointment") if best else None,
		"host": best.get("host") if best else None,
		"colour": sighting.colour or (best.get("colour") if best else None),
		"vehicle_class": (plates.classify(sighting.plate_normalized) or {}).get("vehicle_class") if plates.classify(sighting.plate_normalized) else None,
		"expected_arrival": best.get("expected_arrival") if best else None,
		"expected_exit": exp_exit,
		"entry_time": sighting.sighting_time if entry else None,
		"entry_camera": sighting.camera if entry else None,
		"entry_gate": cam.gate if entry else None,
		"entry_snapshot": sighting.vehicle_image if entry else None,
		"last_seen_time": sighting.sighting_time,
		"last_seen_camera": sighting.camera,
		"last_seen_zone": cam.zone,
	})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.insert()
	return doc


def _review(reason, sighting, visit, candidates):
	s = get_settings()
	item = frappe.get_doc({
		"doctype": "CCTV Review Item",
		"reason": reason,
		"status": "Open",
		"plate": plates.display(sighting.plate_normalized),
		"farm": sighting.farm,
		"sighting": sighting.name,
		"vehicle_visit": visit,
		"sla_due": add_to_date(now_datetime(), minutes=s.review_sla_minutes),
	})
	for c in candidates[:5]:
		item.append("candidates", {"reference_doctype": c.doctype, "reference_name": c.name, "label": c.label, "score": round(c.score * 100, 1)})
	item.flags.ignore_permissions = True
	item.flags.ignore_links = True
	item.insert()
	frappe.publish_realtime("cctv_review", {"name": item.name, "plate": item.plate, "reason": reason, "farm": item.farm}, after_commit=True)
	return item.name


def _flag(visit, text):
	cur = frappe.db.get_value("CCTV Vehicle Visit", visit, "flags_text") or ""
	if text not in cur:
		frappe.db.set_value("CCTV Vehicle Visit", visit, "flags_text", (cur + "\n" + text).strip())


def _on_entry(sighting, cam, conf, internal=False):
	candidates = matching.find_candidates(sighting.plate_normalized, sighting.farm, sighting.sighting_time)
	best, needs_review, reason = matching.decide(candidates, conf)
	usable = best if best and best.score >= 0.5 else None
	visit = _visit_from(usable, sighting, cam, entry=not internal)
	if internal:
		_flag(visit.name, "Entry not recorded: first seen inside, at " + (cam.camera_name or sighting.camera))
	sighting.db_set({"vehicle_visit": visit.name, "match_status": "Review" if needs_review else "Matched",
		"match_source": usable.source if usable else None, "match_score": round((usable.score if usable else 0) * 100, 1)})

	plate = plates.display(sighting.plate_normalized)
	if needs_review:
		_review(reason, sighting, visit.name, candidates)
	if not candidates:
		raise_alert("Unregistered Vehicle", farm=sighting.farm, camera=sighting.camera, zone=cam.zone,
			event_time=sighting.sighting_time, source_event=sighting.event, plate=plate, vehicle_visit=visit.name,
			summary="No appointment, delivery, trip or registered vehicle matches this plate.",
			confidence=sighting.confidence, snapshot=sighting.vehicle_image)
	elif reason == "Arrived Before Approval":
		_flag(visit.name, f"Arrived before approval ({usable.get('workflow_state')})")
		raise_alert("Arrived Before Approval", farm=sighting.farm, camera=sighting.camera, zone=cam.zone,
			event_time=sighting.sighting_time, plate=plate, vehicle_visit=visit.name, appointment=usable.get("appointment"),
			summary=f"{usable.label}: appointment is still {usable.get('workflow_state')}.")
	# Rule-gated: only where a rule says when vehicles may come.
	if find_rule("Vehicle After Hours", sighting.farm, cam.zone, sighting.camera):
		raise_alert("Vehicle After Hours", farm=sighting.farm, camera=sighting.camera, zone=cam.zone,
			event_time=sighting.sighting_time, plate=plate, vehicle_visit=visit.name,
			summary=f"{visit.party_name} arrived outside permitted hours.")
	_check_zone(sighting, cam, usable, visit.name)
	return f"visit {visit.name}" + (f" (review: {reason})" if needs_review else "")


def _check_zone(sighting, cam, best, visit):
	"""A vehicle read inside a zone it is not allowed in (dock, cold-room yard)."""
	if not cam.zone or cam.role in ENTRY_ROLES:
		return
	try:
		from upande_security.api.zones import is_allowed
		person = {"employee": best.get("employee")} if best else {}
		if not is_allowed(cam.zone, person, sighting.sighting_time):
			raise_alert("Vehicle in Wrong Zone", farm=sighting.farm, camera=sighting.camera, zone=cam.zone,
				event_time=sighting.sighting_time, plate=plates.display(sighting.plate_normalized), vehicle_visit=visit,
				summary=f"{best.label if best else 'Unidentified vehicle'} seen in {cam.zone}.")
	except Exception:
		frappe.log_error(title="CCTV zone check failed")


def _on_exit(sighting, cam, visit, conf):
	if not visit:
		# Leaving with no open visit: the entry was missed. Record it so the time
		# inside is at least bounded, and let the guard sort out who it was.
		candidates = matching.find_candidates(sighting.plate_normalized, sighting.farm, sighting.sighting_time)
		best, _, _ = matching.decide(candidates, conf)
		usable = best if best and best.score >= 0.5 else None
		doc = _visit_from(usable, sighting, cam, entry=False)
		visit = doc.name
		_flag(visit, "Entry not recorded")
		_review("Unmatched" if not usable else "Low Confidence", sighting, visit, candidates)
	v = frappe.get_doc("CCTV Vehicle Visit", visit)
	v.exit_time = sighting.sighting_time
	v.exit_camera = sighting.camera
	v.exit_gate = cam.gate
	v.exit_snapshot = sighting.vehicle_image
	v.last_seen_time = sighting.sighting_time
	v.last_seen_camera = sighting.camera
	v.status = "Departed"
	v.closed_by = "Camera"
	if v.entry_time:
		v.total_minutes = int(time_diff_in_seconds(v.exit_time, v.entry_time) // 60)
	v.flags.ignore_permissions = True
	v.save()
	sighting.db_set({"vehicle_visit": visit, "match_status": "Matched"})
	if v.appointment and not frappe.db.get_value("Appointment", v.appointment, "custom_check_out_time"):
		_flag(visit, "Left without check-out at the gate")
	return f"closed {visit}"


# ------------------------------------------------------------------ scheduled

def check_open_visits():
	"""Scheduler: overstays, and visits still open at the end of the day."""
	if not is_on("anpr_enabled"):
		return
	s = get_settings()
	now = now_datetime()
	for v in frappe.get_all("CCTV Vehicle Visit", filters={"status": "On Premises", "expected_exit": ["is", "set"]},
			fields=["name", "plate", "farm", "expected_exit", "party_name", "last_seen_camera", "appointment"], limit=1000):
		if get_datetime(v.expected_exit) < add_to_date(now, minutes=-s.overstay_grace_minutes):
			frappe.db.set_value("CCTV Vehicle Visit", v.name, "status", "Overstayed")
			raise_alert("Vehicle Overstay", farm=v.farm, camera=v.last_seen_camera, plate=v.plate, vehicle_visit=v.name,
				appointment=v.appointment, event_time=now, subject_key=v.name,
				summary=f"{v.party_name} was expected to leave by {frappe.utils.format_datetime(v.expected_exit, 'HH:mm')}.")


def close_day():
	"""Scheduler (end of day): visits with no exit read become 'Exit Not Recorded'
	and go on the guards' list, rather than staying 'on premises' for ever."""
	if not is_on("anpr_enabled"):
		return
	cutoff = add_to_date(now_datetime(), hours=-12)
	for v in frappe.get_all("CCTV Vehicle Visit", filters={"status": ["in", ["On Premises", "Overstayed"]],
			"entry_time": ["<", cutoff], "party_type": ["not in", ["Staff", "Fleet"]]},
			fields=["name", "plate", "farm", "party_name", "last_seen_camera"], limit=1000):
		frappe.db.set_value("CCTV Vehicle Visit", v.name, {"status": "Exit Not Recorded"})
		raise_alert("Exit Not Recorded", farm=v.farm, camera=v.last_seen_camera, plate=v.plate, vehicle_visit=v.name,
			subject_key=v.name, summary=f"{v.party_name}: no exit read since entry.")


# ------------------------------------------------------------------ guard-facing API

def _require_gate_role():
	roles = set(frappe.get_roles())
	if not roles & {"Gate Guard", "Security Head", "Security Manager", "CCTV Operator", "System Manager"}:
		frappe.throw(_("Not permitted."), frappe.PermissionError)


@frappe.whitelist()
def get_gate_suggestions(farm, gate=None, minutes=15):
	"""Vehicles the gate camera has just read, for the guard to confirm at check-in."""
	_require_gate_role()
	filters = {"farm": farm, "guard_confirmed": 0, "entry_time": [">=", add_to_date(now_datetime(), minutes=-int(minutes))],
		"status": ["in", OPEN_STATES]}
	if gate:
		filters["entry_gate"] = gate
	return frappe.get_all("CCTV Vehicle Visit", filters=filters,
		fields=["name", "plate", "party_type", "party_name", "source", "reference_doctype", "reference_name", "appointment",
			"entry_time", "entry_gate", "entry_snapshot", "colour", "flags_text"], order_by="entry_time desc", limit=20)


@frappe.whitelist()
def confirm_visit(name, reference_doctype=None, reference_name=None, corrected_plate=None, notes=None):
	"""The guard confirms (and if needed corrects) what the camera saw."""
	_require_gate_role()
	v = frappe.get_doc("CCTV Vehicle Visit", name)
	if corrected_plate:
		v.plate = plates.display(corrected_plate)
		v.plate_normalized = plates.normalize(corrected_plate)
	if reference_doctype and reference_name:
		_relink(v, reference_doctype, reference_name)
	v.guard_confirmed = 1
	v.confirmed_by = frappe.session.user
	if notes:
		v.notes = ((v.notes or "") + "\n" + notes).strip()
	v.flags.ignore_permissions = True
	v.save()
	return {"visit": v.name, "appointment": v.appointment}


def _relink(v, doctype, name):
	labels = {
		"Appointment": lambda d: (d.customer_name, d.custom_visitor_type or "Visitor"),
		"Gate Receiving Verification": lambda d: (d.supplier or "Supplier", "Supplier"),
		"Gate Dispatch Verification": lambda d: ("Dispatch " + (d.driver_name or ""), "Fleet"),
		"Gate Vehicle Verification": lambda d: ("Fleet trip " + (d.asset or ""), "Fleet"),
		"Staff Vehicle Sticker": lambda d: ("Staff – " + (frappe.db.get_value("Employee", d.employee, "employee_name") or ""), "Staff"),
		"CCTV Known Vehicle": lambda d: (d.owner_label or d.display_plate, d.category),
	}
	d = frappe.get_doc(doctype, name)
	label, ptype = labels.get(doctype, lambda d: (d.name, "Unknown"))(d)
	v.source = doctype if doctype in labels else v.source
	v.reference_doctype, v.reference_name = doctype, name
	v.party_name, v.party_type = label, ptype if ptype in ("Visitor", "Customer", "Contractor", "Supplier", "Fleet", "Staff") else "Unknown"
	if doctype == "Appointment":
		v.appointment = name
		v.host = d.custom_meet_with
		v.expected_arrival = d.scheduled_time
		if d.custom_expected_exit:
			v.expected_exit = d.custom_expected_exit


@frappe.whitelist()
def resolve_review_item(name, resolution, linked_doctype=None, linked_name=None, corrected_plate=None, notes=None):
	_require_gate_role()
	item = frappe.get_doc("CCTV Review Item", name)
	if item.status == "Resolved":
		return {"ok": True, "name": item.name}
	if resolution in ("Linked", "Walk-in Created") and not (linked_doctype and linked_name):
		frappe.throw(_("Choose the record this vehicle belongs to."))
	if item.vehicle_visit and (linked_doctype or corrected_plate):
		confirm_visit(item.vehicle_visit, linked_doctype, linked_name, corrected_plate, notes)
	if resolution == "Blocked":
		_block(item)
	item.update({"status": "Resolved", "resolution": resolution, "linked_doctype": linked_doctype, "linked_name": linked_name,
		"resolved_by": frappe.session.user, "resolved_at": now_datetime(), "notes": notes})
	item.flags.ignore_permissions = True
	item.save()
	if item.sighting:
		frappe.db.set_value("CCTV Vehicle Sighting", item.sighting, "match_status", "Ignored" if resolution == "Ignored" else "Matched")
	return {"ok": True, "name": item.name}


def _block(item):
	"""Blocking a plate = an Active Security Watchlist entry, so the existing
	watchlist machinery (and every other gate check) picks it up."""
	if not frappe.db.exists("Security Watchlist", {"vehicle_plate": item.plate, "status": "Active"}):
		frappe.get_doc({"doctype": "Security Watchlist", "full_name": f"Vehicle {item.plate}", "person_type": "External",
			"vehicle_plate": item.plate, "status": "Active", "reason": f"Blocked from CCTV review {item.name}",
			"added_by": frappe.session.user, "added_on": frappe.utils.today()}).insert(ignore_permissions=True)


@frappe.whitelist()
def create_walkin_from_review(name, customer_name, phone=None, host=None, purpose=None, visitor_type=None):
	"""Unmatched vehicle -> a walk-in Appointment prefilled with its plate, via
	the gate's own walk-in API (same validation, same notifications)."""
	_require_gate_role()
	item = frappe.get_doc("CCTV Review Item", name)
	from upande_security.api import dashboard_v2
	result = dashboard_v2.create_walk_in(customer_name=customer_name, phone=phone, host=host, purpose=purpose,
		transport="Motorcycle" if (plates.classify(item.plate) or {}).get("vehicle_class") == "Motorcycle" else "Vehicle",
		plate=item.plate, farm=item.farm)
	if result.get("name"):
		resolve_review_item(name, "Walk-in Created", "Appointment", result["name"])
	return result


@frappe.whitelist()
def close_visit(name, notes=None):
	"""Guard closes a visit by hand (exit read missed)."""
	_require_gate_role()
	v = frappe.get_doc("CCTV Vehicle Visit", name)
	v.status = "Closed Manually"
	v.closed_by = "Guard"
	v.exit_time = v.exit_time or now_datetime()
	if v.entry_time:
		v.total_minutes = int(time_diff_in_seconds(v.exit_time, v.entry_time) // 60)
	if notes:
		v.notes = ((v.notes or "") + "\n" + notes).strip()
	v.flags.ignore_permissions = True
	v.save()
	return {"ok": True, "status": v.status}


@frappe.whitelist()
def get_live_vehicles(farm=None):
	"""Vehicles on premises, for the Vehicles board."""
	if not frappe.has_permission("CCTV Vehicle Visit", "read"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	filters = {"status": ["in", ["On Premises", "Overstayed"]]}
	if farm:
		filters["farm"] = farm
	rows = frappe.get_list("CCTV Vehicle Visit", filters=filters,
		fields=["name", "plate", "party_type", "party_name", "farm", "entry_time", "expected_exit", "last_seen_time",
			"last_seen_camera", "last_seen_zone", "status", "guard_confirmed", "flags_text", "appointment"],
		order_by="entry_time desc", limit_page_length=500)
	now = now_datetime()
	for r in rows:
		r.minutes_inside = int(time_diff_in_seconds(now, r.entry_time) // 60) if r.entry_time else None
		r.seen_minutes_ago = int(time_diff_in_seconds(now, r.last_seen_time) // 60) if r.last_seen_time else None
		r.camera_name = frappe.db.get_value("CCTV Camera", r.last_seen_camera, "camera_name") if r.last_seen_camera else None
	return rows


# ------------------------------------------------------------------ doc events

def on_appointment_update(doc, method=None):
	"""Guard checked a visitor in the Desk way: tie it to the camera's visit."""
	if doc.has_value_changed("custom_check_in_time") and doc.custom_check_in_time:
		link_checkin(doc)


def link_checkin(doc_or_name):
	"""Mark the camera's open visit for this appointment's plate as confirmed by
	the guard's check-in. Called from the Desk hook above and from the gate
	app's check_in_visitor (which writes with db.set_value, so no hook fires)."""
	if not is_on("anpr_enabled"):
		return
	try:
		doc = frappe.get_doc("Appointment", doc_or_name) if isinstance(doc_or_name, str) else doc_or_name
		plate = plates.normalize(doc.custom_vehicles_number_plate or doc.custom_motorcycles_plate)
		if not plate:
			return
		farm = doc.custom_farmunit if frappe.db.exists("Farm", doc.custom_farmunit or "") else doc.custom_meet_with_farm
		visit = _open_visit(plate, farm) if farm else None
		if not visit:
			return
		v = frappe.get_doc("CCTV Vehicle Visit", visit)
		if not v.appointment:
			_relink(v, "Appointment", doc.name)
		v.guard_confirmed = 1
		v.confirmed_by = frappe.session.user
		v.flags.ignore_permissions = True
		v.save()
	except Exception:
		frappe.log_error(title="CCTV: linking appointment to vehicle visit failed")
