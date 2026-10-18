# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Covert watchlist: log every transaction of a person under investigation.

A Security Head puts someone on the Security Watchlist - by hand, or from an
Incident Report's people ("Watch a person"). From then on every gate
transaction that identifies them is written to Watchlist Activity and the
Security Heads get an in-app notification, until the entry is set Inactive
(or its incident is Resolved/Closed, when "close with incident" is ticked).

COVERT BY DESIGN. Guards must never learn that someone is being watched, so:
- nothing here changes what a gate endpoint returns or does - no banner, no
  block, no extra field;
- matching runs after the guard's record is saved, and every failure is
  swallowed into the Error Log, never raised into the guard's request;
- notifications go only to users holding Security Head, never through
  Security Ops Settings' Notification Rules (which can route to anyone).

Two ways in, because the gate endpoints are not uniform:
- doc_events (hooks.py) for records created or saved normally: Appointment,
  Attendance, Gate Movement, the three Gate * Verification doctypes,
  Incident Report;
- track() called explicitly by the endpoints that write check-ins and
  check-outs with frappe.db.set_value (security_api.check_in_visitor and
  friends), which fire no hooks at all.
Each (entry, record, activity) is logged once, so a check-in seen by both
paths is not doubled.

Matching keys, strongest first: Employee, ID number, phone, vehicle plate.
A name is used only when one side has nothing stronger - the record carries
just a name (a driver on a dispatch or receiving check), or the watch entry
has no Employee, ID or phone (someone known only by name from an incident).
It must match exactly and is logged as "Name", so investigators can weigh it.
IDs shorter than 5 characters, phones that are not a full Kenyan number and
plates under 4 characters are ignored, so placeholders like "N/A" or "0"
never match each other.
"""

import frappe

from upande_security.api.feature_flags import is_feature_enabled

_CACHE_KEY = "upande_security:watchlist_active"
_CLOSED_INCIDENT_STATUSES = ("Resolved", "Closed")
# Belt and braces on top of clearing the cache on every watchlist save.
_CACHE_TTL_SECONDS = 300


# --- normalisation ------------------------------------------------------------

def _norm_id(value, min_len=5):
	norm = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
	return norm if len(norm) >= min_len else ""


def _norm_phone(value):
	digits = "".join(ch for ch in str(value or "") if ch.isdigit())
	if not digits:
		return ""
	if digits[0] == "0":
		digits = "254" + digits[1:]
	elif len(digits) == 9 and digits[0] in ("7", "1"):
		digits = "254" + digits
	return digits if len(digits) == 12 and digits.startswith("254") else ""


def _norm_name(value):
	return " ".join(str(value or "").lower().split())


# --- active entries -------------------------------------------------------------

def clear_cache():
	frappe.cache.delete_value(_CACHE_KEY)


def _active_entries():
	"""Active entries with their match keys pre-normalised, cached until any
	entry changes. Empty for nearly every request, which is the fast path."""
	if not is_feature_enabled("feature_watchlist"):
		return []
	entries = frappe.cache.get_value(_CACHE_KEY)
	if entries is None:
		entries = []
		for e in frappe.get_all(
			"Security Watchlist",
			filters={"status": "Active"},
			fields=["name", "full_name", "employee", "id_number", "phone_number", "vehicle_plate", "restrict_to_company"],
		):
			entries.append({
				"name": e.name,
				"full_name": e.full_name,
				"company": e.restrict_to_company,
				"employee": e.employee or "",
				"id": _norm_id(e.id_number),
				"phone": _norm_phone(e.phone_number),
				"plate": _norm_id(e.vehicle_plate, min_len=4),
				"person": _norm_name(e.full_name),
			})
		frappe.cache.set_value(_CACHE_KEY, entries, expires_in_sec=_CACHE_TTL_SECONDS)
	return entries


def _matches(subject, company=None):
	"""[(entry, matched_on)] for one person/vehicle described by `subject`
	(keys: employee, id, phone, plate, name - any may be missing)."""
	employee = subject.get("employee") or ""
	id_number = _norm_id(subject.get("id"))
	phone = _norm_phone(subject.get("phone"))
	plate = _norm_id(subject.get("plate"), min_len=4)
	name = _norm_name(subject.get("name"))
	name_only = not (employee or id_number or phone or plate)

	found = []
	for e in _active_entries():
		if e["company"] and company and e["company"] != company:
			continue
		if employee and e["employee"] == employee:
			found.append((e, "Employee"))
		elif id_number and e["id"] == id_number:
			found.append((e, "ID Number"))
		elif phone and e["phone"] == phone:
			found.append((e, "Phone"))
		elif plate and e["plate"] == plate:
			found.append((e, "Vehicle Plate"))
		elif name and (name_only or not (e["employee"] or e["id"] or e["phone"])) and e["person"] == name:
			found.append((e, "Name"))
	return found


# --- recording ---------------------------------------------------------------------

def _security_heads():
	holders = frappe.get_all(
		"Has Role",
		filters={"role": "Security Head", "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	if not holders:
		return []
	return frappe.get_all("User", filters={"name": ["in", holders], "enabled": 1}, pluck="name")


def _record(entry, matched_on, activity_type, doctype, name, farm=None, gate=None, details=None, when=None):
	if frappe.db.exists(
		"Watchlist Activity",
		{"watchlist": entry["name"], "reference_doctype": doctype, "reference_name": name, "activity_type": activity_type},
	):
		return
	when = when or frappe.utils.now_datetime()
	activity = frappe.get_doc({
		"doctype": "Watchlist Activity",
		"watchlist": entry["name"],
		"person": entry["full_name"],
		"activity_type": activity_type,
		"occurred_at": when,
		"matched_on": matched_on,
		"reference_doctype": doctype,
		"reference_name": name,
		"farm": farm,
		"gate": gate,
		"handled_by": frappe.session.user,
		"details": details,
	})
	activity.flags.ignore_links = True
	activity.insert(ignore_permissions=True)

	count = frappe.db.count("Watchlist Activity", {"watchlist": entry["name"]})
	frappe.db.set_value(
		"Security Watchlist", entry["name"],
		{"activity_count": count, "last_activity_on": when},
		update_modified=False,
	)

	subject = "Watchlist: " + (entry["full_name"] or entry["name"]) + " - " + activity_type
	body = (
		activity_type + " at " + (farm or "an unknown farm") + (" (" + gate + ")" if gate else "")
		+ ", " + doctype + " " + name + ". Matched on " + matched_on + "."
		+ ("<br>" + details if details else "")
	)
	for user in _security_heads():
		if user == frappe.session.user:
			continue
		note = frappe.new_doc("Notification Log")
		note.for_user = user
		note.type = "Alert"
		note.subject = subject
		note.email_content = body
		note.document_type = "Watchlist Activity"
		note.document_name = activity.name
		note.insert(ignore_permissions=True)


# --- what each record says about who was involved ---------------------------------

def _subjects(doc):
	"""(farm, gate, [(subject, details)]) describing who this record is about."""
	dt = doc.doctype
	if dt == "Appointment":
		subject = {
			"id": doc.get("custom_id_number"),
			"phone": doc.get("customer_phone_number"),
			"plate": doc.get("custom_vehicles_number_plate"),
			"name": doc.get("customer_name"),
		}
		details = (doc.get("custom_visitor_type") or "Visitor") + " to see " + (doc.get("custom_meet_with_name") or doc.get("custom_meet_with") or "?")
		if doc.get("customer_details"):
			details += " - " + doc.customer_details
		farm = doc.get("custom_farmunit") or doc.get("custom_meet_with_farm")
		return farm, doc.get("custom_exit_gate") or doc.get("custom_entry_gate"), [(subject, details)]
	if dt == "Attendance":
		subject = {"employee": doc.get("employee"), "plate": doc.get("custom_vehicle_number_plate")}
		return doc.get("custom_farm"), doc.get("custom_exit_gate") or doc.get("custom_entry_gate"), [(subject, doc.get("employee_name"))]
	if dt == "Gate Movement":
		subject = {"employee": doc.get("employee"), "plate": doc.get("vehicle_plate")}
		return doc.get("farm"), doc.get("exit_gate") or doc.get("entry_gate"), [(subject, doc.get("employee_name"))]
	if dt == "Gate Vehicle Verification":
		subject = {"plate": doc.get("vehicle_no")}
		details = (doc.get("vehicle_no") or "") + (" - " + doc.task_description if doc.get("task_description") else "")
		return doc.get("to_farm") or doc.get("from_farm"), None, [(subject, details)]
	if dt in ("Gate Dispatch Verification", "Gate Receiving Verification"):
		people = [({"plate": doc.get("vehicle_no")}, "Vehicle " + (doc.get("vehicle_no") or ""))]
		if doc.get("driver_name"):
			people.append(({"name": doc.driver_name}, "Driver " + doc.driver_name))
		farm = doc.get("farm")
		return farm, None, people
	if dt == "Incident Report":
		people = []
		for table, role in (("responsible_persons", "responsible"), ("victims", "victim"), ("witnesses", "witness")):
			for row in doc.get(table) or []:
				subject = {"id": row.get("id_number"), "phone": row.get("contact"), "name": row.get("person_name")}
				people.append((subject, "Named as " + role + " in " + (doc.get("nature_of_incident") or "an incident")))
		return doc.get("farm"), doc.get("location"), people
	return None, None, []


def _company_of(doc):
	for field in ("company", "custom_company", "custom_meet_with_company"):
		if doc.get(field):
			return doc.get(field)
	return None


def _track_doc(doc, activity_type):
	if not _active_entries():
		return
	farm, gate, people = _subjects(doc)
	company = _company_of(doc)
	for subject, details in people:
		for entry, matched_on in _matches(subject, company):
			_record(entry, matched_on, activity_type, doc.doctype, doc.name, farm, gate, details)


# --- entry points ---------------------------------------------------------------------

def _log_failure(title):
	"""Error Log entry for a tracking failure. Must itself never raise: it runs
	after the guard's record is already committed."""
	try:
		frappe.log_error(title)
	except Exception:
		pass


