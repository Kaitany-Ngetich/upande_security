"""Appointment document events and permission query.

Ported from Frappe Server Scripts (DB-only records, fixtures/server_script.json).
These are NOT API endpoints: no URL, nothing calls them by name. Frappe fires
them via hooks.py (doc_events / permission_query_conditions), so they are
deliberately NOT decorated with @frappe.whitelist().
"""

import frappe


def clear_appointment_party(doc, method=None):
	"""Before Save: clear party/appointment_with on every save.

	party/appointment_with are core CRM fields this app never uses (Gate
	Guard/Secretary have them locked read-only, the mobile app never sets them,
	and the doctype's real customer-tracking field is custom_customer). Left
	alone, core controller logic auto-fills appointment_with/party with a stale,
	unrelated value whenever customer_email is blank. On production this
	silently linked to whatever Customer record was most recently modified
	anywhere on the bench; locally it landed on the literal string "Customer",
	which fails link validation outright and blocks every save.
	"""
	doc.party = None
	doc.appointment_with = None


def clear_appointment_party_before_insert(doc, method=None):
	"""Before Insert: sibling of clear_appointment_party, same fields/reason.

	ERPNext's core Appointment controller auto-fills party/appointment_with
	from its own before_insert(), which runs before any Before Save hook.
	Clearing only on Before Save was found to still leave some newly created
	Appointments with a stale party/appointment_with (visible on that
	Customer's Connections/activity feed in Desk, which this app must never do,
	since the real customer-tracking field is custom_customer). Clearing here
	too closes that gap at the earliest possible point.
	"""
	doc.party = None
	doc.appointment_with = None


def clear_stale_event_participant(doc, method=None):
	"""After Save: remove the Customer link ERPNext stamps on the linked Event.

	Companion to the two clear_appointment_party hooks. Those clear the
	Appointment's own fields, but ERPNext's core controller separately creates a
	linked calendar Event (doc.calendar_event) and stamps a Customer-type row
	onto ITS event_participants child table, referencing the same stale
	most-recently-modified Customer. That independent write is what leaked every
	Appointment into every unrelated Customer's Desk timeline/activity feed.

	Must run on After Save, not Before/After Insert: doc.calendar_event is still
	None at both of those points (confirmed empirically 2026-10-01). The event
	is created and linked later in the same request.

	Child rows are deleted individually via frappe.delete_doc (the original
	sandbox could not reach frappe.db.delete); kept as-is for faithfulness.

	Round 2 (2026-10-01): even with the participant row gone, the same core flow
	creates a standalone Communication per participant (communication_medium=
	Event, reference_doctype=Event, reference_name=this event) with a
	Communication Link (timeline_links) child row. THAT is what Desk's
	Activity/get_docinfo reads to decide which documents a communication shows
	under. So delete the whole Communication for any Customer-type timeline link
	tied to this event. Nothing in this app intends an Appointment's Event to
	carry a real Customer relationship.
	"""
	if not doc.calendar_event:
		return

	rows = frappe.db.sql(
		"SELECT name FROM `tabEvent Participants` WHERE parent=%s AND reference_doctype=%s",
		(doc.calendar_event, "Customer"),
		as_dict=True,
	)
	for r in rows:
		frappe.delete_doc("Event Participants", r.name, ignore_permissions=True, force=True)

	comm_names = frappe.db.sql(
		"SELECT DISTINCT c.name FROM `tabCommunication` c "
		"JOIN `tabCommunication Link` cl ON cl.parent = c.name "
		"WHERE c.reference_doctype=%s AND c.reference_name=%s AND cl.link_doctype=%s",
		("Event", doc.calendar_event, "Customer"),
		as_dict=True,
	)
	for r in comm_names:
		frappe.delete_doc("Communication", r.name, ignore_permissions=True, force=True)


