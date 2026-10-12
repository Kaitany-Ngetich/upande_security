# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Every API endpoint the Security Gate mobile app calls, in one file.

ONE FILE, ON PURPOSE
--------------------
These were API-type Server Scripts: logic living in the database, invisible
to git, unreviewable, untestable, and written against the `safe_exec`
sandbox (no imports, no f-strings, bracket-only dict access,
`frappe.utils.x()` only). They now live here as ordinary Python.

They are deliberately NOT split across per-domain modules. When something
fails at a gate at 3am, the traceback names this file and a line number,
and there is exactly one place to look. Sections below are fixed and
ordered; find the endpoint by its section banner.

NAVIGATING
----------
Sections, in order. Each is introduced by a full-width `# ===` banner, so
searching for the banner text jumps straight to it:

    SECTION 1   SESSION & LOOKUPS
    SECTION 2   VISITORS
    SECTION 3   CONTRACTORS
    SECTION 4   BADGES
    SECTION 5   STAFF GATE
    SECTION 6   PATROLS
    SECTION 7   INCIDENTS
    SECTION 8   SHIFTS
    SECTION 9   ASSETS
    SECTION 10  VEHICLE STICKERS
    SECTION 11  DASHBOARDS & REPORTS

Within a section, functions are in the order the app uses them: read
before write, search before act.

HOW THE APP STILL REACHES THESE
-------------------------------
The app posts to bare paths (`/api/method/get_employee`), which Frappe
resolves only through the Server Script map. `hooks.py`'s
`override_whitelisted_methods` aliases each bare name onto the function
here, and `frappe.handler.execute_cmd` consults that map BEFORE the Server
Script map and before `get_attr`:

    def execute_cmd(cmd, from_async=False):
            cmd = frappe.override_whitelisted_method(cmd)   # <- first
            server_script = get_server_script_map().get("_api", {}).get(cmd)

So an APK already installed at a gate keeps working with no rebuild and no
OTA. Every alias here is load-bearing for builds we cannot inspect - a
handset can outlive several releases, and these paths are its only way in.
tests/test_bare_paths.py pins them so a deletion fails a test, not a gate.

THE RESPONSE CONTRACT
---------------------
Each function returns its payload; Frappe wraps a return value in
`message`, exactly as `frappe.response["message"] = ...` did.

Failure is signalled by RETURNING `{"error": "..."}` at HTTP 200, matching
what the Server Scripts did. This is not stylistic: `lib/api/client.ts`
treats 401/403 as a dead session, calls `forgetDevice()` and redirects to
login, so raising here would log a guard out mid-shift rather than show
them a message.

The exception is `contractor_gate_checkout`, which used `frappe.throw` as a
Server Script and still does. Its behaviour is preserved exactly rather
than "fixed" - the installed app already handles the HTTP error it
produces, and quietly changing that is a behaviour change in the field.

Parameters are left unannotated. `frappe.whitelist` applies
`validate_argument_types`, which `safe_exec` never did; adding `: int` or
`: str` would newly enforce coercion on values these endpoints have always
taken as free-form strings.