def track(doctype, name, activity_type):
	"""For endpoints that write with frappe.db.set_value (no hooks fire).
	Every call site commits immediately before this, so the rollback here can
	only undo the watchlist's own rows. Never raises."""
	try:
		if not _active_entries():
			return
		_track_doc(frappe.get_doc(doctype, name), activity_type)
		frappe.db.commit()
	except Exception:
		try:
			frappe.db.rollback()
		except Exception:
			pass
		_log_failure("watchlist tracking: " + doctype + " " + str(name))


_SAVEPOINT = "watchlist_tracking"


def on_doc_event(doc, method=None):
	"""doc_events handler for every tracked doctype. Never raises.

	Runs inside the guard's own transaction, so its writes sit behind a
	savepoint: a failure rolls back only the watchlist rows, never the
	guard's Attendance / Appointment / gate record."""
	if not _active_entries() and doc.doctype != "Incident Report":
		return
	try:
		frappe.db.savepoint(_SAVEPOINT)
	except Exception:
		return
	try:
		_handle_doc_event(doc, method)
		frappe.db.release_savepoint(_SAVEPOINT)
	except Exception:
		try:
			frappe.db.rollback(save_point=_SAVEPOINT)
		except Exception:
			pass
		_log_failure("watchlist tracking: " + doc.doctype + " " + str(doc.name))