def appointment_host_wa_number(doc, method=None):
	"""Before Save: set custom_visit_purpose and normalise host WhatsApp number.

	DISABLED by NOT being wired in hooks.py (hook entry left commented out),
	rather than deleted. It was disabled=1 on the local site because it was
	interfering with WhatsApp notifications; it is still ENABLED on production,
	so the Server Script there must be disabled separately when this ships, and
	this function kept so it can be re-enabled by uncommenting one hook line.

	Original reasoning: custom_host_whatsapp_no is fetch_from'd off the host
	Employee's cell_number, usually stored in local Kenyan format
	("0707196203"), but WhatsApp's API needs international format
	("254707196203"). Without conversion the "Visitor at Reception - Host Alert
	(WhatsApp)" notification silently never reaches a real host (frappe_whatsapp
	cannot deliver to a locally-formatted number: no exception, no Error Log).
	"""
	doc.custom_visit_purpose = (doc.customer_details or "").strip() or "a visit"

	raw_number = doc.custom_host_whatsapp_no or ""
	digits = ""
	for ch in raw_number:
		if ch.isdigit():
			digits = digits + ch
	if digits:
		if digits[0] == "0":
			digits = "254" + digits[1:]
		elif digits[0:3] != "254":
			digits = "254" + digits
		doc.custom_host_whatsapp_no = digits


def host_sees_own_appointments(user):
	"""permission_query_conditions for Appointment. RETURNS an SQL fragment.

	Branches (identical to the original script):
	  - user has role Secretary                      -> None (no restriction)
	  - (Host or Visit Approver) and NOT System Manager:
	      - has an Employee with user_id == user     -> "`tabAppointment`.custom_meet_with = <escaped employee name>"
	      - no Employee record                       -> "1=0" (sees nothing)
	  - anyone else (Gate Guard, System Manager, Administrator via no
	    Host role, etc.)                             -> None (no restriction)

	The original left `conditions` unset in the unrestricted cases, which
	resolves to no extra condition; returning None is the equivalent here.
	The employee name is interpolated into SQL, so it goes through
	frappe.db.escape (same safety property as the original); the user is passed
	as a bound parameter to the role lookup.
	"""
	user_roles = [r[0] for r in frappe.db.sql(
		"SELECT role FROM `tabHas Role` WHERE parent = %s AND parenttype = 'User'",
		(user,),
	)]

	if "Secretary" in user_roles:
		return None

	if ("Host" in user_roles or "Visit Approver" in user_roles) and "System Manager" not in user_roles:
		employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
		if employee:
			return "`tabAppointment`.custom_meet_with = " + frappe.db.escape(employee)
		return "1=0"

	return None


# ---------------------------------------------------------------------------
# hooks.py entries (module path assumed: upande_security.api.appointment_events)
#
# doc_events -> the existing "Appointment" dict must be MERGED, keep after_insert
# and on_update exactly as they are:
#
#   "Appointment": {
#       "before_insert": "upande_security.api.appointment_events.clear_appointment_party_before_insert",
#       "before_save": [
#           "upande_security.api.appointment_events.clear_appointment_party",
#           # Disabled, see appointment_host_wa_number docstring. Uncomment to enable:
#           # "upande_security.api.appointment_events.appointment_host_wa_number",
#       ],
#       "after_save": "upande_security.api.appointment_events.clear_stale_event_participant",
#       "after_insert": "upande_security.api.appointment_recipients.notify_extra_recipients",  # existing
#       "on_update": <existing entry, unchanged>,
#   },
#
# permission_query_conditions (top-level dict; merge if it already exists):
#
#   permission_query_conditions = {
#       "Appointment": "upande_security.api.appointment_events.host_sees_own_appointments",
#   }
#
# Before Save ordering: clear_appointment_party only sets party/appointment_with;
# appointment_host_wa_number only sets custom_visit_purpose/custom_host_whatsapp_no.
# Disjoint fields, so order does not matter and they do not conflict.
# Frappe runs a hook list in listed order anyway.
# ---------------------------------------------------------------------------