Each function keeps the `frappe.log_error(<api_method>, ...)` title its
Server Script used, so existing Error Log entries stay greppable by the
same name.
"""

import frappe


# =============================================================================
# SECTION 1   SESSION & LOOKUPS
# =============================================================================
# Read-only. Nothing here writes, so these were migrated first as the pilot.


@frappe.whitelist()
def get_session_info():
	"""Who is logged in, what they may do, and which features are on.

	Drives the app's side menu and every role-gated screen, so it is the
	first call after login.
	"""
	try:
		user = frappe.session.user
		full_name = frappe.db.get_value("User", user, "full_name") or user

		role_rows = frappe.db.sql("SELECT role FROM `tabHas Role` WHERE parent = %s", (user,))
		roles = [r[0] for r in role_rows if r and r[0]]

		employee = frappe.db.get_value(
			"Employee",
			{"user_id": user},
			["name", "employee_name", "department", "designation", "company", "custom_farm"],
			as_dict=True,
		)

		# Command Center (the app's admin view - shift planning, full incident
		# list, sticker/badge approvals, Security Ops Settings) is strictly
		# role-gated: Security Head or System Manager only. No allowlist
		# bypass - every action inside it is itself sensitive, so access has
		# to track the same role that already governs write permission on
		# those doctypes rather than a separate list that could drift.
		has_command_center_access = "Security Head" in roles or "System Manager" in roles

		# Keep in sync with FEATURE_FIELDS in api/feature_flags.py. This list
		# was duplicated because a sandboxed Server Script could not import
		# that module; now that this is ordinary Python the duplication is no
		# longer forced, but it is kept for this migration so behaviour is
		# provably identical. Collapsing the two is a follow-up.
		#
		# Missing/None reads as enabled (fails open), matching
		# feature_flags.is_feature_enabled() - a site predating a flag keeps
		# behaving as it always has.
		feature_field_names = [
			"feature_visitor_approval_workflow",
			"feature_contractor_checkin",
			"feature_sos_alert",
			"feature_patrol_geofence_alerts",
			"feature_security_alerts",
			"feature_watchlist",
			"feature_asset_scanning",
			"feature_gate_dispatch",
			"feature_gate_receiving",
			"feature_vehicle_stickers",
			"feature_visitor_badges",
			"feature_supplier_badges",
			"feature_command_center",
			"feature_visitor_sms_otp",
			"feature_staff_checkin",
			"feature_vehicle_gate_tracking",
			"feature_taxi_driver_checkout",
			"feature_gate_temp_exit",
			"feature_host_receipt_confirmation",
			"feature_passenger_names",
			"feature_carried_items",
		]
		raw_flags = (
			frappe.db.get_value(
				"Security Ops Settings", "Security Ops Settings", feature_field_names, as_dict=True
			)
			or {}
		)
		features = {}
		for flag_name in feature_field_names:
			flag_value = raw_flags.get(flag_name)
			features[flag_name] = True if flag_value is None else bool(flag_value)

		return {
			"user": user,
			"full_name": full_name,
			"roles": roles,
			"is_gate_guard": "Gate Guard" in roles,
			"is_security_head": "Security Head" in roles,
			"has_command_center_access": has_command_center_access
			and features.get("feature_command_center", True),
			"employee": employee or {},
			"features": features,
		}
	except Exception as e:
		frappe.log_error("get_session_info", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def get_employee(name=None):
	"""Full employee record for staff attendance and host pre-fill.

	Note the key rename on the way out: `employee_category` is returned as
	`custom_employee_category`, which is what the app reads. Kept exactly as
	the Server Script had it - the handset depends on this spelling.
	"""
	try:
		name = str(name or "").strip()
		if not name:
			return {"error": "name is required"}

		emp = frappe.db.get_value(
			"Employee",
			name,
			[
				"name",
				"employee_name",
				"department",
				"designation",
				"company",
				"default_shift",
				"custom_farm",
				"employee_category",
				"status",
			],
			as_dict=True,
		)
		if not emp:
			return {"error": "Employee " + name + " not found"}

		return {
			"name": emp.name,
			"employee_name": emp.employee_name or "",
			"department": emp.department or "",
			"designation": emp.designation or "",
			"company": emp.company or "",
			"default_shift": emp.default_shift or "",
			"custom_farm": emp.custom_farm or "",
			"custom_employee_category": emp.employee_category or "",
			"status": emp.status or "",
		}
	except Exception as e:
		frappe.log_error("get_employee", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def search_employees(query=None):
	"""Type-ahead host search over Active employees.

	Raw SQL rather than get_all because the original matched on either the
	employee ID or the name with a single OR, which get_all's filter syntax
	cannot express without an or_filters split.
	"""
	try:
		query = str(query or "").strip()
		# The handset fires on every keystroke; two characters is the floor
		# that keeps this from scanning the whole roster on "a".
		if len(query) < 2:
			return []

		like = "%" + query + "%"
		rows = frappe.db.sql(
			"""
			SELECT name, employee_name, designation, department, status
			FROM `tabEmployee`
			WHERE status = 'Active'
			  AND (name LIKE %s OR employee_name LIKE %s)
			ORDER BY employee_name ASC
			LIMIT 20
			""",
			(like, like),
			as_dict=True,
		)
		return [
			{
				"name": r.name,
				"employee_name": r.employee_name or "",
				"designation": r.designation or "",
				"department": r.department or "",
				"status": r.status or "",
			}
			for r in rows
		]
	except Exception as e:
		frappe.log_error("search_employees", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def search_staff(query=None):
	"""Staff lookup for the gate's Staff tab - exact employee ID first, then
	a name/ID LIKE search.

	Returns BOTH a `matches` list and a flattened copy of the best match at
	the top level. Older installed builds only read the flat
	found/employee_id/full_name shape and never learned about `matches`, so
	both must stay until every device is upgraded.
	"""
	try:
		query = str(query or "").strip()
		if not query:
			return {"error": "query is required"}

		fields = [
			"name",
			"employee_name",
			"department",
			"designation",
			"company",
			"default_shift",
			"custom_farm",
			"employee_category",
		]

		exact = frappe.db.get_value("Employee", {"name": query, "status": "Active"}, fields, as_dict=True)

		if exact:
			rows = [exact]
		else:
			like = "%" + query + "%"
			rows = frappe.db.sql(
				"""
				SELECT name, employee_name, department, designation, company,
				       default_shift, custom_farm, employee_category
				FROM `tabEmployee`
				WHERE status = 'Active'
				  AND (name LIKE %s OR employee_name LIKE %s)
				ORDER BY employee_name ASC
				LIMIT 20
				""",
				(like, like),
				as_dict=True,
			)

		matches = [
			{
				"employee_id": r.name,
				"full_name": r.employee_name or "",
				"department": r.department or "",
				"designation": r.designation or "",
				"company": r.company or "",
				"default_shift": r.default_shift or "",
				"custom_farm": r.custom_farm or "",
				"custom_employee_category": r.employee_category or "",
			}
			for r in rows
		]

		result = {"matches": matches}
		if matches:
			best = matches[0]
			result["found"] = True
			result["employee_id"] = best["employee_id"]
			result["full_name"] = best["full_name"]
			result["department"] = best["department"]
			result["designation"] = best["designation"]
			result["company"] = best["company"]
			result["default_shift"] = best["default_shift"]
			result["custom_farm"] = best["custom_farm"]
			result["custom_employee_category"] = best["custom_employee_category"]
		else:
			result["found"] = False
			result["query"] = query
		return result
	except Exception as e:
		frappe.log_error("search_staff", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def search_customers(query=None):
	"""Customer lookup for the customer-appointment booking screen.

	An empty query deliberately returns the first 20 customers rather than
	an empty list - the screen opens with the picker already populated.
	"""
	try:
		query = str(query or "").strip()
		filters = {}
		if query:
			filters["customer_name"] = ["like", "%" + query + "%"]

		rows = frappe.get_all(
			"Customer",
			filters=filters,
			fields=["name", "customer_name", "mobile_no", "email_id"],
			order_by="customer_name asc",
			limit_page_length=20,
		)
		return [
			{
				"name": r.name,
				"customer_name": r.customer_name,
				"mobile_no": r.mobile_no or "",
				"email_id": r.email_id or "",
			}
			for r in rows
		]
	except Exception as e:
		frappe.log_error("search_customers", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def get_security_head_contact():
	"""Who the calling guard should ring in an emergency, and on what number.

	Resolution order, narrowest first: a Security Head holding a Farm User
	Permission for this guard's farm, then one holding a Company permission,
	then that company's own Security Fallback Contact row.

	Joins to User, not Employee, for the phone. A Security Head's login
	always has a User record, but several real heads on this site are shared
	desk accounts with no Employee at all, and even those that have one
	often leave Employee.cell_number blank while User.mobile_no is set.

	When nothing resolves it returns an error naming the company rather than
	a generic number. The single org-wide fallback was removed once every
	company got its own row: a company with neither a head nor a fallback is
	a real gap to fix by adding a row, not something to paper over with a
	stale number that may ring nobody.
	"""
	try:
		current_user = frappe.session.user
		company = ""
		farm = ""

		# Same resolution order as submit_patrol_points: Employee linked to
		# this login first, then Security Guard matched on full name
		# (Security Guard has no user_id, so a name match is the only link
		# available for guards who are not in Employee at all).
		employee = frappe.db.get_value(
			"Employee", {"user_id": current_user}, ["company", "custom_farm"], as_dict=True
		)
		if employee:
			company = employee.company or ""
			farm = employee.custom_farm or ""
		else:
			user_full = frappe.db.get_value("User", current_user, "full_name") or ""
			if user_full:
				guard = frappe.db.get_value(
					"Security Guard", {"full_name": user_full}, ["company", "farm"], as_dict=True
				)
				if guard:
					company = guard.company or ""
					farm = guard.farm or ""

		HEAD_BY_SCOPE = (
			"SELECT u.full_name, u.mobile_no, u.phone "
			"FROM `tabUser Permission` up "
			"JOIN `tabHas Role` hr ON hr.parent = up.user AND hr.role = 'Security Head' "
			"JOIN `tabUser` u ON u.name = up.user "
			"WHERE up.allow = %s AND up.for_value = %s LIMIT 1"
		)

		contact_name = ""
		phone = ""

		if farm:
			farm_rows = frappe.db.sql(HEAD_BY_SCOPE, ("Farm", farm), as_dict=True)
			if farm_rows:
				contact_name = farm_rows[0].full_name or ""
				phone = farm_rows[0].mobile_no or farm_rows[0].phone or ""

		if not phone and company:
			company_rows = frappe.db.sql(HEAD_BY_SCOPE, ("Company", company), as_dict=True)
			if company_rows:
				contact_name = company_rows[0].full_name or ""
				phone = company_rows[0].mobile_no or company_rows[0].phone or ""

		source = "company_or_farm_head"

		# A company's own configured fallback, so each company (Kaitet Ltd.,
		# Karen Roses, Westwood Dairies, ...) can have a number without
		# needing a real Security Head assignment just to get one.
		if not phone and company:
			fallback_row = frappe.db.get_value(
				"Security Fallback Contact",
				{"parent": "Security Ops Settings", "company": company},
				["contact_name", "contact_phone"],
				as_dict=True,
			)
			if fallback_row and fallback_row.contact_phone:
				contact_name = fallback_row.contact_name or "Security Operations"
				phone = fallback_row.contact_phone
				source = "company_fallback"

		if not phone:
			return {
				"error": "No Security Head configured for company '"
				+ company
				+ "' and no fallback contact row exists for it in Security Ops Settings "
				"— ask a System Manager to add one."
			}

		return {
			"name": contact_name,
			"phone": phone,
			"company": company,
			"farm": farm,
			"source": source,
		}
	except Exception as e:
		frappe.log_error("get_security_head_contact", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def get_security_ops_settings():
	"""The Security Ops Settings singleton, for Command Center's mobile
	Settings screen.

	Deliberately narrow: only the four scalar thresholds are exposed.
	fallback_contacts / notification_rules / farm_gates / dispatch_sources
	are Desk-only for now (no mobile screen needs them) and are left out.

	Access is strictly Security Head / System Manager by role, with no
	allowlist - matching get_session_info's has_command_center_access
	exactly, since visibility and every write it allows are one gate, not
	two that can drift apart.
	"""
	try:
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (frappe.session.user,)
		)
		roles = [row[0] for row in role_rows if row and row[0]]

		if not ("Security Head" in roles or "System Manager" in roles):
			return {"error": "You do not have access to Security Ops Settings."}

		settings = (
			frappe.db.get_value(
				"Security Ops Settings",
				"Security Ops Settings",
				[
					"nearby_guard_alert_radius_m",
					"nearby_alert_stale_minutes",
					"missed_checkin_minutes",
					"escalation_minutes",
				],
				as_dict=True,
			)
			or {}
		)

		# `or 0` on every read: a blank threshold means "unset", and the app
		# expects a number, not null.
		return {
			"nearby_guard_alert_radius_m": settings.get("nearby_guard_alert_radius_m") or 0,
			"nearby_alert_stale_minutes": settings.get("nearby_alert_stale_minutes") or 0,
			"missed_checkin_minutes": settings.get("missed_checkin_minutes") or 0,
			"escalation_minutes": settings.get("escalation_minutes") or 0,
		}
	except Exception as e:
		frappe.log_error("get_security_ops_settings", str(e))
		return {"error": str(e)}


# =============================================================================
# SECTION 2   VISITORS
# =============================================================================


@frappe.whitelist()
def get_appointment(name=None):
	"""One appointment, flattened, with the host's name and badge details
	joined in.

	LEFT JOINs rather than follow-up get_values so a deleted host Employee
	or a detached Visitor Badge still returns the appointment instead of
	failing - host_name then falls back to the raw custom_meet_with ID.
	"""
	try:
		name = str(name or "").strip()
		if not name:
			return {"error": "name is required"}

		row = frappe.db.sql(
			"""
			SELECT a.name, a.customer_name, a.customer_phone_number,
			       a.customer_email, a.customer_organization, a.custom_meet_with,
			       e.employee_name AS host_name,
			       a.scheduled_time, a.customer_details,
			       a.custom_mode_of_transport,
			       a.custom_vehicles_number_plate, a.custom_vehicles_colour,
			       a.workflow_state, a.status, a.custom_reporting_status,
			       a.custom_check_in_time, a.custom_check_out_time,
			       a.custom_visitor_badge, a.custom_host_received_time,
			       b.badge_number, b.company AS badge_company, b.farm AS badge_farm
			FROM `tabAppointment` a
			LEFT JOIN `tabEmployee` e ON e.name = a.custom_meet_with
			LEFT JOIN `tabVisitor Badge` b ON b.name = a.custom_visitor_badge
			WHERE a.name = %s
			LIMIT 1
			""",
			(name,),
			as_dict=True,
		)
		if not row:
			return {"error": "Appointment " + name + " not found"}

		r = row[0]
		return {
			"name": r.name,
			"customer_name": r.customer_name or "",
			"customer_phone_number": r.customer_phone_number or "",
			"customer_email": r.customer_email or "",
			"customer_organization": r.customer_organization or "",
			"custom_meet_with": r.custom_meet_with or "",
			"host_name": r.host_name or r.custom_meet_with or "",
			"scheduled_time": str(r.scheduled_time) if r.scheduled_time else "",
			"customer_details": r.customer_details or "",
			"custom_mode_of_transport": r.custom_mode_of_transport or "",
			"custom_vehicles_number_plate": r.custom_vehicles_number_plate or "",
			"custom_vehicles_colour": r.custom_vehicles_colour or "",
			"workflow_state": r.workflow_state or "",
			"status": r.status or "",
			"custom_reporting_status": r.custom_reporting_status or "",
			"custom_check_in_time": str(r.custom_check_in_time) if r.custom_check_in_time else "",
			"custom_check_out_time": str(r.custom_check_out_time) if r.custom_check_out_time else "",
			"custom_visitor_badge": r.custom_visitor_badge or "",
			# Deliberately None rather than "" when absent - the app
			# distinguishes "no badge" from "badge number zero".
			"custom_visitor_badge_number": r.badge_number if r.badge_number is not None else None,
			"custom_visitor_badge_company": r.badge_company or "",
			"custom_visitor_badge_farm": r.badge_farm or "",
			"custom_host_received_time": str(r.custom_host_received_time)
			if r.custom_host_received_time
			else "",
		}
	except Exception as e:
		frappe.log_error("get_appointment", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def get_visitor_history(query=None):
	"""Look up a returning visitor by ID number, to pre-fill a walk-in.

	Keyed on custom_id_number ONLY - deliberately not name or phone. Both
	of those can match more than one real person (two visitors named
	"Peter", a shared or reassigned phone), and this result pre-fills AND
	LOCKS a walk-in's identity fields, so a wrong match would silently
	attach a stranger's ID, host and purpose to today's visitor.

	Note the failure shape: {"found": False}, not {"error": ...}. The app
	treats any failure here as "no history", which is the safe default -
	the guard just keys the details in by hand.
	"""
	try:
		query = str(query or "").strip()
		if not query:
			return {"found": False}

		matches = frappe.get_all(
			"Appointment",
			filters=[["custom_check_in_time", "is", "set"], ["custom_id_number", "=", query]],
			fields=[
				"name",
				"customer_name",
				"customer_phone_number",
				"customer_organization",
				"custom_id_number",
				"custom_meet_with",
				"customer_details",
				"custom_mode_of_transport",
				"custom_vehicles_number_plate",
				"custom_vehicles_colour",
				"scheduled_time",
				"custom_check_in_time",
			],
			order_by="custom_check_in_time desc",
			limit_page_length=10,
		)

		if not matches:
			return {"found": False}

		# The most recent visit is the source of truth for name/ID/host/
		# purpose - but not every visitor type collects every field
		# (Customer and Contractor bookings never key in a phone number), so
		# a later phone-less visit must not blank out a phone that genuinely
		# is on file from an earlier one. Backfill each optional field from
		# the nearest match that actually has it, still newest-first.
		m = matches[0]

		def backfill(fieldname):
			for row in matches:
				if row.get(fieldname):
					return row.get(fieldname)
			return None

		return {
			"found": True,
			"visitor_name": m.customer_name,
			"phone_number": m.customer_phone_number or backfill("customer_phone_number"),
			"organization": m.customer_organization or backfill("customer_organization"),
			"id_no": m.custom_id_number,
			"host_id": m.custom_meet_with,
			"host_name": frappe.db.get_value("Employee", m.custom_meet_with, "employee_name")
			if m.custom_meet_with
			else "",
			"purpose": m.customer_details,
			"transport_mode": m.custom_mode_of_transport or backfill("custom_mode_of_transport"),
			"vehicle_reg_no": m.custom_vehicles_number_plate
			or backfill("custom_vehicles_number_plate"),
			"vehicle_color": m.custom_vehicles_colour or backfill("custom_vehicles_colour"),
			"last_visit_date": m.custom_check_in_time or m.scheduled_time,
			# Always "id" - this only ever queries custom_id_number, so a
			# match is always a unique-key match and is safe to lock on.
			"matched_by": "id",
		}
	except Exception as e:
		frappe.log_error("get_visitor_history", str(e))
		return {"found": False}


@frappe.whitelist()
def search_visitor_appointment(query=None):
	"""Find today's appointment for a visitor at the gate.

	Matches on name, phone, appointment ID (LIKE) or exact ID number, but
	only for TODAY - a guard is checking in someone standing in front of
	them, not browsing history.

	`matched_by` is the important part of the response. Name is a partial,
	case-insensitive LIKE and is NOT unique: two visitors can genuinely
	share a name, so a name hit can surface the wrong person's
	appointment. Only an exact ID-number match ("id") or an exact
	appointment-name match ("appointment", e.g. a QR scan) is unambiguous;
	everything else is "other" and the client must never auto-lock identity
	fields on it (see gate.tsx onProceed/onRegisterAsWalkIn).
	"""
	try:
		query = str(query or "").strip()
		if not query:
			return {"error": "query is required"}

		today = frappe.utils.today()
		like = "%" + query + "%"

		rows = frappe.db.sql(
			"""
			SELECT a.name, a.customer_name, a.custom_id_number, a.customer_phone_number,
			       a.customer_email, a.customer_organization, a.custom_meet_with,
			       e.employee_name AS host_name,
			       a.scheduled_time, a.customer_details,
			       a.custom_mode_of_transport,
			       a.custom_vehicles_number_plate, a.custom_vehicles_colour,
			       a.workflow_state, a.status, a.custom_reporting_status
			FROM `tabAppointment` a
			LEFT JOIN `tabEmployee` e ON e.name = a.custom_meet_with
			WHERE DATE(a.scheduled_time) = %s
			  AND (a.customer_name LIKE %s
			       OR a.customer_phone_number LIKE %s
			       OR a.name LIKE %s
			       OR a.custom_id_number = %s)
			ORDER BY a.scheduled_time DESC
			LIMIT 1
			""",
			(today, like, like, like, query),
			as_dict=True,
		)

		if not rows:
			return {"has_appointment": False, "query": query}

		r = rows[0]

		phone = r.customer_phone_number or ""
		transport_mode = r.custom_mode_of_transport or ""
		vehicle_reg_no = r.custom_vehicles_number_plate or ""
		vehicle_color = r.custom_vehicles_colour or ""

		# Same backfill principle as get_visitor_history: today's booking is
		# the source of truth for name/host/purpose/status, but Customer and
		# Contractor bookings never key in phone, transport or vehicle. Fill
		# those from this person's past visits so a guard does not see a
		# blank Phone that is genuinely on file - the richer history lookup
		# only runs when NO appointment exists for today at all.
		#
		# Backfill ONLY against this exact person's ID number, never by name
		# or phone: those can match a different person and would silently
		# attach a stranger's vehicle to this visitor. No ID on today's
		# record means no safe unique key, so skip rather than guess.
		id_no = r.custom_id_number or ""
		if id_no and not (phone and transport_mode and vehicle_reg_no and vehicle_color):
			past = frappe.get_all(
				"Appointment",
				filters=[
					["custom_check_in_time", "is", "set"],
					["name", "!=", r.name],
					["custom_id_number", "=", id_no],
				],
				fields=[
					"customer_phone_number",
					"custom_mode_of_transport",
					"custom_vehicles_number_plate",
					"custom_vehicles_colour",
					"custom_check_in_time",
				],
				order_by="custom_check_in_time desc",
				limit_page_length=10,
			)

			def backfill(fieldname):
				for row in past:
					if row.get(fieldname):
						return row.get(fieldname)
				return ""

			phone = phone or backfill("customer_phone_number")
			transport_mode = transport_mode or backfill("custom_mode_of_transport")
			vehicle_reg_no = vehicle_reg_no or backfill("custom_vehicles_number_plate")
			vehicle_color = vehicle_color or backfill("custom_vehicles_colour")

		if r.custom_id_number and r.custom_id_number == query:
			matched_by = "id"
		elif r.name == query:
			matched_by = "appointment"
		else:
			matched_by = "other"

		return {
			"has_appointment": True,
			"name": r.name,
			"visitor_name": r.customer_name or "",
			"id_no": r.custom_id_number or "",
			"phone_number": phone,
			"organization": r.customer_organization or "",
			"host_id": r.custom_meet_with or "",
			"host_name": r.host_name or r.custom_meet_with or "",
			"scheduled_time": str(r.scheduled_time) if r.scheduled_time else "",
			"purpose": r.customer_details or "",
			# Defaults to On Foot rather than blank - the form needs a value
			# selected, and On Foot is the safe assumption at a gate.
			"transport_mode": transport_mode or "On Foot",
			"vehicle_reg_no": vehicle_reg_no,
			"vehicle_color": vehicle_color,
			"status": r.workflow_state or r.status or "",
			"reporting_status": r.custom_reporting_status or "",
			"matched_by": matched_by,
		}
	except Exception as e:
		frappe.log_error("search_visitor_appointment", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def approved_appointments():
	"""Visitors cleared to enter or already inside, for the gate's main list.

	Ordering matters to the guard: anyone already Checked In sorts above
	those merely Approved, then most recent first within each group. The
	CASE in the ORDER BY is what does that, so don't "simplify" it to a
	plain workflow_state sort.
	"""
	try:
		rows = frappe.db.sql(
			"""
			SELECT a.name, a.customer_name, a.customer_phone_number,
			       a.customer_details, a.scheduled_time, a.workflow_state,
			       a.custom_meet_with,
			       a.custom_check_in_time, a.custom_mode_of_transport,
			       a.custom_vehicles_number_plate, a.custom_vehicles_colour,
			       a.custom_number_of_passengers,
			       a.custom_host_received_time,
			       a.custom_visitor_type,
			       b.badge_number,
			       e.employee_name AS host_name
			FROM `tabAppointment` a
			LEFT JOIN `tabEmployee` e ON e.name = a.custom_meet_with
			LEFT JOIN `tabVisitor Badge` b ON b.name = a.custom_visitor_badge
			WHERE a.workflow_state IN ('Approved by Host', 'Visitor Checked In')
			ORDER BY
			  CASE a.workflow_state
			    WHEN 'Visitor Checked In' THEN 0
			    ELSE 1
			  END,
			  a.custom_check_in_time DESC,
			  a.scheduled_time DESC
			LIMIT 100
			""",
			as_dict=True,
		)
		result = []
		for r in rows:
			host_id = str(r.custom_meet_with) if r.custom_meet_with else ""
			# Passenger count is an Int field but can be NULL; the app wants
			# a number, and a bad value counts as none rather than failing
			# the whole list.
			passengers = 0
			if r.custom_number_of_passengers is not None:
				try:
					passengers = int(r.custom_number_of_passengers)
				except (TypeError, ValueError):
					passengers = 0
			result.append(
				{
					"name": str(r.name) if r.name else "",
					"customer_name": str(r.customer_name) if r.customer_name else "",
					"phone": str(r.customer_phone_number) if r.customer_phone_number else "",
					"purpose": str(r.customer_details) if r.customer_details else "",
					"scheduled_time": str(r.scheduled_time) if r.scheduled_time else "",
					"workflow_state": str(r.workflow_state) if r.workflow_state else "",
					"host_id": host_id,
					"host_name": str(r.host_name) if r.host_name else host_id,
					"check_in_time": str(r.custom_check_in_time) if r.custom_check_in_time else "",
					"transport": str(r.custom_mode_of_transport) if r.custom_mode_of_transport else "",
					"plate": str(r.custom_vehicles_number_plate)
					if r.custom_vehicles_number_plate
					else "",
					"colour": str(r.custom_vehicles_colour) if r.custom_vehicles_colour else "",
					"passengers": passengers,
					# None, not "", when there is no badge - see get_appointment.
					"custom_visitor_badge_number": r.badge_number
					if r.badge_number is not None
					else None,
					"custom_host_received_time": str(r.custom_host_received_time)
					if r.custom_host_received_time
					else "",
					"custom_visitor_type": str(r.custom_visitor_type)
					if r.custom_visitor_type
					else "",
				}
			)
		return result
	except Exception as e:
		frappe.log_error("approved_appointments", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def pending_approvals():
	"""Appointments waiting on their host, for the host's approvals screen.

	LEFT JOIN rather than two queries so a host whose Employee record has
	been deleted still shows the appointment, with the raw ID standing in
	for the name.
	"""
	try:
		rows = frappe.db.sql(
			"""
			SELECT a.name, a.customer_name, a.customer_phone_number,
			       a.customer_details, a.scheduled_time, a.workflow_state,
			       a.custom_meet_with,
			       e.employee_name AS host_name
			FROM `tabAppointment` a
			LEFT JOIN `tabEmployee` e ON e.name = a.custom_meet_with
			WHERE a.workflow_state = 'Pending Host Review'
			ORDER BY a.scheduled_time DESC
			LIMIT 100
			""",
			as_dict=True,
		)
		result = []
		for r in rows:
			host_id = str(r.custom_meet_with) if r.custom_meet_with else ""
			result.append(
				{
					"name": str(r.name) if r.name else "",
					"customer_name": str(r.customer_name) if r.customer_name else "",
					"phone": str(r.customer_phone_number) if r.customer_phone_number else "",
					"purpose": str(r.customer_details) if r.customer_details else "",
					"scheduled_time": str(r.scheduled_time) if r.scheduled_time else "",
					"workflow_state": str(r.workflow_state) if r.workflow_state else "",
					"host_id": host_id,
					"host_name": str(r.host_name) if r.host_name else host_id,
				}
			)
		return result
	except Exception as e:
		frappe.log_error("pending_approvals", str(e))
		return {"error": str(e)}


# =============================================================================
# SECTION 3   CONTRACTORS
# =============================================================================


@frappe.whitelist()
def getContractorContract(query=None):
	"""Look up a contractor by supplier name and report whether they are
	currently cleared to be on site.

	The Supplier's `custom_is_contractor` flag is only their standing
	identity as a contractor org. Whether they may enter TODAY comes from
	having a Contract row (party_type=Supplier) with status=Active. Most
	recent first, so a lapsed contract does not shadow the current one.

	camelCase name because that is the bare path the app already calls;
	renaming it would 404 every handset in the field.

	Note the failure shape: the full "not a contractor" skeleton plus an
	`error` key, never a bare {"error": ...}. The app reads
	`has_active_contract` and `vehicles` unconditionally. frappe.throw on a
	missing query is INSIDE the try, so it soft-fails into that same
	skeleton - preserved exactly as the Server Script had it.
	"""
	EMPTY = {
		"contract_name": None,
		"contractor_name": None,
		"is_contractor": False,
		"has_active_contract": False,
		"supplier_id": None,
		"vehicles": [],
	}
	try:
		query = str(query or "")
		if not query:
			frappe.throw("Search query is required")

		q = query.strip()

		suppliers = frappe.get_all(
			"Supplier",
			filters={
				"disabled": 0,
				"custom_is_contractor": 1,
				"supplier_name": ["like", "%" + q + "%"],
			},
			fields=["name", "supplier_name", "supplier_group", "mobile_no", "email_id"],
			limit=5,
			order_by="supplier_name asc",
		)

		if not suppliers:
			return dict(EMPTY)

		s = suppliers[0]

		contracts = frappe.get_all(
			"Contract",
			filters={"party_type": "Supplier", "party_name": s["name"]},
			fields=[
				"name",
				"status",
				"fulfilment_status",
				"start_date",
				"end_date",
				"document_type",
				"document_name",
			],
			order_by="creation desc",
			limit=10,
		)

		active_contract = None
		for c in contracts:
			if c.get("status") == "Active":
				active_contract = c
				break

		# Falls back to the latest contract for display even when none is
		# Active, so the guard can see WHY entry is refused (expired on
		# <date>) rather than just "no contract".
		contract = active_contract or (contracts[0] if contracts else None)

		project = None
		if contract and contract.get("document_type") == "Project" and contract.get("document_name"):
			proj = frappe.get_all(
				"Project",
				filters={"name": contract["document_name"]},
				fields=["name", "project_name", "status", "is_active", "expected_end_date"],
				limit=1,
			)
			if proj:
				project = proj[0]

		# Registered vehicles from the Supplier's own child table. Wrapped
		# separately because a site without the custom_registered_vehicles
		# field should still return the contract, just with no vehicles.
		vehicles = []
		try:
			rows = frappe.get_all(
				"Supplier Vehicle",
				filters={"parent": s["name"], "parentfield": "custom_registered_vehicles"},
				fields=["number_plate", "colour", "vehicle_type", "is_active"],
				order_by="idx asc",
			)
			vehicles = [
				{
					"number_plate": r["number_plate"],
					"colour": r.get("colour") or "",
					"vehicle_type": r.get("vehicle_type") or "",
				}
				for r in rows
				if r.get("number_plate")
			]
		except Exception:
			pass

		return {
			"contract_name": contract["name"] if contract else None,
			"contractor_name": s["supplier_name"],
			"supplier_id": s["name"],
			"supplier_group": s.get("supplier_group"),
			"is_contractor": True,
			"has_active_contract": bool(active_contract),
			"contract_status": contract["status"] if contract else None,
			"fulfilment_status": contract.get("fulfilment_status") if contract else None,
			"contract_start": str(contract["start_date"])
			if contract and contract.get("start_date")
			else None,
			"contract_end": str(contract["end_date"])
			if contract and contract.get("end_date")
			else None,
			"project": {
				"name": project["name"],
				"project_name": project.get("project_name") or project["name"],
				"status": project.get("status"),
				"is_active": project.get("is_active"),
				"expected_end_date": str(project["expected_end_date"])
				if project.get("expected_end_date")
				else None,
			}
			if project
			else None,
			"contact_phone": s.get("mobile_no") or "",
			"vehicles": vehicles,
		}

	except Exception as e:
		# Title-only log_error, as the original had it.
		frappe.log_error("Contractor Contract Search Error")
		out = dict(EMPTY)
		out["error"] = str(e)
		return out


@frappe.whitelist()
def contractor_gate_checkout():
	"""Check a contractor out at the gate.

	RAISES rather than returning {"error": ...}, unlike everything else in
	this file. That is the Server Script's behaviour preserved exactly: the
	installed app already handles the HTTP error this produces, and
	converting it to a soft failure would silently change what a guard sees
	in the field. `frappe.throw` yields 417, which `lib/api/client.ts`
	surfaces as an error rather than treating as a dead session, so it does
	not log anyone out.

	Reads `appointment_name` off form_dict rather than taking it as a
	parameter, so a missing key throws the same message it always did.
	"""
	appt_name = (frappe.form_dict.get("appointment_name") or "").strip()
	if not appt_name:
		frappe.throw("appointment_name is required")

	if frappe.db.get_single_value("Security Ops Settings", "feature_contractor_checkin") == 0:
		frappe.throw("This feature is not enabled on this instance.")

	try:
		now_str = frappe.utils.now()

		# Try the workflow action but do not fail if the current state does
		# not allow it - the fields below are the source of truth.
		try:
			from frappe.model.workflow import apply_workflow

			doc = frappe.get_doc("Appointment", appt_name)
			apply_workflow(doc, "Confirm Check Out")
		except Exception:
			pass

		# Always write checkout fields via set_value (bypasses link validation)
		frappe.db.set_value(
			"Appointment",
			appt_name,
			{"custom_check_out_time": now_str, "custom_reporting_status": "Checked out"},
			update_modified=True,
		)

		# Release any Supplier Badge issued for this visit back into the pool
		# - same mechanic as check_out_visitor releasing a Visitor Badge,
		# deliberately overriding Supplier Badge's older "stays with one
		# supplier long-term" design (see supplier_badge_qr.py) so a badge is
		# reusable across suppliers rather than permanently assigned.
		badge_name = frappe.db.get_value("Appointment", appt_name, "custom_supplier_badge")
		if badge_name:
			frappe.db.set_value(
				"Supplier Badge",
				badge_name,
				{"status": "Available", "current_appointment": None, "supplier": None},
			)

		frappe.db.commit()

		return {"success": True, "appointment": appt_name, "check_out_time": now_str}

	except Exception as e:
		frappe.log_error(
			title="Contractor Gate Checkout Error",
			message="User: "
			+ frappe.session.user
			+ "\nAppointment: "
			+ appt_name
			+ "\nError: "
			+ str(e),
		)
		frappe.throw("Contractor check-out failed: " + str(e))


# =============================================================================
# SECTION 4   BADGES
# =============================================================================


@frappe.whitelist()
def list_supplier_badges(status=None, company=None, limit=None):
	"""Supplier Badge rows for Command Center's badge management screen.

	All filters optional. Access is System Manager or Security Head only -
	this is a management surface, same gate as issuing a badge.
	"""
	try:
		allowed_roles = ("System Manager", "Security Head")
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (frappe.session.user,)
		)
		caller_roles = [row[0] for row in role_rows if row and row[0]]
		if not any(r in caller_roles for r in allowed_roles):
			return {"error": "Only System Manager or Security Head can list supplier badges."}

		status = str(status).strip() if status is not None else ""
		company = str(company).strip() if company is not None else ""

		row_limit = 200
		if limit:
			try:
				row_limit = int(limit)
			except (TypeError, ValueError):
				row_limit = 200
		row_limit = max(1, min(row_limit, 1000))

		where_parts = ["1=1"]
		params = {"row_limit": row_limit}
		if status:
			where_parts.append("status = %(status)s")
			params["status"] = status
		if company:
			where_parts.append("company = %(company)s")
			params["company"] = company

		rows = frappe.db.sql(
			"SELECT name, badge_number, company, supplier, status, qr_image, creation "
			"FROM `tabSupplier Badge` "
			"WHERE " + " AND ".join(where_parts) + " "
			"ORDER BY creation DESC "
			"LIMIT %(row_limit)s",
			params,
			as_dict=True,
		)
		out = []
		for r in rows:
			# Resolved per row rather than joined: Supplier is a link that may
			# dangle, and the original fell back to the raw ID in that case.
			supplier_name = ""
			if r.supplier:
				supplier_name = frappe.db.get_value("Supplier", r.supplier, "supplier_name") or r.supplier
			out.append(
				{
					"name": r.name,
					"badge_number": r.badge_number,
					"company": r.company or "",
					"supplier": r.supplier or "",
					"supplier_name": supplier_name,
					"status": r.status or "",
					"qr_image": r.qr_image or "",
					"creation": str(r.creation) if r.creation else "",
				}
			)
		return out
	except Exception as e:
		frappe.log_error("list_supplier_badges", str(e))
		return {"error": str(e)}


# =============================================================================
# SECTION 5   STAFF GATE
# =============================================================================


@frappe.whitelist()
def get_today_attendance(employee=None):
	"""Today's most recent submitted Attendance row for one employee, used
	by the Staff panel to decide between CHECK IN and CHECK OUT.

	`frappe.get_all` (not get_list) is deliberate and pre-existing. This
	replaced a raw /api/resource/Attendance call, and Attendance's DocPerm
	grants read only to System Manager / HR User / HR Manager / Employee -
	none of which an external Gate Guard without an HR-linked Employee
	record ever holds. That raw call 403'd for exactly those users the
	moment they picked a staff match, and the app's axios interceptor
	treats a 403 as a dead session, so it looked like a forced logout for
	what was really a missing read permission on one doctype.

	Falls back to Staff Gate Movement: a company on "Movement Log Only"
	never creates an Attendance row, but the panel still needs to know the
	person is on site so it can offer CHECK OUT.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_staff_checkin") == 0:
			raise Exception("This feature is not enabled on this instance.")

		employee = str(employee or "").strip()
		if not employee:
			return {"error": "employee is required"}

		today = frappe.utils.today()
		rows = frappe.get_all(
			"Attendance",
			filters=[
				["employee", "=", employee],
				["attendance_date", "=", today],
				["docstatus", "=", 1],
			],
			fields=[
				"name",
				"employee",
				"in_time",
				"out_time",
				"status",
				"attendance_date",
				"custom_temp_exit_time",
			],
			order_by="creation desc",
			limit_page_length=1,
		)
		found = rows[0] if rows else None

		if not found:
			mv = frappe.get_all(
				"Staff Gate Movement",
				filters=[["employee", "=", employee], ["movement_date", "=", today]],
				fields=["name", "employee", "time_in", "time_out", "movement_date"],
				order_by="creation desc",
				limit_page_length=1,
			)
			if mv:
				m = mv[0]
				# time_in/time_out are clock times on a dated row, so they
				# only become timestamps paired with movement_date.
				found = {
					"name": m["name"],
					"employee": m["employee"],
					"in_time": str(m["movement_date"]) + " " + str(m["time_in"])
					if m["time_in"]
					else None,
					"out_time": str(m["movement_date"]) + " " + str(m["time_out"])
					if m["time_out"]
					else None,
					"status": "Movement",
					"attendance_date": m["movement_date"],
					"custom_temp_exit_time": None,
				}

		return {"attendance": found}
	except Exception as e:
		frappe.log_error("get_today_attendance", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def list_checked_in_staff():
	"""Everyone currently on site, scoped to what the caller may see.

	This is the one endpoint in this file that DOES scope by company/farm,
	and it does so by hand rather than through User Permissions, because
	`frappe.get_all` ignores those entirely. The rules:

	  System Manager   -> everything
	  Security Head    -> their own Company/Farm User Permission rows
	  everyone else    -> their Employee's company/farm, or failing that
	                      their Security Guard record's

	A caller with no resolvable company or farm gets `name = __no_match__`,
	which returns nothing. That is deliberate: falling through to "no
	filter" would quietly show every company's staff to someone the system
	could not place.

	Note the error shape: {"staff": [], "error": ...}. The app reads
	`staff` unconditionally.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_staff_checkin") == 0:
			raise Exception("This feature is not enabled on this instance.")
		today = frappe.utils.today()

		current_user = frappe.session.user
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (current_user,)
		)
		roles = [row[0] for row in role_rows if row and row[0]]

		is_system_manager = "System Manager" in roles
		is_security_head = "Security Head" in roles

		scope_companies = []
		scope_farms = []

		if not is_system_manager:
			if is_security_head:
				perm_rows = frappe.db.sql(
					"SELECT allow, for_value FROM `tabUser Permission` "
					"WHERE user = %s AND allow IN ('Company', 'Farm')",
					(current_user,),
					as_dict=True,
				)
				for p in perm_rows:
					if p.allow == "Company" and p.for_value:
						scope_companies.append(p.for_value)
					elif p.allow == "Farm" and p.for_value:
						scope_farms.append(p.for_value)
			else:
				employee = frappe.db.get_value(
					"Employee", {"user_id": current_user}, ["company", "custom_farm"], as_dict=True
				)
				if employee:
					if employee.company:
						scope_companies.append(employee.company)
					if employee.custom_farm:
						scope_farms.append(employee.custom_farm)
				else:
					user_full = frappe.db.get_value("User", current_user, "full_name") or ""
					if user_full:
						guard = frappe.db.get_value(
							"Security Guard", {"full_name": user_full}, ["company", "farm"], as_dict=True
						)
						if guard:
							if guard.company:
								scope_companies.append(guard.company)
							if guard.farm:
								scope_farms.append(guard.farm)

		def _scoped(base, company_field, farm_field):
			"""Company wins over farm when both resolve - same precedence the
			original used for both queries."""
			if is_system_manager:
				return base
			if scope_companies:
				return base + [[company_field, "in", scope_companies]]
			if scope_farms:
				return base + [[farm_field, "in", scope_farms]]
			return base + [["name", "=", "__no_match__"]]

		rows = frappe.get_all(
			"Attendance",
			filters=_scoped(
				[
					["attendance_date", "=", today],
					["custom_gate_app_entry", "=", 1],
					["out_time", "is", "not set"],
					["docstatus", "<", 2],
				],
				"company",
				"custom_farm",
			),
			fields=[
				"name",
				"employee",
				"employee_name",
				"department",
				"in_time",
				"custom_temp_exit_time",
				"docstatus",
			],
			order_by="in_time desc",
		)

		# Companies on "Movement Log Only" never create an Attendance row, so
		# their people would be missing from the on-site list entirely. Same
		# scoping, mapped onto the shape the client already reads.
		mv_rows = frappe.get_all(
			"Staff Gate Movement",
			filters=_scoped(
				[["movement_date", "=", today], ["time_out", "is", "not set"]], "company", "farm"
			),
			fields=["name", "employee", "employee_name", "movement_date", "time_in"],
			order_by="time_in desc",
		)
		for m in mv_rows:
			rows.append(
				{
					"name": m["name"],
					"employee": m["employee"],
					"employee_name": m["employee_name"],
					"department": "",
					"in_time": str(m["movement_date"]) + " " + str(m["time_in"])
					if m["time_in"]
					else None,
					"custom_temp_exit_time": None,
					"docstatus": 1,
				}
			)

		return {"staff": rows}
	except Exception as e:
		frappe.log_error("list_checked_in_staff", str(e))
		return {"staff": [], "error": str(e)}


@frappe.whitelist()
def list_today_staff_attendance():
	"""Every submitted Attendance row for today plus today's Staff Gate
	Movements, for the Summary tab's staff section.

	`frappe.get_all` (not get_list) is deliberate and pre-existing: this
	replaced a raw /api/resource/Attendance call from the client, which 403s
	for a Gate Guard without HR-linked Attendance read access. It is
	therefore unscoped - every company, every farm - exactly as the REST
	call was. That is a known gap, not something this migration changes.

	Note the error shape: {"attendance": [], "error": ...}, not the bare
	{"error": ...} the rest of this file uses. The app reads `attendance`
	unconditionally, so the key has to be present even on failure.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_staff_checkin") == 0:
			raise Exception("This feature is not enabled on this instance.")
		today = frappe.utils.today()
		rows = frappe.get_all(
			"Attendance",
			filters=[["attendance_date", "=", today], ["docstatus", "=", 1]],
			fields=[
				"name",
				"employee",
				"employee_name",
				"department",
				"in_time",
				"out_time",
				"custom_temp_exit_time",
			],
			order_by="in_time desc",
			limit_page_length=200,
		)
		mv_rows = frappe.get_all(
			"Staff Gate Movement",
			filters=[["movement_date", "=", today]],
			fields=["name", "employee", "employee_name", "movement_date", "time_in", "time_out"],
			order_by="time_in desc",
			limit_page_length=200,
		)
		for m in mv_rows:
			# time_in/time_out are clock times on a dated row, so they only
			# become timestamps when paired with movement_date.
			in_stamp = str(m["movement_date"]) + " " + str(m["time_in"]) if m["time_in"] else None
			out_stamp = str(m["movement_date"]) + " " + str(m["time_out"]) if m["time_out"] else None
			rows.append(
				{
					"name": m["name"],
					"employee": m["employee"],
					"employee_name": m["employee_name"],
					"department": "",
					"in_time": in_stamp,
					"out_time": out_stamp,
					"custom_temp_exit_time": None,
				}
			)

		return {"attendance": rows}
	except Exception as e:
		frappe.log_error("list_today_staff_attendance", str(e))
		return {"attendance": [], "error": str(e)}


# =============================================================================
# SECTION 7   INCIDENTS
# =============================================================================


@frappe.whitelist()
def list_incident_categories():
	"""Categories for the mobile incident-report form's picker.

	Sources Incident Category, NOT Incident Report's own
	`nature_of_incident` Select - the two have drifted apart and the Select
	is what a saved incident is actually validated against. Preserved as-is:
	this is a straight port, not the place to fix that.
	"""
	try:
		rows = frappe.get_all(
			"Incident Category",
			fields=["name"],
			order_by="name asc",
			limit_page_length=100,
		)
		return [{"name": r.name} for r in rows]
	except Exception as e:
		frappe.log_error("list_incident_categories", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def list_incidents(from_date=None, to_date=None, limit=None):
	"""Incident Reports for the dashboard, optionally within a date range.

	Scoping is indirect: Incident Report carries no company or farm field,
	so the scope is inferred from whoever reported it, by joining Employee
	on user_id = reported_by. System Manager sees everything; a Security
	Head sees what their User Permissions grant; anyone else sees their own
	company/farm.

	A caller with no resolvable company or farm gets `1=0` - nothing -
	rather than falling through to every incident on the instance.

	Unlike list_checked_in_staff, company and farm are OR'd here rather
	than company-wins: an incident reported by someone at your farm should
	appear even if their company differs. Both match their originals.
	"""
	try:
		row_limit = 200
		if limit:
			try:
				row_limit = int(limit)
			except (TypeError, ValueError):
				row_limit = 200
		row_limit = max(1, min(row_limit, 1000))

		from_date = from_date or ""
		to_date = to_date or ""

		current_user = frappe.session.user
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (current_user,)
		)
		roles = [row[0] for row in role_rows if row and row[0]]

		is_system_manager = "System Manager" in roles
		is_security_head = "Security Head" in roles

		scope_companies = []
		scope_farms = []

		if not is_system_manager:
			if is_security_head:
				perm_rows = frappe.db.sql(
					"SELECT allow, for_value FROM `tabUser Permission` "
					"WHERE user = %s AND allow IN ('Company', 'Farm')",
					(current_user,),
					as_dict=True,
				)
				for p in perm_rows:
					if p.allow == "Company" and p.for_value:
						scope_companies.append(p.for_value)
					elif p.allow == "Farm" and p.for_value:
						scope_farms.append(p.for_value)
			else:
				employee = frappe.db.get_value(
					"Employee", {"user_id": current_user}, ["company", "custom_farm"], as_dict=True
				)
				if employee:
					if employee.company:
						scope_companies.append(employee.company)
					if employee.custom_farm:
						scope_farms.append(employee.custom_farm)
				else:
					user_full = frappe.db.get_value("User", current_user, "full_name") or ""
					if user_full:
						guard = frappe.db.get_value(
							"Security Guard", {"full_name": user_full}, ["company", "farm"], as_dict=True
						)
						if guard:
							if guard.company:
								scope_companies.append(guard.company)
							if guard.farm:
								scope_farms.append(guard.farm)

		where_parts = ["1=1"]
		params = {"row_limit": row_limit}
		if from_date:
			where_parts.append("DATE(i.incident_datetime) >= %(from_date)s")
			params["from_date"] = from_date
		if to_date:
			where_parts.append("DATE(i.incident_datetime) <= %(to_date)s")
			params["to_date"] = to_date

		if not is_system_manager:
			# Placeholders are generated, values are still bound - the IN
			# list length varies, the content never reaches the SQL text.
			conditions = []
			for idx, value in enumerate(scope_companies):
				params["c" + str(idx)] = value
			if scope_companies:
				conditions.append(
					"e.company IN ("
					+ ", ".join("%(c" + str(i) + ")s" for i in range(len(scope_companies)))
					+ ")"
				)
			for idx, value in enumerate(scope_farms):
				params["f" + str(idx)] = value
			if scope_farms:
				conditions.append(
					"e.custom_farm IN ("
					+ ", ".join("%(f" + str(i) + ")s" for i in range(len(scope_farms)))
					+ ")"
				)
			where_parts.append("(" + " OR ".join(conditions) + ")" if conditions else "1=0")

		rows = frappe.db.sql(
			"SELECT i.name, i.incident_datetime, i.location, i.nature_of_incident, i.severity, "
			"i.description, i.status, i.reported_datetime, i.reported_by "
			"FROM `tabIncident Report` i "
			"LEFT JOIN `tabEmployee` e ON e.user_id = i.reported_by "
			"WHERE " + " AND ".join(where_parts) + " "
			"ORDER BY i.incident_datetime DESC "
			"LIMIT %(row_limit)s",
			params,
			as_dict=True,
		)
		return [
			{
				"name": r.name,
				"incident_datetime": str(r.incident_datetime) if r.incident_datetime else "",
				"location": r.location or "",
				"nature_of_incident": r.nature_of_incident or "",
				"severity": r.severity or "",
				"description": r.description or "",
				"status": r.status or "",
				"reported_datetime": str(r.reported_datetime) if r.reported_datetime else "",
				"reported_by": r.reported_by or "",
			}
			for r in rows
		]
	except Exception as e:
		frappe.log_error("list_incidents", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def my_incidents():
	"""The 50 most recent incidents reported by the calling user."""
	try:
		rows = frappe.db.sql(
			"""
			SELECT name, incident_datetime, location, nature_of_incident, severity,
			       description, status, reported_datetime
			FROM `tabIncident Report`
			WHERE reported_by = %s
			ORDER BY incident_datetime DESC
			LIMIT 50
			""",
			(frappe.session.user,),
			as_dict=True,
		)
		return [
			{
				"name": r.name,
				"incident_datetime": str(r.incident_datetime) if r.incident_datetime else "",
				"location": r.location or "",
				"nature_of_incident": r.nature_of_incident or "",
				"severity": r.severity or "",
				"description": r.description or "",
				"status": r.status or "",
				"reported_datetime": str(r.reported_datetime) if r.reported_datetime else "",
			}
			for r in rows
		]
	except Exception as e:
		frappe.log_error("my_incidents", str(e))
		return {"error": str(e)}


# =============================================================================
# SECTION 8   SHIFTS
# =============================================================================


@frappe.whitelist()
def check_in_shift():
	"""Mobile shift check-in, for External (contractor) guards only.

	Internal (Employee) guards have Attendance records that already carry a
	check-in signal; External guards have no Employee record at all, so
	there is no Attendance path for them - this is the substitute.

	Writes only `checked_in`, never `status`: status stays purely
	clock-derived by security_guard_shift_assignment.py's controller and the
	hourly refresh_shift_statuses job. Uses frappe.db.set_value rather than
	doc.save() to avoid re-running validate() - including its overlap check
	- for a field that has nothing to do with scheduling.
	"""
	try:
		current_user = frappe.session.user

		external_guard = None
		is_internal = False

		emp = frappe.db.get_value("Employee", {"user_id": current_user}, "name")
		if emp:
			is_internal = True
		else:
			# External guards have no User of their own; the app signs in as
			# a shared gate account, so fall back to matching on full name.
			user_full = frappe.db.get_value("User", current_user, "full_name") or ""
			if user_full:
				external_guard = frappe.db.get_value("Security Guard", {"full_name": user_full}, "name")

		if is_internal:
			return {"error": "Employee guards check in via attendance, not the app"}
		if not external_guard:
			return {"error": "Could not resolve your guard identity"}

		shift_name = frappe.db.get_value(
			"Security Guard Shift Assignment",
			{"external_guard": external_guard, "status": ["in", ["Scheduled", "Active"]]},
			"name",
		)
		if not shift_name:
			return {"error": "No scheduled or active shift found to check in to"}

		frappe.db.set_value(
			"Security Guard Shift Assignment", shift_name, "checked_in", 1, update_modified=True
		)
		frappe.db.commit()
		return {"name": shift_name, "checked_in": 1}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("check_in_shift", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def my_current_shift():
	"""The calling guard's own shift: the Active one if there is one, else
	the nearest upcoming Scheduled one, else none.

	Read-only. Creation stays in Desk, where Security Head / System Manager
	/ HR User already have full CRUD through native doctype permissions.

	guard_type and checked_in are surfaced so the app can decide whether to
	offer the "check in to shift" action - that is only meaningful for
	External (contractor) guards, who have no Employee or Attendance record
	to check in against. An Internal guard's checked_in stays governed by
	whatever ties it to Attendance, untouched here.
	"""
	try:
		current_user = frappe.session.user

		internal_guard = None
		external_guard = None
		guard_type = None

		emp = frappe.db.get_value("Employee", {"user_id": current_user}, "name")
		if emp:
			internal_guard = emp
			guard_type = "Internal"
		else:
			# External guards have no User of their own; the app signs in as
			# a shared gate account, so fall back to matching on full name.
			user_full = frappe.db.get_value("User", current_user, "full_name") or ""
			if user_full:
				guard_name = frappe.db.get_value("Security Guard", {"full_name": user_full}, "name")
				if guard_name:
					external_guard = guard_name
					guard_type = "External"

		if not internal_guard and not external_guard:
			# No guard_type key at all here, matching the original - the app
			# treats a missing guard_type as "could not identify you".
			return {"shift": None}

		# Four queries written out in full rather than one with the guard
		# column and sort direction interpolated in. Both would come from a
		# fixed pair, so formatting would be safe today - but SQL assembled
		# by string formatting invites the next edit to splice in something
		# that isn't. The duplication is the cheaper of the two costs.
		ACTIVE_INTERNAL = """
			SELECT name, farm, shift_type, start_date, end_date, status, checked_in
			FROM `tabSecurity Guard Shift Assignment`
			WHERE internal_guard = %s AND status = 'Active'
			ORDER BY start_date DESC LIMIT 1
		"""
		ACTIVE_EXTERNAL = """
			SELECT name, farm, shift_type, start_date, end_date, status, checked_in
			FROM `tabSecurity Guard Shift Assignment`
			WHERE external_guard = %s AND status = 'Active'
			ORDER BY start_date DESC LIMIT 1
		"""
		NEXT_INTERNAL = """
			SELECT name, farm, shift_type, start_date, end_date, status, checked_in
			FROM `tabSecurity Guard Shift Assignment`
			WHERE internal_guard = %s AND status = 'Scheduled'
			ORDER BY start_date ASC LIMIT 1
		"""
		NEXT_EXTERNAL = """
			SELECT name, farm, shift_type, start_date, end_date, status, checked_in
			FROM `tabSecurity Guard Shift Assignment`
			WHERE external_guard = %s AND status = 'Scheduled'
			ORDER BY start_date ASC LIMIT 1
		"""

		guard_value = internal_guard or external_guard

		# Active first, newest; then the soonest upcoming Scheduled one.
		rows = frappe.db.sql(
			ACTIVE_INTERNAL if internal_guard else ACTIVE_EXTERNAL, (guard_value,), as_dict=True
		)
		chosen = rows[0] if rows else None
		if not chosen:
			rows2 = frappe.db.sql(
				NEXT_INTERNAL if internal_guard else NEXT_EXTERNAL, (guard_value,), as_dict=True
			)
			chosen = rows2[0] if rows2 else None

		if not chosen:
			return {"shift": None, "guard_type": guard_type}

		return {
			"shift": {
				"name": chosen["name"],
				"farm": chosen["farm"],
				"shift_type": chosen["shift_type"],
				"start_date": str(chosen["start_date"]),
				"end_date": str(chosen["end_date"]),
				"status": chosen["status"],
				"guard_type": guard_type,
				"checked_in": 1 if chosen["checked_in"] else 0,
			}
		}
	except Exception as e:
		frappe.log_error("my_current_shift", str(e))
		return {"error": str(e)}


# =============================================================================
# SECTION 9   ASSETS
# =============================================================================


@frappe.whitelist()
def my_assets_at_farm():
	"""Known Security Assets at the calling guard's own farm, most recently
	seen first - feeds the "report missing" picker.

	Resolves the farm from the guard's Employee record, falling back to a
	Security Guard matched on full name for external guards, who have no
	Employee record.
	"""
	try:
		current_user = frappe.session.user

		resolved_farm = frappe.db.get_value("Employee", {"user_id": current_user}, "custom_farm")
		if not resolved_farm:
			user_full = frappe.db.get_value("User", current_user, "full_name") or ""
			guard_name = None
			if user_full:
				guard_name = frappe.db.get_value("Security Guard", {"full_name": user_full}, "name")
			if guard_name:
				resolved_farm = frappe.db.get_value("Security Guard", guard_name, "farm")

		if not resolved_farm:
			return {"assets": []}

		rows = frappe.db.sql(
			"""
			SELECT asset_code, asset_name, category, last_status, last_seen_at,
			       last_missing_reported_at
			FROM `tabSecurity Asset`
			WHERE farm = %s
			ORDER BY COALESCE(last_seen_at, '1970-01-01') DESC
			LIMIT 200
			""",
			(resolved_farm,),
			as_dict=True,
		)
		return {
			"assets": [
				{
					"asset_code": r["asset_code"],
					"asset_name": r["asset_name"],
					"category": r["category"],
					"last_status": r["last_status"],
					"last_seen_at": str(r["last_seen_at"]) if r["last_seen_at"] else None,
					"last_missing_reported_at": str(r["last_missing_reported_at"])
					if r["last_missing_reported_at"]
					else None,
				}
				for r in rows
			]
		}
	except Exception as e:
		frappe.log_error("my_assets_at_farm", str(e))
		return {"error": str(e)}


# =============================================================================
# SECTION 10   VEHICLE STICKERS
# =============================================================================


@frappe.whitelist()
def list_sticker_requests(status=None, limit=None):
	"""The sticker review queue that feeds approve/reject_staff_sticker_request.

	`status` defaults to "Pending" - the working set a review screen needs
	most. Pass an explicit empty string to get every status. Access is
	System Manager or Security Head only, the same gate as approving.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_vehicle_stickers") == 0:
			raise Exception("This feature is not enabled on this instance.")

		allowed_roles = ("System Manager", "Security Head")
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (frappe.session.user,)
		)
		caller_roles = [row[0] for row in role_rows if row and row[0]]
		if not any(r in caller_roles for r in allowed_roles):
			return {"error": "Only System Manager or Security Head can list sticker requests."}

		# Note the asymmetry with list_supplier_badges: an omitted status
		# means "Pending" here, but "any" there. Both match their originals.
		status = str(status).strip() if status is not None else "Pending"

		row_limit = 200
		if limit:
			try:
				row_limit = int(limit)
			except (TypeError, ValueError):
				row_limit = 200
		row_limit = max(1, min(row_limit, 1000))

		where_parts = ["1=1"]
		params = {"row_limit": row_limit}
		if status:
			where_parts.append("status = %(status)s")
			params["status"] = status

		rows = frappe.db.sql(
			"SELECT name, employee, employee_name, vehicle_type, plate_number, color, "
			"collection_farm, collection_point, status, review_notes, linked_sticker, creation "
			"FROM `tabStaff Vehicle Sticker Request` "
			"WHERE " + " AND ".join(where_parts) + " "
			"ORDER BY creation DESC "
			"LIMIT %(row_limit)s",
			params,
			as_dict=True,
		)
		return [
			{
				"name": r.name,
				"employee": r.employee or "",
				"employee_name": r.employee_name or "",
				"vehicle_type": r.vehicle_type or "",
				"plate_number": r.plate_number or "",
				"color": r.color or "",
				"collection_farm": r.collection_farm or "",
				"collection_point": r.collection_point or "",
				"status": r.status or "",
				"review_notes": r.review_notes or "",
				"linked_sticker": r.linked_sticker or "",
				"creation": str(r.creation) if r.creation else "",
			}
			for r in rows
		]
	except Exception as e:
		frappe.log_error("list_sticker_requests", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def reject_staff_sticker_request(request_name=None, review_notes=None):
	"""Reject a pending staff vehicle sticker request.

	Role check is done here rather than via DocPerm because the caller is a
	gate account whose doctype permissions are broader than who should be
	allowed to approve or reject; see approve_staff_sticker_request for the
	matching rule.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_vehicle_stickers") == 0:
			raise Exception("This feature is not enabled on this instance.")

		allowed_roles = ("System Manager", "Security Head")
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (frappe.session.user,)
		)
		caller_roles = [row[0] for row in role_rows if row and row[0]]
		if not any(r in caller_roles for r in allowed_roles):
			return {"error": "Only System Manager or Security Head can reject a sticker request."}

		request_name = str(request_name or "").strip()
		review_notes = str(review_notes or "").strip()

		if not request_name:
			return {"error": "request_name is required."}

		req = frappe.db.get_value(
			"Staff Vehicle Sticker Request", request_name, ["name", "status"], as_dict=True
		)
		if not req:
			return {"error": "Request " + request_name + " not found."}
		if req.status != "Pending":
			return {"error": "This request is already " + str(req.status) + "."}

		update = {"status": "Rejected"}
		if review_notes:
			update["review_notes"] = review_notes
		frappe.db.set_value("Staff Vehicle Sticker Request", request_name, update)
		frappe.db.commit()
		return {"success": True, "request": request_name}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("reject_staff_sticker_request", str(e))
		return {"error": str(e)}