def _handle_doc_event(doc, method):
	dt = doc.doctype
	if dt == "Appointment":
		if method == "after_insert":
			_track_doc(doc, "Visit Registered")
			# Walk-ins and contractor check-ins are created already checked in.
			if doc.get("custom_check_in_time"):
				_track_doc(doc, "Visitor Check-in")
		elif method == "on_update":
			if doc.get("custom_check_in_time") and doc.has_value_changed("custom_check_in_time"):
				_track_doc(doc, "Visitor Check-in")
			if doc.get("custom_check_out_time") and doc.has_value_changed("custom_check_out_time"):
				_track_doc(doc, "Visitor Check-out")
	elif dt == "Attendance":
		# Only a gate check-in - not HRMS auto-attendance, leave or absences.
		if method == "after_insert" and doc.get("status") == "Present" and doc.get("custom_gate_app_entry"):
			_track_doc(doc, "Staff Check-in")
	elif dt == "Gate Movement":
		if method == "after_insert":
			_track_doc(doc, "Staff Check-in")
	elif dt == "Gate Vehicle Verification":
		if method == "after_insert":
			_track_doc(doc, "Vehicle Exit" if doc.get("gate_exit_time") else "Vehicle Entry")
		elif method == "on_update" and doc.get("gate_entry_time") and doc.has_value_changed("gate_entry_time"):
			_track_doc(doc, "Vehicle Entry")
	elif dt == "Gate Dispatch Verification" and method == "after_insert":
		_track_doc(doc, "Dispatch Check")
	elif dt == "Gate Receiving Verification" and method == "after_insert":
		_track_doc(doc, "Receiving Check")
	elif dt == "Incident Report" and method == "on_update":
		_track_doc(doc, "Named in Incident")
		_close_with_incident(doc)


def _close_with_incident(incident):
	if incident.get("status") not in _CLOSED_INCIDENT_STATUSES:
		return
	for name in frappe.get_all(
		"Security Watchlist",
		filters={"incident": incident.name, "close_with_incident": 1, "status": "Active"},
		pluck="name",
	):
		entry = frappe.get_doc("Security Watchlist", name)
		entry.status = "Inactive"
		entry.closure_notes = "Closed automatically: incident " + incident.name + " was " + incident.status + "."
		entry.save(ignore_permissions=True)


# --- starting a watch from an incident ------------------------------------------------

@frappe.whitelist()
def watch_incident_person(incident, row_name, reason=None, close_with_incident=1):
	"""Put a person named on an Incident Report on the watchlist.
	Security Head / System Manager only."""
	frappe.only_for(("Security Head", "System Manager"))
	inc = frappe.get_doc("Incident Report", incident)
	row = None
	for table in ("responsible_persons", "victims", "witnesses"):
		for r in inc.get(table) or []:
			if r.name == row_name:
				row = r
	if not row:
		frappe.throw("That person is not on incident " + incident + ".")

	existing = frappe.db.get_value(
		"Security Watchlist",
		{"incident": incident, "full_name": row.person_name, "status": "Active"},
		"name",
	)
	if existing:
		return {"name": existing, "existing": True}

	person_type = {"Employee": "Employee", "Visitor": "Visitor", "External": "External"}.get(row.person_type or "", "")
	entry = frappe.get_doc({
		"doctype": "Security Watchlist",
		"full_name": row.person_name,
		"person_type": person_type,
		"id_number": row.id_number,
		"phone_number": row.contact,
		"status": "Active",
		"incident": incident,
		"close_with_incident": frappe.utils.cint(close_with_incident),
		"reason": reason or ((inc.nature_of_incident or "Incident") + " - " + incident),
	})
	entry.insert(ignore_permissions=True)
	return {"name": entry.name, "existing": False}
