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
    SECTION 12  LEGACY VEHICLE TICKETS

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

import urllib.parse

import frappe

from upande_security.api import watchlist
from upande_security.api.security_alerts import log_unauthorized_access


def _s(value):
	"""Original `s(key)`: None -> "", anything else -> str(value).strip()."""
	if value is None:
		return ""
	return str(value).strip()
def _normalise_ke_phone(raw):
	"""Digits-only, Kenyan country code (254) prefixed. Returns "" if no digits.

	0712... -> 254712...; 254712... stays; anything else gets 254 prepended.
	"""
	digits = ""
	for ch in (raw or ""):
		if ch.isdigit():
			digits = digits + ch
	if not digits:
		return ""
	if digits[0] == "0":
		return "254" + digits[1:]
	if digits[0:3] != "254":
		return "254" + digits
	return digits
def _guard_scope():
	"""(company, farm) of the guard making this call.

	Employee is tried first; each missing half is then independently
	backfilled from the Security Guard record matched on User.full_name. The
	two halves are backfilled independently on purpose: most guards' Employee
	has company but a blank custom_farm, and an earlier "only if BOTH missing"
	condition left custom_farmunit unstamped on ~95% of real check-ins. These
	two fields are what daily_summary / list_incidents access scoping filters
	on, so a blank here silently hides the visit from its Security Head.
	"""
	current_user = frappe.session.user
	from upande_security.api.gate_movement import guard_post

	employee = frappe.db.get_value(
		"Employee", {"user_id": current_user}, ["company", "custom_farm"], as_dict=True
	)
	resolved_company = employee.company if employee else None
	# Today's roster shift beats the static farm - guards move between farms.
	resolved_farm = guard_post(current_user)[0] or (employee.custom_farm if employee else None)
	if not resolved_company or not resolved_farm:
		user_full = frappe.db.get_value("User", current_user, "full_name") or ""
		if user_full:
			guard = frappe.db.get_value(
				"Security Guard", {"full_name": user_full}, ["company", "farm"], as_dict=True
			)
			if guard:
				if not resolved_company:
					resolved_company = guard.company
				if not resolved_farm:
					resolved_farm = guard.farm
	if not resolved_farm:
		# A login linked to no farm: the farm the guard chose in the app.
		from upande_security.api.gate_movement import requested_farm

		resolved_farm = requested_farm()
		if resolved_farm and not resolved_company and frappe.get_meta("Farm").has_field("company"):
			resolved_company = frappe.db.get_value("Farm", resolved_farm, "company")
	return resolved_company, resolved_farm
def _form_has(key):
	"""True if the client sent `key` at all (even as null/"").

	Frappe merges a JSON body into form_dict, so this sees both transports.
	Needed because a whitelisted parameter defaulting to None cannot tell
	"absent" from "explicit null".
	"""
	return key in frappe.local.form_dict
def _sp_lookup(container, key):
	"""Bracket lookup that yields None on a missing key or non-subscriptable container.

	The sandboxed originals could not use `.get()` (it was intercepted as a key
	lookup), so every read was `try: x[key] except (KeyError, TypeError)`. This
	keeps those exact semantics - including tolerating a payload that is a list
	or string rather than a dict - in one place.
	"""
	try:
		return container[key]
	except (KeyError, TypeError):
		return None
def _sp_gate_from_roster():
	"""The gate/post the current guard is rostered at right now (see
	gate_movement.guard_post), or "" - an empty gate is honest, a guessed one
	is not.

	Shared by create_staff_attendance and staff_gate_checkout.
	"""
	from upande_security.api.gate_movement import guard_post

	return guard_post()[1] or ""


def _user_roles(user):
	"""Role names for `user`, read straight from tabHas Role.

	Deliberately NOT frappe.get_roles(): that adds the automatic roles
	(All/Guest/Desk User) and expands by user type, whereas the original
	scripts only ever trusted explicit Has Role rows.
	"""
	role_rows = frappe.db.sql("SELECT role FROM `tabHas Role` WHERE parent = %s", (user,))
	roles = []
	for row in role_rows:
		if row and row[0]:
			roles.append(row[0])
	return roles
def _parse_gate_activity_comment(state, html_content):
	"""Pull actor/reason/extra out of the HTML comment the Appointment client script writes.

	Shapes (the client script owns the format; this parser is coupled to it):
	  <b>Rejected by Alice:</b> No appointment today
	  <b>Rescheduled by Bob:</b> Try tomorrow<br><b>New time:</b> 2026-05-23 10:00:00
	  <b>Redirected by Carol:</b> Boss busy<br><b>From:</b> X <b>To:</b> Y
	Anything that does not match leaves the corresponding field blank rather
	than failing the whole feed.
	"""
	out = {"actor": "", "reason": "", "extra_label": "", "extra_value": ""}
	if not html_content:
		return out
	c = str(html_content)
	try:
		ix1 = c.index("by ") + 3
		ix2 = c.index(":</b>", ix1)
		out["actor"] = c[ix1:ix2].strip()
	except (ValueError, KeyError, TypeError):
		pass
	try:
		ix3 = c.index(":</b>") + len(":</b>")
		rest = c[ix3:]
		br = rest.find("<br>")
		chunk = rest if br == -1 else rest[:br]
		chunk = chunk.strip()
		if chunk.startswith(" "):
			chunk = chunk[1:]
		out["reason"] = chunk
	except (ValueError, KeyError, TypeError):
		pass
	if state == "Rescheduled by Host" or state == "Rescheduled by Secretary":
		try:
			ix = c.index("<b>New time:</b>") + len("<b>New time:</b>")
			out["extra_label"] = "New time"
			out["extra_value"] = c[ix:].strip()
		except (ValueError, KeyError, TypeError):
			pass
	elif state == "Redirected to Another Host":
		try:
			ix = c.index("<b>To:</b>") + len("<b>To:</b>")
			out["extra_label"] = "New host"
			out["extra_value"] = c[ix:].strip()
		except (ValueError, KeyError, TypeError):
			pass
	return out


# =============================================================================
# SECTION 1   SESSION & LOOKUPS
# =============================================================================
# Read-only. Nothing here writes, so these were migrated first as the pilot.


def _guard_location(user):
	try:
		from upande_security.api.gate_movement import _location

		return _location(user)
	except Exception:
		return None


def _checking_farm(user):
	try:
		from upande_security.api.gate_vehicle import _resolve_checking_farm

		# Linked farm only: an empty value tells the app to ask the guard.
		return _resolve_checking_farm(user, linked_only=True)
	except Exception:
		return None


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
			# The farm whose gate this login checks at - Employee first, then
			# Security Guard - the same resolution the gate endpoints use, so
			# external guards (no Employee record) get a gate picker too.
			"checking_farm": _checking_farm(user),
			# Rostered post plus any emergency location change on top of it.
			"location": _guard_location(user),
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


@frappe.whitelist()
def update_security_ops_settings(
	nearby_guard_alert_radius_m=None,
	nearby_alert_stale_minutes=None,
	missed_checkin_minutes=None,
	escalation_minutes=None,
):
	"""Write the four scalar thresholds on the Security Ops Settings singleton.

	WRITES Security Ops Settings (Single). Only fields present and non-empty
	are updated; a value that is not an integer is silently skipped (not an
	error). Deliberately narrow: fallback_contacts, notification_rules,
	farm_gates and dispatch_sources stay Desk-only.

	Access: strictly Security Head / System Manager by role, no allowlist (the
	Command Center User allowlist was removed from has_command_center_access,
	so leaving it here would make hiding the mobile chip cosmetic only).

	Uses db.set_value, so the Settings doctype's validate/on_update hooks do
	NOT run. The commit happens even when nothing was updated; the response
	always echoes the stored values (0 for unset).
	"""
	try:
		roles = _user_roles(frappe.session.user)
		has_access = "Security Head" in roles or "System Manager" in roles

		if not has_access:
			return {"error": "You do not have access to Security Ops Settings."}

		supplied = {
			"nearby_guard_alert_radius_m": nearby_guard_alert_radius_m,
			"nearby_alert_stale_minutes": nearby_alert_stale_minutes,
			"missed_checkin_minutes": missed_checkin_minutes,
			"escalation_minutes": escalation_minutes,
		}
		scalar_fields = (
			"nearby_guard_alert_radius_m",
			"nearby_alert_stale_minutes",
			"missed_checkin_minutes",
			"escalation_minutes",
		)
		updates = {}
		for field in scalar_fields:
			raw_value = supplied[field]
			if raw_value is not None and raw_value != "":
				try:
					updates[field] = int(raw_value)
				except (TypeError, ValueError):
					pass

		if updates:
			frappe.db.set_value("Security Ops Settings", "Security Ops Settings", updates)

		frappe.db.commit()

		settings = frappe.db.get_value(
			"Security Ops Settings",
			"Security Ops Settings",
			list(scalar_fields),
			as_dict=True,
		)
		if not settings:
			settings = {}

		return {
			"success": True,
			"nearby_guard_alert_radius_m": settings.get("nearby_guard_alert_radius_m") or 0,
			"nearby_alert_stale_minutes": settings.get("nearby_alert_stale_minutes") or 0,
			"missed_checkin_minutes": settings.get("missed_checkin_minutes") or 0,
			"escalation_minutes": settings.get("escalation_minutes") or 0,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("update_security_ops_settings", str(e))
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
def getVisitorHistory(query=None):
	"""Older visitor-history lookup, matching on phone OR a partial name.

	Distinct from get_visitor_history (same section), which supersedes it and
	keys on custom_id_number ONLY. This one's `customer_name like %q%` can
	match a different person entirely, which is exactly why the newer
	endpoint exists. Kept as-is: this is a port, not the place to change
	matching rules, and the camelCase bare path may still be called by a
	build we cannot inspect.

	Deliberately has NO try/except, matching the original: an exception here
	propagates rather than soft-failing. Adding one would change the status
	code an old client sees.
	"""
	query = (query or "").strip()

	if not query:
		return {"found": False}

	matches = frappe.get_all(
		"Appointment",
		filters=[
			["custom_visitor_type", "in", ["Visitor", ""]],
			["custom_check_in_time", "is", "set"],
		],
		or_filters=[
			["customer_phone_number", "=", query],
			["customer_name", "like", "%" + query + "%"],
		],
		fields=[
			"name",
			"customer_name",
			"customer_phone_number",
			"custom_meet_with",
			"customer_details",
			"custom_mode_of_transport",
			"custom_vehicles_number_plate",
			"custom_vehicles_colour",
			"scheduled_time",
			"custom_check_in_time",
		],
		order_by="custom_check_in_time desc",
		limit_page_length=1,
	)

	if not matches:
		return {"found": False}

	m = matches[0]
	host_name = None
	if m.custom_meet_with:
		host_name = frappe.db.get_value("Employee", m.custom_meet_with, "employee_name")

	return {
		"found": True,
		"visitor_name": m.customer_name,
		"phone_number": m.customer_phone_number,
		"host_id": m.custom_meet_with,
		"host_name": host_name,
		"purpose": m.customer_details,
		"transport_mode": m.custom_mode_of_transport,
		"vehicle_reg_no": m.custom_vehicles_number_plate,
		"vehicle_color": m.custom_vehicles_colour,
		"last_visit_date": m.custom_check_in_time or m.scheduled_time,
	}


@frappe.whitelist()
def getVisitorAppointment(query=None):
	"""Older gate appointment search, superseded by
	search_visitor_appointment.

	Differences from the newer one, all preserved: it searches ALL open
	appointments rather than only today's, matches `name`, `customer_name`
	and `customer_phone_number` with LIKE, reports `id_no` as the
	appointment name (not an ID number), and hardcodes `organization` to the
	literal string "Visitor". It carries no `matched_by`, so a caller cannot
	tell a unique hit from a partial name collision.

	frappe.throw on a missing query sits INSIDE the try, so it soft-fails
	into the error shape below rather than raising - same as the original.
	Note that shape: the full skeleton plus `status` and `message`, never a
	bare {"error": ...}, because the client reads `has_appointment`
	unconditionally.
	"""
	try:
		if not query:
			frappe.throw("Search criteria is required")

		appointments = frappe.get_all(
			"Appointment",
			filters={"status": ["not in", ["Cancelled", "Closed"]]},
			or_filters=[
				["name", "like", "%" + query + "%"],
				["customer_name", "like", "%" + query + "%"],
				["customer_phone_number", "like", "%" + query + "%"],
			],
			fields=[
				"name",
				"customer_name",
				"customer_phone_number",
				"customer_details",
				"status",
				"scheduled_time",
				"custom_meet_with",
				"custom_reporting_status",
				"custom_mode_of_transport",
				"custom_vehicles_number_plate",
				"custom_vehicles_colour",
			],
			limit=1,
		)

		result = {"has_appointment": False, "status": "No Appointment Found"}

		if appointments:
			appt = appointments[0]

			host_id = appt.get("custom_meet_with")
			host_display_name = host_id
			if host_id:
				employee_name = frappe.db.get_value("Employee", host_id, "employee_name")
				if employee_name:
					host_display_name = employee_name

			result = {
				"has_appointment": True,
				"name": appt.get("name"),
				"visitor_name": appt.get("customer_name"),
				# Yes, id_no is the appointment name. The old Flutter model
				# expected it there; not a typo.
				"id_no": appt.get("name"),
				"phone_number": appt.get("customer_phone_number"),
				"organization": "Visitor",
				"host_name": host_display_name,
				# Raw datetime, left for the client to format.
				"scheduled_time": appt.get("scheduled_time"),
				"purpose": appt.get("customer_details") or "General Visit",
				"transport_mode": appt.get("custom_mode_of_transport") or "On Foot",
				"vehicle_reg_no": appt.get("custom_vehicles_number_plate") or "",
				"vehicle_color": appt.get("custom_vehicles_colour") or "",
				"status": appt.get("custom_reporting_status") or appt.get("status"),
			}

		return result

	except Exception as e:
		# Title-only log_error, as the original had it.
		frappe.log_error("Gate Check-in Search Error")
		return {"has_appointment": False, "status": "Error", "message": str(e)}


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


@frappe.whitelist()
def check_in_visitor(name=None, transport=None, plate=None, colour=None, organization=None,
		passengers=None, driver_name=None, driver_phone=None, entry_gate=None):
	"""Check a visitor in at the gate (Server Script 'Check In Visitor', allow_guest=0).

	transport/plate/colour/organization/driver_name/driver_phone are only
	written when the client actually SENT the key (_form_has), because an
	absent key must preserve whatever the workflow already stored on the
	Appointment. An explicit empty string IS a deliberate signal (the gate
	form sends transport="" for On Foot) and is written; for transport the
	empty value is stored as "On Foot". Do not collapse this to `if transport:`.

	workflow_state is set directly via db.set_value rather than
	apply_workflow(): the original sandbox could not import apply_workflow, so
	live behaviour has always been a hardcoded jump. The preceding
	allowed_states check is the only guard on legality. That guard is skipped
	when feature_visitor_approval_workflow == 0, and also when the current
	state is blank.

	The commit happens BEFORE the OTP SMS block, and that block swallows every
	exception, so an SMS/OTP failure never undoes or reports against a
	successful check-in. The OTP is only generated if the visitor has none yet
	(re-check-ins do not re-text). `otp_enabled is None` counts as enabled.
	Non-numeric `passengers` is silently ignored.
	"""
	try:
		name = _s(name)
		sent_transport = _form_has("transport")
		transport = _s(transport)
		sent_plate = _form_has("plate")
		plate = _s(plate)
		sent_colour = _form_has("colour")
		colour = _s(colour)
		sent_organization = _form_has("organization")
		organization = _s(organization)
		passengers_raw = str(passengers) if passengers is not None else ""
		sent_driver_name = _form_has("driver_name")
		driver_name = _s(driver_name)
		sent_driver_phone = _form_has("driver_phone")
		driver_phone = _s(driver_phone)
		entry_gate = str(entry_gate or "").strip()

		if not name:
			return {"error": "name is required"}

		existing = frappe.db.get_value("Appointment", name, ["name", "workflow_state"], as_dict=True)
		if not existing:
			return {"error": "Appointment " + name + " not found"}

		approval_required = frappe.db.get_single_value("Security Ops Settings", "feature_visitor_approval_workflow") != 0
		allowed_states = ["Approved by Host", "Approved by Secretary", "Open"]
		current_state = existing.workflow_state or ""
		if approval_required and current_state and current_state not in allowed_states:
			return {
				"error": "Cannot check in from state: " + current_state +
						 ". Visitor must be approved by host first."
			}

		now = frappe.utils.now_datetime()
		updates = {
			"workflow_state": "Visitor Checked In",
			"custom_reporting_status": "Checked in",
			"custom_check_in_time": now,
		}
		if sent_transport:
			updates["custom_mode_of_transport"] = transport or "On Foot"
		if sent_plate:
			updates["custom_vehicles_number_plate"] = plate
		if sent_colour:
			updates["custom_vehicles_colour"] = colour
		if sent_organization:
			updates["customer_organization"] = organization
		if sent_driver_name:
			updates["custom_taxi_driver_name"] = driver_name
		if sent_driver_phone:
			updates["custom_taxi_driver_phone"] = driver_phone
		if passengers_raw:
			try:
				updates["custom_number_of_passengers"] = int(passengers_raw)
			except Exception:
				pass
		if entry_gate:
			updates["custom_entry_gate"] = entry_gate

		resolved_company, resolved_farm = _guard_scope()
		if resolved_company:
			updates["custom_company"] = resolved_company
		if resolved_farm:
			updates["custom_farmunit"] = resolved_farm

		frappe.db.set_value("Appointment", name, updates)
		frappe.db.commit()
		watchlist.track("Appointment", name, "Visitor Check-in")

		try:
			otp_enabled = frappe.db.get_single_value("Security Ops Settings", "feature_visitor_sms_otp")
			if otp_enabled is None or otp_enabled:
				otp_row = frappe.db.get_value(
					"Appointment", name,
					["customer_phone_number", "customer_name", "custom_meet_with_company", "custom_visitor_otp"],
					as_dict=True,
				)
				if otp_row and not otp_row.custom_visitor_otp:
					otp_digits = _normalise_ke_phone(otp_row.customer_phone_number)
					if otp_digits:
						otp_hash = frappe.utils.generate_hash(length=4)
						otp_code = ""
						for ch in otp_hash:
							otp_code = otp_code + str(ord(ch) % 10)
						frappe.db.set_value("Appointment", name, "custom_visitor_otp", otp_code, update_modified=False)
						otp_company = otp_row.custom_meet_with_company or "us"
						otp_template = frappe.db.get_single_value("Security Ops Settings", "visitor_otp_sms_template")
						if not otp_template:
							otp_template = "Welcome to {company}! Your visit code is {code}."
						otp_message = otp_template.replace("{company}", otp_company).replace("{code}", otp_code).replace("{visitor}", otp_row.customer_name or "")
						frappe.call(
							"frappe.core.doctype.sms_settings.sms_settings.send_sms",
							receiver_list=[otp_digits],
							msg=otp_message,
							success_msg=False,
						)
		except Exception:
			pass

		return {
			"name": name,
			"custom_reporting_status": "Checked in",
			"custom_check_in_time": str(now),
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("check_in_visitor", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def check_out_visitor(name=None):
	"""Check a visitor out and free their badge (Server Script 'Check Out Visitor', allow_guest=0).

	The "host must have scanned the badge QR before checkout" gate was
	deliberately disabled on 2026-09-29 (live request). custom_host_received_time
	is still fetched and recorded elsewhere but no longer blocks; the missing
	check is intentional, not an omission. Restoring it means returning an
	error when existing.custom_visitor_badge is set and
	existing.custom_host_received_time is not.

	workflow_state is set directly (no apply_workflow), same reason as
	check_in_visitor. The Visitor Badge is released (Available, no current
	appointment) in the same commit as the Appointment close. The thank-you
	SMS runs after the commit and swallows all exceptions so SMS can never
	fail a checkout. NOTE it is gated by the SAME flag as the OTP
	(feature_visitor_sms_otp), not a separate thank-you flag.
	"""
	try:
		name = str(name or "").strip()
		if not name:
			return {"error": "name is required"}

		existing = frappe.db.get_value(
			"Appointment",
			name,
			["name", "custom_host_received_time", "custom_visitor_badge"],
			as_dict=True,
		)
		if not existing:
			return {"error": "Appointment " + name + " not found"}

		now = frappe.utils.now_datetime()
		frappe.db.set_value(
			"Appointment",
			name,
			{
				"workflow_state": "Visitor Checked Out",
				"custom_reporting_status": "Checked out",
				"custom_check_out_time": now,
				"status": "Closed",
			},
		)
		if existing.custom_visitor_badge:
			frappe.db.set_value(
				"Visitor Badge",
				existing.custom_visitor_badge,
				{"status": "Available", "current_appointment": None},
			)
		frappe.db.commit()
		watchlist.track("Appointment", name, "Visitor Check-out")

		try:
			thankyou_enabled = frappe.db.get_single_value("Security Ops Settings", "feature_visitor_sms_otp")
			if thankyou_enabled is None or thankyou_enabled:
				ty_row = frappe.db.get_value(
					"Appointment", name,
					["customer_phone_number", "customer_name", "custom_meet_with_company"],
					as_dict=True,
				)
				if ty_row:
					ty_digits = _normalise_ke_phone(ty_row.customer_phone_number)
					if ty_digits:
						ty_company = ty_row.custom_meet_with_company or "us"
						ty_template = frappe.db.get_single_value("Security Ops Settings", "visitor_thankyou_sms_template")
						if not ty_template:
							ty_template = "Thanks for visiting {company}, welcome again!"
						ty_message = ty_template.replace("{company}", ty_company).replace("{visitor}", ty_row.customer_name or "")
						frappe.call(
							"frappe.core.doctype.sms_settings.sms_settings.send_sms",
							receiver_list=[ty_digits],
							msg=ty_message,
							success_msg=False,
						)
		except Exception:
			pass

		return {
			"name": name,
			"workflow_state": "Visitor Checked Out",
			"custom_reporting_status": "Checked out",
			"custom_check_out_time": str(now),
			"status": "Closed",
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("check_out_visitor", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def create_walk_in(customer_name=None, id_number=None, phone=None, email=None, host=None,
		purpose=None, organization=None, transport=None, plate=None, colour=None,
		driver_name=None, driver_phone=None, passengers=None):
	"""Create an already-checked-in walk-in Appointment (Server Script 'Create Walk In', allow_guest=0).

	scheduled_time is ALWAYS server now + 15 min; any client value (there is
	none read here) must stay ignored. Appointment's own "not in the past"
	validation re-evaluates now() a moment after the value is set, so an
	unbuffered now() has already become the past by then, and device clocks /
	timezones are not trusted.

	flags.ignore_mandatory + insert(ignore_permissions=True) are deliberate:
	the guard role cannot create Appointments directly. Status is created
	"Open" and "Checked in" immediately (unlike create_walk_in_notify, which
	starts "Scheduled" and goes to host review). custom_company /
	custom_farmunit are stamped from the guard's scope for access scoping.
	The OTP SMS is sent after commit and cannot fail the call. Unlike
	check_in_visitor it does not check whether an OTP already exists.
	"""
	try:
		customer_name = _s(customer_name)
		id_number = _s(id_number)
		phone = _s(phone)
		email = _s(email)
		host = _s(host)
		purpose = _s(purpose)
		organization = _s(organization)
		transport = _s(transport) or "On Foot"
		plate = _s(plate)
		colour = _s(colour)
		driver_name = _s(driver_name)
		driver_phone = _s(driver_phone)
		passengers_raw = str(passengers) if passengers is not None else ""

		if not customer_name:
			return {"error": "customer_name is required"}
		if not phone:
			return {"error": "phone is required"}
		if not host:
			return {"error": "host is required"}

		scheduled_time = str(frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=15))

		host_ok = frappe.db.get_value("Employee", host, "name")
		if not host_ok:
			return {"error": "Host " + host + " not found"}

		now = frappe.utils.now_datetime()
		doc = frappe.new_doc("Appointment")
		doc.flags.ignore_mandatory = True
		doc.customer_name = customer_name
		doc.custom_id_number = id_number
		doc.customer_phone_number = phone
		doc.customer_email = email
		doc.custom_meet_with = host
		doc.scheduled_time = scheduled_time
		doc.customer_details = purpose
		doc.custom_mode_of_transport = transport
		doc.custom_vehicles_number_plate = plate
		doc.custom_vehicles_colour = colour
		if organization:
			doc.customer_organization = organization
		if driver_name:
			doc.custom_taxi_driver_name = driver_name
		if driver_phone:
			doc.custom_taxi_driver_phone = driver_phone
		if passengers_raw:
			try:
				doc.custom_number_of_passengers = int(passengers_raw)
			except Exception:
				pass
		doc.status = "Open"
		doc.custom_reporting_status = "Checked in"
		doc.custom_check_in_time = now

		resolved_company, resolved_farm = _guard_scope()
		if resolved_company:
			doc.custom_company = resolved_company
		if resolved_farm:
			doc.custom_farmunit = resolved_farm

		doc.insert(ignore_permissions=True)
		frappe.db.commit()

		try:
			otp_enabled = frappe.db.get_single_value("Security Ops Settings", "feature_visitor_sms_otp")
			if otp_enabled is None or otp_enabled:
				otp_digits = _normalise_ke_phone(doc.customer_phone_number)
				if otp_digits:
					otp_hash = frappe.utils.generate_hash(length=4)
					otp_code = ""
					for ch in otp_hash:
						otp_code = otp_code + str(ord(ch) % 10)
					frappe.db.set_value("Appointment", doc.name, "custom_visitor_otp", otp_code, update_modified=False)
					otp_company = doc.custom_meet_with_company or "us"
					otp_template = frappe.db.get_single_value("Security Ops Settings", "visitor_otp_sms_template")
					if not otp_template:
						otp_template = "Welcome to {company}! Your visit code is {code}."
					otp_message = otp_template.replace("{company}", otp_company).replace("{code}", otp_code).replace("{visitor}", doc.customer_name or "")
					frappe.call(
						"frappe.core.doctype.sms_settings.sms_settings.send_sms",
						receiver_list=[otp_digits],
						msg=otp_message,
						success_msg=False,
					)
		except Exception:
			pass

		return {
			"name": doc.name,
			"customer_name": customer_name,
			"host_id": host,
			"custom_reporting_status": "Checked in",
			"custom_check_in_time": str(now),
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("create_walk_in", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def create_walk_in_notify(customer_name=None, id_number=None, phone=None, email=None,
		organization=None, host=None, purpose=None, transport=None, plate=None,
		colour=None, idempotency_key=None, passengers=None):
	"""Create a walk-in Appointment that goes to host review and emails host + secretaries
	(Server Script 'Create Walk In Notify', allow_guest=0).

	Idempotency: the mobile app mints one key per form-fill and resends it on
	every retry, so a repeat of an attempt that already landed (guard re-taps
	NOTIFY HOST after a timeout) returns the existing record with
	duplicate_suppressed=True, notified=0, and never inserts or emails again.
	Lookup is by Appointment.custom_idempotency_key. It is a read-then-write
	with no lock, so two truly concurrent retries can both miss and both insert.

	scheduled_time is server now + 15 min for the same reason as
	create_walk_in (Appointment's re-evaluated "not in the past" check).

	WORKFLOW (behaviour-preservation decision): the original tried
	`from frappe.model.workflow import apply_workflow` and, because the
	safe-exec sandbox forbids imports, ALWAYS fell into its except branch,
	which set workflow_state and custom_reporting_status to
	"Pending Host Review" via db.set_value. That is the live behaviour, so
	this port does the set_value directly and does NOT call apply_workflow.
	Switching to apply_workflow would change what is written (it would not
	set custom_reporting_status), so do it only as a deliberate change.

	Secretary recipients are scoped to the host's company through User
	Permission(Company). An unscoped "role = Secretary" query also matches
	every dev/admin test account (they hold every role), which used to CC
	Upande's own dev team on real walk-ins. The email send is best-effort:
	failure leaves notified=0 but the appointment still stands.
	"""
	try:
		customer_name = _s(customer_name)
		id_number = _s(id_number)
		phone = _s(phone)
		email = _s(email)
		organization = _s(organization)
		host = _s(host)
		purpose = _s(purpose)
		transport = _s(transport) or "On Foot"
		plate = _s(plate)
		colour = _s(colour)
		idempotency_key = _s(idempotency_key)
		passengers_raw = str(passengers) if passengers is not None else ""

		if not customer_name:
			return {"error": "customer_name is required"}
		if not phone:
			return {"error": "phone is required"}
		if not host:
			return {"error": "host is required"}

		existing_name = ""
		if idempotency_key:
			existing_name = frappe.db.get_value(
				"Appointment", {"custom_idempotency_key": idempotency_key}, "name"
			) or ""

		if existing_name:
			existing = frappe.db.get_value(
				"Appointment",
				existing_name,
				["customer_name", "custom_meet_with", "workflow_state"],
				as_dict=True,
			)
			return {
				"name": existing_name,
				"customer_name": existing.customer_name if existing else customer_name,
				"host_id": existing.custom_meet_with if existing else host,
				"workflow_state": existing.workflow_state if existing else "Pending Host Review",
				"notified": 0,
				"duplicate_suppressed": True,
			}

		scheduled_time = str(frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=15))

		host_rec = frappe.db.get_value("Employee", host, ["name", "user_id", "employee_name", "company"], as_dict=True)
		if not host_rec:
			return {"error": "Host " + host + " not found"}

		# Leftover debug log from the original; it writes the full payload
		# (visitor name, phone, ID number) into the Error Log on every call.
		# Kept for parity, flagged as a PII concern.
		host_email_dbg = host_rec.user_id or ""
		frappe.log_error(
			title="create_walk_in_notify debug",
			message="Payload: " + str(frappe.local.form_dict) + "\nHost: " + host + "\nHost email (user_id): " + host_email_dbg,
		)

		doc = frappe.new_doc("Appointment")
		doc.flags.ignore_mandatory = True
		doc.customer_name = customer_name
		doc.custom_id_number = id_number
		doc.customer_phone_number = phone
		doc.customer_email = email
		if organization:
			doc.customer_organization = organization
		doc.custom_meet_with = host
		doc.scheduled_time = scheduled_time
		doc.customer_details = purpose
		doc.custom_mode_of_transport = transport
		doc.custom_vehicles_number_plate = plate
		doc.custom_vehicles_colour = colour
		if idempotency_key:
			doc.custom_idempotency_key = idempotency_key
		if passengers_raw:
			try:
				doc.custom_number_of_passengers = int(passengers_raw)
			except Exception:
				pass
		doc.status = "Open"
		doc.custom_reporting_status = "Scheduled"
		doc.insert(ignore_permissions=True)
		appt_name = doc.name

		frappe.db.set_value(
			"Appointment",
			appt_name,
			{
				"workflow_state": "Pending Host Review",
				"custom_reporting_status": "Pending Host Review",
			},
		)
		frappe.db.commit()

		host_user_id = host_rec.user_id or ""
		host_name = host_rec.employee_name or host
		recipient_users = []
		if host_user_id:
			recipient_users.append(host_user_id)

		try:
			if host_rec.company:
				sec_rows = frappe.db.sql(
					"SELECT DISTINCT up.user FROM `tabUser Permission` up "
					"JOIN `tabHas Role` hr ON hr.parent = up.user AND hr.role = 'Secretary' "
					"WHERE up.allow = 'Company' AND up.for_value = %s "
					"AND up.user NOT IN ('Administrator', 'Guest')",
					(host_rec.company,),
					as_dict=False,
				)
				for row in sec_rows:
					if row and row[0] and row[0] not in recipient_users:
						recipient_users.append(row[0])
		except Exception:
			pass

		subject = "Walk-in Visitor: " + customer_name + " at the gate to see " + host_name
		body = "<p><strong>" + customer_name + "</strong> (walk-in) has arrived at the gate to see <strong>" + host_name + "</strong></p>"
		if purpose:
			body = body + "<p>Purpose: " + purpose + "</p>"
		body = body + "<p>Please <strong>approve, reschedule, or reject</strong> this visit in ERPNext.</p>"

		notified = 0
		if recipient_users:
			try:
				frappe.sendmail(
					recipients=recipient_users,
					subject=subject,
					message=body,
					now=True,
				)
				notified = len(recipient_users)
			except Exception:
				pass

		return {
			"name": appt_name,
			"customer_name": customer_name,
			"host_id": host,
			"workflow_state": "Pending Host Review",
			"notified": notified,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("create_walk_in_notify", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def book_customer_appointment(customer=None, person_name=None, id_number=None, host=None,
		scheduled_time=None, purpose=None):
	"""Pre-book a visit for a person sent by an existing Customer
	(Server Script 'Book Customer Appointment', allow_guest=0).

	Phone and email always come from the linked Customer record, never from
	the caller; only the person's name and ID number are captured per visit.

	The doc is inserted in the workflow's own initial state and only THEN
	moved to "Pending Host Review" with a second db.set_value. Do not set
	workflow_state before insert: the Workflow now rejects states not reachable
	through a named action. The two-step set_value bypass mirrors what the
	original sandbox forced (no apply_workflow). Unlike the walk-in endpoints,
	scheduled_time IS taken from the client, so Appointment's past-time
	validation can reject it (surfaces as {"error": ...}).
	"""
	try:
		customer = _s(customer)
		person_name = _s(person_name)
		id_number = _s(id_number)
		host = _s(host)
		scheduled_time = _s(scheduled_time)
		purpose = _s(purpose)

		if not customer:
			return {"error": "customer is required"}
		if not person_name:
			return {"error": "person_name is required"}
		if not host:
			return {"error": "host is required"}
		if not scheduled_time:
			return {"error": "scheduled_time is required"}

		customer_doc = frappe.db.get_value(
			"Customer", customer, ["name", "customer_name", "mobile_no", "email_id"], as_dict=True
		)
		if not customer_doc:
			return {"error": "Customer " + customer + " not found"}

		host_ok = frappe.db.get_value("Employee", host, "name")
		if not host_ok:
			return {"error": "Host " + host + " not found"}

		doc = frappe.new_doc("Appointment")
		doc.flags.ignore_mandatory = True
		doc.customer_name = person_name
		doc.custom_id_number = id_number
		doc.custom_customer = customer_doc.name
		doc.customer_phone_number = customer_doc.mobile_no or ""
		doc.customer_email = customer_doc.email_id or ""
		doc.custom_meet_with = host
		doc.scheduled_time = scheduled_time
		doc.customer_details = purpose
		doc.custom_visitor_type = "Customer"
		doc.status = "Open"
		doc.insert(ignore_permissions=True)
		frappe.db.set_value("Appointment", doc.name, "workflow_state", "Pending Host Review")
		frappe.db.commit()
		return {
			"name": doc.name,
			"customer_name": doc.customer_name,
			"custom_customer": doc.custom_customer,
			"host_id": host,
			"scheduled_time": str(doc.scheduled_time),
			"workflow_state": "Pending Host Review",
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("book_customer_appointment", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def gate_temp_exit(reference_doctype=None, reference_name=None, direction=None):
	"""Record a person stepping out ("out") / back in ("in") without a full checkout
	(Server Script 'Gate Temp Exit', allow_guest=0).

	The feature-flag guard RAISES inside the try on purpose, so a disabled
	feature soft-fails into {"error": "This feature is not enabled on this
	instance."} at HTTP 200 (and also logs an Error Log row and rolls back).
	Preserved as-is; do not turn it into a bare frappe.throw.

	reference_doctype is whitelisted to Appointment/Attendance, which is what
	makes the doctype-from-input db.get_value/set_value calls safe. Each "in"
	appends "<out> -> <in> (<mins>m)" to custom_temp_exit_log; the out time is
	cleared to None. Times are stored as strings from get_datetime_str (the
	prod sandbox cannot use strftime). A duration that cannot be computed
	becomes the literal text "None" in the log line, by design of the original.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_gate_temp_exit") == 0:
			raise Exception("This feature is not enabled on this instance.")

		reference_doctype = (reference_doctype or "").strip()
		reference_name = (reference_name or "").strip()
		direction = (direction or "").strip()

		allowed_doctypes = ["Appointment", "Attendance"]

		if reference_doctype not in allowed_doctypes:
			return {"error": "reference_doctype must be Appointment or Attendance"}
		if not reference_name:
			return {"error": "reference_name is required"}
		if direction not in ("out", "in"):
			return {"error": "direction must be 'out' or 'in'"}
		if not frappe.db.exists(reference_doctype, reference_name):
			return {"error": reference_doctype + " " + reference_name + " not found"}

		current_temp_exit = frappe.db.get_value(reference_doctype, reference_name, "custom_temp_exit_time")

		if direction == "out":
			if current_temp_exit:
				return {"error": reference_name + " is already stepped out"}
			now_str = frappe.utils.get_datetime_str(frappe.utils.now_datetime())
			frappe.db.set_value(reference_doctype, reference_name, "custom_temp_exit_time", now_str, update_modified=True)
			frappe.db.commit()
			return {
				"success": True,
				"direction": "out",
				"temp_exit_time": now_str,
			}

		if not current_temp_exit:
			return {"error": reference_name + " is not currently stepped out"}
		now_str = frappe.utils.get_datetime_str(frappe.utils.now_datetime())
		duration_minutes = None
		try:
			duration_minutes = round(frappe.utils.time_diff_in_seconds(now_str, current_temp_exit) / 60, 1)
		except Exception:
			duration_minutes = None

		existing_log = frappe.db.get_value(reference_doctype, reference_name, "custom_temp_exit_log") or ""
		log_line = str(current_temp_exit) + " -> " + now_str + " (" + str(duration_minutes) + "m)"
		new_log = log_line if not existing_log else existing_log + "\n" + log_line

		frappe.db.set_value(
			reference_doctype,
			reference_name,
			{"custom_temp_exit_time": None, "custom_temp_exit_log": new_log},
			update_modified=True,
		)
		frappe.db.commit()
		return {
			"success": True,
			"direction": "in",
			"out_time": now_str,
			"duration_minutes": duration_minutes,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("gate_temp_exit", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def notify_host(name=None):
	"""Move an existing Appointment to host review and email the host
	(Server Script 'Notify Host', allow_guest=0).

	WORKFLOW (behaviour-preservation decision): the original wrapped
	`apply_workflow(doc, "Notify Host")` in try/except with a db.set_value
	fallback, but the safe-exec sandbox forbids the import, so the fallback
	was ALWAYS what ran. This port performs that set_value directly and does
	not call apply_workflow. Calling it would add workflow side effects
	(transition validation, doc.save hooks) that never ran in production.

	Recipients: the host's user plus EVERY user holding the Secretary role,
	site-wide (no company scoping, unlike create_walk_in_notify, which was
	later fixed to scope by Company User Permission). Likely to over-notify,
	including dev/admin accounts holding all roles. Preserved, not fixed.
	The workflow update is committed before the email attempt and email
	failure is swallowed (notified=0, still success=True).
	"""
	try:
		name = str(name or "").strip()
		if not name:
			return {"error": "name is required"}

		appt = frappe.db.sql(
			"""
			SELECT a.name, a.customer_name, a.customer_details,
				   a.scheduled_time, a.workflow_state, a.custom_meet_with,
				   e.employee_name AS host_display_name,
				   e.user_id AS host_user_id
			FROM `tabAppointment` a
			LEFT JOIN `tabEmployee` e ON e.name = a.custom_meet_with
			WHERE a.name = %s
			LIMIT 1
			""",
			(name,),
			as_dict=True,
		)
		if not appt:
			return {"error": "Appointment " + name + " not found"}
		r = appt[0]

		frappe.db.set_value(
			"Appointment",
			name,
			{"workflow_state": "Pending Host Review"},
		)
		frappe.db.commit()

		recipient_users = []
		host_user_id = r.host_user_id or ""
		if host_user_id:
			recipient_users.append(host_user_id)

		try:
			sec_rows = frappe.db.sql(
				"SELECT DISTINCT parent FROM `tabHas Role` WHERE role = 'Secretary' AND parent NOT IN ('Administrator', 'Guest')",
				as_dict=False,
			)
			for row in sec_rows:
				if row and row[0] and row[0] not in recipient_users:
					recipient_users.append(row[0])
		except Exception:
			pass

		notified = 0
		visitor_name = r.customer_name or name
		host_display = r.host_display_name or r.custom_meet_with or "the host"
		purpose = r.customer_details or ""
		scheduled = str(r.scheduled_time) if r.scheduled_time else ""

		subject = "Gate Arrival: " + visitor_name + " is at the gate to see " + host_display

		body = "<p><strong>" + visitor_name + "</strong> has arrived at the gate</p>"
		if host_display:
			body = body + "<p>Visiting: " + host_display + "</p>"
		if purpose:
			body = body + "<p>Purpose: " + purpose + "</p>"
		if scheduled:
			body = body + "<p>Scheduled: " + scheduled + "</p>"
		body = body + "<p>Please <strong>approve, reschedule, or reject</strong> this visit in ERPNext.</p>"

		if recipient_users:
			try:
				frappe.sendmail(
					recipients=recipient_users,
					subject=subject,
					message=body,
					now=True,
				)
				notified = len(recipient_users)
			except Exception:
				pass

		return {
			"success": True,
			"appointment": name,
			"workflow_state": "Pending Host Review",
			"notified": notified,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("notify_host", str(e))
		return {"error": str(e)}


@frappe.whitelist(allow_guest=True)
def confirm_host_received(company=None, farm=None, badge_number=None):
	"""Host confirms receipt of a visitor by scanning the badge QR code.

	allow_guest=True is load-bearing: reached anonymously via the QR code; a
	403 logs the mobile user out. Because the caller is unauthenticated this
	verb is keyed by company+farm+badge_number and never trusts an
	appointment name (see confirm_host_received_by_appointment for the
	logged-in variant). Gated by feature_host_receipt_confirmation.

	Idempotent: if custom_host_received_time is already set it is NOT
	overwritten; the existing time is returned with already_confirmed=True.
	Writes via raw frappe.db.set_value (no doc hooks).
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_host_receipt_confirmation") == 0:
			raise Exception("This feature is not enabled on this instance.")

		company = str(company or "").strip()
		farm = str(farm or "").strip()
		badge_number_raw = str(badge_number) if badge_number is not None else ""

		if not company:
			return {"error": "company is required"}
		elif not farm:
			return {"error": "farm is required"}
		elif not badge_number_raw:
			return {"error": "badge_number is required"}
		else:
			try:
				badge_number = int(badge_number_raw)
			except Exception:
				badge_number = None

			if badge_number is None:
				return {"error": "badge_number must be a number"}
			else:
				current_appointment = frappe.db.get_value(
					"Visitor Badge",
					{"company": company, "farm": farm, "badge_number": badge_number},
					"current_appointment",
				)
				if not current_appointment:
					return {
						"error": "Badge "
						+ str(badge_number)
						+ " ("
						+ company
						+ " / "
						+ farm
						+ ") is not currently assigned to any visitor."
					}
				else:
					appt = frappe.db.get_value(
						"Appointment",
						current_appointment,
						["name", "custom_host_received_time"],
						as_dict=True,
					)
					if not appt:
						return {
							"error": "Badge "
							+ str(badge_number)
							+ " points to a visit that no longer exists."
						}
					elif appt.custom_host_received_time:
						return {
							"already_confirmed": True,
							"confirmed_at": str(appt.custom_host_received_time),
						}
					else:
						now = frappe.utils.now_datetime()
						frappe.db.set_value(
							"Appointment", appt.name, "custom_host_received_time", now
						)
						frappe.db.commit()
						return {
							"already_confirmed": False,
							"confirmed_at": str(now),
						}
	except Exception as e:
		frappe.log_error("confirm_host_received", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def confirm_host_received_by_appointment(name=None):
	"""Desk-side counterpart of confirm_host_received, behind the "Confirm
	Receipt" button on the Appointment form, for hosts already logged in and
	looking at the record (no badge scan).

	Not allow_guest on purpose: the guest verb never trusts an appointment
	name from an unauthenticated caller, this one can because it requires a
	session. Gated by feature_host_receipt_confirmation. Requires that a
	visitor badge was issued (custom_visitor_badge set). Idempotent, same as
	the guest verb. Writes via raw frappe.db.set_value.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_host_receipt_confirmation") == 0:
			raise Exception("This feature is not enabled on this instance.")

		name = str(name or "").strip()

		if not name:
			return {"error": "name is required"}
		else:
			appt = frappe.db.get_value(
				"Appointment",
				name,
				["name", "custom_host_received_time", "custom_visitor_badge"],
				as_dict=True,
			)
			if not appt:
				return {"error": "Appointment " + name + " not found"}
			elif not appt.custom_visitor_badge:
				return {
					"error": "No visitor badge has been issued for this visit yet"
				}
			elif appt.custom_host_received_time:
				return {
					"already_confirmed": True,
					"confirmed_at": str(appt.custom_host_received_time),
				}
			else:
				now = frappe.utils.now_datetime()
				frappe.db.set_value("Appointment", name, "custom_host_received_time", now)
				frappe.db.commit()
				return {
					"already_confirmed": False,
					"confirmed_at": str(now),
				}
	except Exception as e:
		frappe.log_error("confirm_host_received_by_appointment", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def confirm_host_received_by_number(badge_number=None):
	"""Desk counterpart of confirm_host_received keyed by the plain badge
	number only; company (and farm) come from the caller's own Employee
	record, as in get_visitor_badge_info_by_number. Not allow_guest.

	Gated by feature_host_receipt_confirmation. With no custom_farm on the
	Employee, scans all farms of the company and takes the first badge that
	is assigned. Idempotent; writes via raw frappe.db.set_value. Unlike the
	lookup verb, an unassigned badge here is NOT logged as an unauthorized
	access attempt.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_host_receipt_confirmation") == 0:
			raise Exception("This feature is not enabled on this instance.")

		badge_number_raw = str(badge_number) if badge_number is not None else ""

		if not badge_number_raw:
			return {"error": "badge_number is required"}
		else:
			try:
				badge_number = int(badge_number_raw)
			except Exception:
				badge_number = None

			if badge_number is None:
				return {"error": "badge_number must be a number"}
			else:
				current_user = frappe.session.user
				employee = frappe.db.get_value(
					"Employee", {"user_id": current_user}, ["company", "custom_farm"], as_dict=True
				)
				company = employee.company if employee else ""
				farm = employee.custom_farm if employee else ""

				if not company:
					return {
						"error": "No Employee record linked to this login — cannot determine your company."
					}
				else:
					current_appointment = None
					if farm:
						current_appointment = frappe.db.get_value(
							"Visitor Badge",
							{"company": company, "farm": farm, "badge_number": badge_number},
							"current_appointment",
						)
					else:
						candidates = frappe.db.get_all(
							"Visitor Badge",
							filters={"company": company, "badge_number": badge_number},
							fields=["current_appointment"],
						)
						for c in candidates:
							if c.current_appointment:
								current_appointment = c.current_appointment
								break

					if not current_appointment:
						return {
							"error": "Badge "
							+ str(badge_number)
							+ " ("
							+ company
							+ (" / " + farm if farm else "")
							+ ") is not currently assigned to any visitor."
						}
					else:
						appt = frappe.db.get_value(
							"Appointment",
							current_appointment,
							["name", "custom_host_received_time"],
							as_dict=True,
						)
						if not appt:
							return {
								"error": "Badge "
								+ str(badge_number)
								+ " points to a visit that no longer exists."
							}
						elif appt.custom_host_received_time:
							return {
								"already_confirmed": True,
								"confirmed_at": str(appt.custom_host_received_time),
							}
						else:
							now = frappe.utils.now_datetime()
							frappe.db.set_value(
								"Appointment", appt.name, "custom_host_received_time", now
							)
							frappe.db.commit()
							return {
								"already_confirmed": False,
								"confirmed_at": str(now),
							}
	except Exception as e:
		frappe.log_error("confirm_host_received_by_number", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def check_out_taxi_driver(name=None):
	"""Mark the taxi driver of an Appointment as departed. Gated by
	feature_taxi_driver_checkout.

	Touches ONLY custom_taxi_driver_check_out_time: the visitor's own
	check-in/out state (workflow_state, custom_check_out_time, status) is
	deliberately untouched so the visitor can still be checked out separately
	whenever they actually leave. Only valid when custom_mode_of_transport is
	"Taxi", and refuses a second departure. Writes via raw frappe.db.set_value.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_taxi_driver_checkout") == 0:
			raise Exception("This feature is not enabled on this instance.")

		name = str(name or "").strip()

		if not name:
			return {"error": "name is required"}
		else:
			existing = frappe.db.get_value(
				"Appointment",
				name,
				["name", "custom_mode_of_transport", "custom_taxi_driver_check_out_time"],
				as_dict=True,
			)
			if not existing:
				return {"error": "Appointment " + name + " not found"}
			elif existing.custom_mode_of_transport != "Taxi":
				return {
					"error": "This appointment is not marked as arriving by Taxi"
				}
			elif existing.custom_taxi_driver_check_out_time:
				return {
					"error": "Driver already marked as departed at "
					+ str(existing.custom_taxi_driver_check_out_time)
				}
			else:
				now = frappe.utils.now_datetime()
				frappe.db.set_value(
					"Appointment", name, "custom_taxi_driver_check_out_time", now
				)
				frappe.db.commit()
				watchlist.track("Appointment", name, "Taxi Driver Check-out")
				return {
					"name": name,
					"custom_taxi_driver_check_out_time": str(now),
				}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("check_out_taxi_driver", str(e))
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

		# The Server Script had a `from frappe.model.workflow import
		# apply_workflow` here, wrapped in try/except Exception: pass, to
		# "also" transition the workflow. That branch was DEAD: safe_exec
		# forbids every import ("ImportError: __import__ not found"), so the
		# import raised on the first line and the except swallowed it on
		# every single call. No contractor checkout has ever transitioned a
		# workflow, only written the fields below.
		#
		# Porting it literally would have started running it for real,
		# because a plain app module CAN import - silently adding a workflow
		# transition and a doc.save() (with every Appointment on_update hook
		# that fires behind it) to an endpoint that never did either. It is
		# left out so this keeps doing exactly what production does today.
		# Adding the transition back is a deliberate feature change, not a
		# migration detail.

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

		# Checking the visit out ends the job: its contractor badges go back
		# to the pool, and anyone still recorded inside a farm is closed.
		from upande_security.api.contractor_badge import release_badges_for_visit

		release_badges_for_visit(appt_name)

		frappe.db.commit()
		watchlist.track("Appointment", appt_name, "Contractor Check-out")

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


@frappe.whitelist()
def contractor_gate_checkin(
	appointment_name=None,
	contractor_ref=None,
	contractor_name=None,
	phone=None,
	company=None,
	purpose=None,
	transport_mode=None,
	number_plate=None,
	vehicle_color=None,
	passengers=None,
):
	"""Check a contractor in at the gate: create a new Appointment (no
	appointment_name) or mark an existing one checked in.

	Error contract differs from the other endpoints, as in the original: this one
	RAISES. The contractor_name and feature-flag frappe.throw calls sit outside the
	try (note the validation runs before the flag check), and the final failure is
	re-raised as frappe.throw('Contractor check-in failed: ...') from the except
	after logging.

	Company/farm stamping comes from the guard's own scope (as check_in_visitor /
	create_walk_in): Employee first, then Security Guard by full name, each of
	company and farm backfilled independently.

	New Appointments are inserted with validation/links/mandatory/email all
	bypassed, then the custom_* fields are written with db.set_value (they are not
	reliably writable through insert). For an existing Appointment ONLY the
	fields are stamped - there is NO workflow transition. The Server Script
	appeared to attempt one, but that block could never run (see the comment
	in the else branch), so stamping is all this has ever done. Do not
	"restore" the transition on the strength of the old code: it would add
	a doc.save() and every Appointment on_update hook, including the OTP
	text, to an endpoint that never fired them.

	Values are used with .strip() exactly as before, so a non-string (e.g. numeric
	phone) raises AttributeError, as it did in the sandbox.
	"""
	appt_name = (appointment_name or '').strip() or None
	contractor_ref = (contractor_ref or '').strip() or None
	contractor_name = (contractor_name or '').strip()
	phone = (phone or '').strip() or None
	company = (company or '').strip() or None
	purpose = (purpose or '').strip() or 'Contractor site access'
	transport = (transport_mode or 'On Foot').strip()
	number_plate = (number_plate or '').strip() or None
	vehicle_color = (vehicle_color or '').strip() or None
	passengers_raw = passengers

	if not contractor_name and contractor_ref:
		contractor_name = frappe.db.get_value('Supplier', contractor_ref, 'supplier_name') or contractor_ref

	if not contractor_name:
		frappe.throw('contractor_name or contractor_ref is required')

	if frappe.db.get_single_value("Security Ops Settings", "feature_contractor_checkin") == 0:
		frappe.throw("This feature is not enabled on this instance.")

	passengers = None
	if passengers_raw not in (None, '', 'null'):
		try:
			passengers = int(passengers_raw)
		except (TypeError, ValueError):
			passengers = None

	current_user = frappe.session.user
	employee = frappe.db.get_value(
		'Employee', {'user_id': current_user}, ['company', 'custom_farm'], as_dict=True
	)
	resolved_company = employee.company if employee else None
	resolved_farm = employee.custom_farm if employee else None
	if not resolved_company or not resolved_farm:
		user_full = frappe.db.get_value('User', current_user, 'full_name') or ''
		if user_full:
			guard = frappe.db.get_value(
				'Security Guard', {'full_name': user_full}, ['company', 'farm'], as_dict=True
			)
			if guard:
				if not resolved_company:
					resolved_company = guard.company
				if not resolved_farm:
					resolved_farm = guard.farm

	now_str = frappe.utils.now()

	try:
		if not appt_name:
			detail_str = purpose
			if company:
				detail_str = detail_str + '\nCompany: ' + company
			if contractor_ref:
				detail_str = detail_str + ' [' + contractor_ref + ']'

			doc = frappe.new_doc('Appointment')
			doc.customer_name = contractor_name
			doc.customer_email = ''
			doc.scheduled_time = now_str
			doc.status = 'Open'
			doc.flags.ignore_validate = True
			doc.flags.ignore_links = True
			doc.flags.ignore_mandatory = True
			doc.flags.ignore_email_alert = True
			doc.flags.ignore_send_email = True
			doc.flags.do_not_send_email = True
			doc.insert(ignore_permissions=True)
			appt_name = doc.name

			updates = {
				'customer_details': detail_str,
				'custom_visitor_type': 'Contractor',
				'custom_reporting_status': 'Checked in',
				'custom_check_in_time': now_str,
				'custom_mode_of_transport': transport,
			}
			if phone:
				updates['customer_phone_number'] = phone
			if number_plate:
				updates['custom_vehicles_number_plate'] = number_plate
			if vehicle_color:
				updates['custom_vehicles_colour'] = vehicle_color
			if passengers is not None:
				updates['custom_number_of_passengers'] = passengers
			if resolved_company:
				updates['custom_company'] = resolved_company
			if resolved_farm:
				updates['custom_farmunit'] = resolved_farm

			frappe.db.set_value('Appointment', appt_name, updates, update_modified=True)

			if contractor_ref:
				frappe.db.set_value('Appointment', appt_name, 'custom_contractor_ref', contractor_ref, update_modified=False)

		else:
			# The Server Script had `from frappe.model.workflow import
			# apply_workflow` here in try/except Exception: pass. It was DEAD
			# — safe_exec forbids every import ("ImportError: __import__ not
			# found"), so the import raised on its first line and the except
			# swallowed it on every call. No contractor check-in has ever
			# transitioned a workflow; only the custom_* fields below were
			# written.
			#
			# Porting it literally would have started running it for real,
			# because a plain module CAN import. "Confirm Check In" is a real
			# transition, so apply_workflow would call doc.save(), move
			# workflow_state to "Visitor Checked In", and fire every
			# Appointment on_update hook behind it — including
			# visitor_sms.on_appointment_update, which texts the contractor
			# an OTP. Whether it fired would depend on the guard's role and
			# the appointment's state, and a failed attempt would leave
			# partial writes for the db.commit() below to commit.
			#
			# Same removal as contractor_gate_checkout (b371f5b). Adding the
			# transition back is a deliberate feature change, not a
			# migration detail.

			updates = {
				'custom_visitor_type': 'Contractor',
				'custom_check_in_time': now_str,
				'custom_reporting_status': 'Checked in',
				'custom_mode_of_transport': transport,
			}
			if number_plate:
				updates['custom_vehicles_number_plate'] = number_plate
			if vehicle_color:
				updates['custom_vehicles_colour'] = vehicle_color
			if passengers is not None:
				updates['custom_number_of_passengers'] = passengers
			if resolved_company:
				updates['custom_company'] = resolved_company
			if resolved_farm:
				updates['custom_farmunit'] = resolved_farm

			frappe.db.set_value('Appointment', appt_name, updates, update_modified=True)
			if contractor_ref:
				frappe.db.set_value('Appointment', appt_name, 'custom_contractor_ref', contractor_ref, update_modified=False)

		frappe.db.commit()
		watchlist.track("Appointment", appt_name, "Visitor Check-in")

		return {
			'success': True,
			'appointment_name': appt_name,
			'check_in_time': now_str,
		}

	except Exception as e:
		frappe.log_error(
			title='Contractor Gate Checkin Error',
			message='User: ' + frappe.session.user + '\nError: ' + str(e)
		)
		frappe.throw('Contractor check-in failed: ' + str(e))
@frappe.whitelist()
def create_contractor_notify(
	contractor_ref=None,
	contractor_name=None,
	phone=None,
	host=None,
	purpose=None,
	plate=None,
	scope_of_work=None,
	expected_exit=None,
	transport_mode=None,
	personnel=None,
	passengers=None,
):
	"""Register a contractor arriving at the gate and notify the host + secretaries.

	WRITES Appointment (insert, then field writes), Error Log (a debug entry
	on every call), and queues/sends Email. Always creates a new
	Appointment; there is no duplicate check.

	Sequence matters: the Appointment is inserted with validation, link and
	mandatory checks bypassed (the gate must never be blocked from logging a
	contractor), then the contractor-specific fields are written with
	set_value(update_modified=False) because they are set after insert, then
	workflow_state and custom_reporting_status are set directly to
	"Pending Host Review".

	There is NO workflow transition. The Server Script wrapped
	apply_workflow(doc2, "Notify Host") in a try with this direct write as
	its fallback, but the import it needed is forbidden in safe_exec, so the
	call always raised and the fallback is all that has ever run. Do not
	"restore" the transition: it would add a doc2.save() and every
	Appointment on_update hook to an endpoint that never fired them.

	`personnel` is a JSON array of {full_name, id_number, is_team_leader}.
	Malformed or missing input just yields no personnel rows. Note the
	original stringified every value first, so an array posted as a real JSON
	list is str()'d to a Python repr, fails to parse, and is silently dropped;
	callers must send it as a JSON string. Preserved as-is.

	transport_mode from the client wins if valid; older callers that omit it
	fall back to "Vehicle" when a plate is given, else "On Foot".

	Best-effort pieces (bad `passengers`/`expected_exit`, the secretary
	lookup, sendmail) are swallowed and never fail registration. `notified`
	is the recipient count handed to sendmail, not a delivery guarantee.
	"""
	try:
		def s(v):
			if v is None:
				return ""
			return str(v).strip()

		contractor_ref = s(contractor_ref)
		contractor_name = s(contractor_name)
		phone = s(phone)
		host = s(host)
		purpose = s(purpose) or "Contractor site access"
		plate = s(plate)
		scope_of_work = s(scope_of_work)
		expected_exit_raw = s(expected_exit)
		transport_mode_in = s(transport_mode)
		personnel_raw = s(personnel)
		# Unlike the others this one is not stripped in the original.
		passengers_raw = str(passengers) if passengers is not None else ""

		personnel_rows = []
		if personnel_raw:
			try:
				parsed = frappe.utils.parse_json(personnel_raw)
				if parsed:
					for row in parsed:
						try:
							full_name = str(row["full_name"] or "").strip()
						except (KeyError, TypeError):
							full_name = ""
						if not full_name:
							continue
						try:
							id_number = str(row["id_number"] or "").strip()
						except (KeyError, TypeError):
							id_number = ""
						try:
							is_team_leader = 1 if row["is_team_leader"] else 0
						except (KeyError, TypeError):
							is_team_leader = 0
						personnel_rows.append(
							{"full_name": full_name, "id_number": id_number, "is_team_leader": is_team_leader}
						)
			except Exception:
				personnel_rows = []

		if not contractor_name and contractor_ref:
			contractor_name = frappe.db.get_value("Supplier", contractor_ref, "supplier_name") or contractor_ref

		if not contractor_name:
			return {"error": "contractor_name or contractor_ref is required"}
		if not host:
			return {"error": "host is required"}

		host_rec = frappe.db.get_value("Employee", host, ["name", "user_id", "employee_name"], as_dict=True)
		if not host_rec:
			return {"error": "Host " + host + " not found"}

		# Pre-existing debug entry: logs the whole payload (phone, personnel
		# ID numbers) into Error Log on every call.
		host_email_dbg = host_rec.user_id or ""
		frappe.log_error(
			title="create_contractor_notify debug",
			message="Payload: " + str(dict(frappe.form_dict or {})) + "\nHost: " + host + "\nHost email (user_id): " + host_email_dbg,
		)

		valid_transport_modes = ["On Foot", "Vehicle", "Motor Bike"]
		if transport_mode_in in valid_transport_modes:
			transport = transport_mode_in
		else:
			transport = "Vehicle" if plate else "On Foot"
		now_str = str(frappe.utils.now_datetime())

		doc = frappe.new_doc("Appointment")
		doc.customer_name = contractor_name
		doc.customer_email = ""
		doc.custom_meet_with = host
		doc.scheduled_time = now_str
		doc.customer_details = purpose
		doc.custom_mode_of_transport = transport
		doc.custom_vehicles_number_plate = plate
		doc.status = "Open"
		doc.custom_reporting_status = "Scheduled"
		for row in personnel_rows:
			doc.append("custom_contractor_personnel", row)
		doc.flags.ignore_validate = True
		doc.flags.ignore_links = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		appt_name = doc.name

		updates = {
			"custom_visitor_type": "Contractor",
		}
		if phone:
			updates["customer_phone_number"] = phone
		if contractor_ref:
			updates["custom_contractor_ref"] = contractor_ref
		if passengers_raw:
			try:
				updates["custom_number_of_passengers"] = int(passengers_raw)
			except Exception:
				pass
		if scope_of_work:
			updates["custom_scope_of_work"] = scope_of_work
		if expected_exit_raw:
			try:
				updates["custom_expected_exit"] = frappe.utils.get_datetime(expected_exit_raw)
			except Exception:
				pass
		frappe.db.set_value("Appointment", appt_name, updates, update_modified=False)

		# The Server Script wrapped `apply_workflow(doc2, "Notify Host")` in
		# try/except with this set_value as the fallback. The import it
		# needed is forbidden in safe_exec, so the call always raised and the
		# fallback is what has always run.
		#
		# The port carried the call across without an import, so it raised
		# NameError instead and the fallback still ran — accidentally
		# correct, but a trap: anyone "fixing" the undefined name, or adding
		# a module-level import, would silently make a workflow transition
		# and a doc2.save() live, firing every Appointment on_update hook.
		# The direct write is now the only path, matching
		# create_walk_in_notify and notify_host.
		frappe.db.set_value(
			"Appointment",
			appt_name,
			{
				"workflow_state": "Pending Host Review",
				"custom_reporting_status": "Pending Host Review",
			},
		)
		frappe.db.commit()

		host_user_id = host_rec.user_id or ""
		host_name = host_rec.employee_name or host
		recipient_users = []
		if host_user_id:
			recipient_users.append(host_user_id)

		try:
			sec_rows = frappe.db.sql(
				"SELECT DISTINCT parent FROM `tabHas Role` WHERE role = 'Secretary' AND parent NOT IN ('Administrator', 'Guest')",
				as_dict=False,
			)
			for row in sec_rows:
				if row and row[0] and row[0] not in recipient_users:
					recipient_users.append(row[0])
		except Exception:
			pass

		subject = "Contractor: " + contractor_name + " at the gate to see " + host_name
		body = "<p><strong>" + contractor_name + "</strong> (contractor) has arrived at the gate to see <strong>" + host_name + "</strong></p>"
		if purpose:
			body = body + "<p>Purpose: " + purpose + "</p>"
		if plate:
			body = body + "<p>Vehicle: " + plate + "</p>"
		body = body + "<p>Please <strong>approve, reschedule, or reject</strong> this visit in ERPNext.</p>"

		notified = 0
		if recipient_users:
			try:
				frappe.sendmail(
					recipients=recipient_users,
					subject=subject,
					message=body,
					now=True,
				)
				notified = len(recipient_users)
			except Exception:
				pass

		return {
			"name": appt_name,
			"customer_name": contractor_name,
			"host_id": host,
			"workflow_state": "Pending Host Review",
			"notified": notified,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("create_contractor_notify", str(e))
		return {"error": str(e)}


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


@frappe.whitelist()
def issue_visitor_badge(name=None, badge_number=None):
	"""Link a pre-printed physical Visitor Badge to an Appointment.

	The badge's QR is fixed (company + farm + badge number); issuing is only a
	server-side pointer (current_appointment), never a per-visit code.

	The company/farm pool is resolved from the caller (Employee first, then
	Security Guard matched by full name since that doctype has no user_id),
	falling back to the visit host's company/farm for admin accounts. Each farm
	has its own badge stock, so both dimensions are required.

	The status check and the write are not atomic. The badge is saved as a full
	document (not db.set_value) so Frappe's modified-timestamp check raises
	TimestampMismatchError when two guards issue the same badge at once, and the
	loser gets a clear error. Do not "simplify" to set_value.

	The feature-flag raise is deliberately INSIDE the try: a disabled feature
	soft-fails through the except (rollback + Error Log + {"error"}), as the
	original did.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_visitor_badges") == 0:
			raise Exception("This feature is not enabled on this instance.")

		name = str(name or "").strip()
		badge_number_raw = str(badge_number) if badge_number is not None else ""

		if not name:
			return {"error": "name is required"}
		if not badge_number_raw:
			return {"error": "badge_number is required"}

		appt = frappe.db.get_value("Appointment", name, ["name", "custom_visitor_badge"], as_dict=True)
		if not appt:
			return {"error": "Appointment " + name + " not found"}

		try:
			badge_number = int(badge_number_raw)
		except Exception:
			badge_number = None

		if badge_number is None:
			return {"error": "badge_number must be a number"}

		current_user = frappe.session.user
		company = ""
		farm = ""
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

		if not company or not farm:
			host = frappe.db.get_value("Appointment", name, "custom_meet_with")
			if host:
				host_employee = frappe.db.get_value(
					"Employee", host, ["company", "custom_farm"], as_dict=True
				)
				if host_employee:
					if not company:
						company = host_employee.company or ""
					if not farm:
						farm = host_employee.custom_farm or ""

		if not company or not farm:
			return {
				"error": "Could not determine which company/farm badge pool to use "
				"— no Employee or Security Guard record linked to this user "
				"with both set, and this visit's host has no fallback for "
				"whichever is still missing"
			}

		badge = frappe.db.get_value(
			"Visitor Badge",
			{"company": company, "farm": farm, "badge_number": badge_number},
			["name", "status", "current_appointment"],
			as_dict=True,
		)
		if not badge:
			return {
				"error": "Badge "
				+ str(badge_number)
				+ " does not exist for "
				+ company
				+ " / "
				+ farm
			}
		if badge.status == "Issued" and badge.current_appointment != name:
			return {
				"error": "Badge "
				+ str(badge_number)
				+ " ("
				+ company
				+ " / "
				+ farm
				+ ") is already issued to another visit ("
				+ str(badge.current_appointment)
				+ ")"
			}

		badge_doc = frappe.get_doc("Visitor Badge", badge.name)
		badge_doc.status = "Issued"
		badge_doc.current_appointment = name
		try:
			badge_doc.save(ignore_permissions=True)
		except frappe.TimestampMismatchError:
			return {
				"error": "Badge "
				+ str(badge_number)
				+ " ("
				+ company
				+ " / "
				+ farm
				+ ") was just issued to another visit — rescan or pick a different badge."
			}

		frappe.db.set_value("Appointment", name, "custom_visitor_badge", badge.name)
		frappe.db.commit()
		return {
			"badge_number": badge_number,
			"company": company,
			"farm": farm,
			"confirm_url": frappe.utils.get_url()
			+ "/visitor-received?company="
			+ company.replace(" ", "%20")
			+ "&farm="
			+ farm.replace(" ", "%20")
			+ "&badge="
			+ str(badge_number),
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("issue_visitor_badge", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def update_supplier_badge(name=None, supplier=None, company=None, status=None):
	"""Edit a Supplier Badge from the Command Center badge screen; also the
	"issue a badge" verb (supplier + company + status=Issued on an Available badge).

	Strictly Security Head / System Manager by role, no allowlist. Roles are read
	from tabHas Role directly (as the original did), not frappe.get_roles.

	Only fields PRESENT in the request are applied, and a present-but-null value
	is applied (it clears the field). Python defaults cannot tell "absent" from
	"null", so presence is also detected via frappe.form_dict keys. Load-bearing:
	do not reduce to `if supplier is not None`.

	qr_image is never touched here. Valid statuses mirror Supplier Badge's Select
	options (same three as Visitor Badge).

	The inner except returns the save error WITHOUT logging it, as the original
	did; only the outer except logs.
	"""
	try:
		current_user = frappe.session.user
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (current_user,)
		)
		roles = []
		for row in role_rows:
			if row and row[0]:
				roles.append(row[0])
		has_access = "Security Head" in roles or "System Manager" in roles

		if not has_access:
			return {"error": "You do not have access to this action."}

		name = str(name or "").strip()

		if not name:
			return {"error": "name is required"}
		if not frappe.db.exists("Supplier Badge", name):
			return {"error": "Supplier Badge not found."}

		valid_statuses = ("Available", "Issued", "Lost")

		sent = frappe.form_dict or {}
		has_supplier = supplier is not None or "supplier" in sent
		has_company = company is not None or "company" in sent
		has_status = status is not None or "status" in sent

		if has_status and status not in valid_statuses:
			return {"error": "Invalid status."}

		doc = frappe.get_doc("Supplier Badge", name)
		applied = False
		if has_supplier:
			doc.supplier = supplier
			applied = True
		if has_company:
			doc.company = company
			applied = True
		if has_status:
			doc.status = status
			applied = True

		if not applied:
			return {"error": "No updatable fields were sent"}

		try:
			doc.save(ignore_permissions=True)
			frappe.db.commit()

			supplier_name = ""
			if doc.supplier:
				supplier_name = frappe.db.get_value("Supplier", doc.supplier, "supplier_name") or ""

			return {
				"success": True,
				"name": doc.name,
				"badge_number": doc.badge_number,
				"supplier": doc.supplier or "",
				"supplier_name": supplier_name,
				"company": doc.company or "",
				"status": doc.status,
			}
		except Exception as e:
			frappe.db.rollback()
			return {"error": str(e)}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("update_supplier_badge", str(e))
		return {"error": str(e)}


@frappe.whitelist(allow_guest=True)
def get_visitor_badge_info(company=None, farm=None, badge_number=None):
	"""QR-scan lookup of the visit currently holding a Visitor Badge.

	allow_guest=True is load-bearing: the scanner is a visitor/host with no
	login, and a 403 here makes the mobile client treat it as a dead session
	and log the user out. Keyed by company+farm+badge_number because an
	anonymous caller has no login to resolve a company from.

	No feature flag (unlike confirm_host_received). Errors are returned at
	HTTP 200 as {"error": ...}, never raised. A scan of an unassigned badge
	also logs an Invalid Badge Scan via log_unauthorized_access; a failure of
	that logging is deliberately swallowed so it can never mask the response.
	"""
	try:
		company = str(company or "").strip()
		farm = str(farm or "").strip()
		badge_number_raw = str(badge_number) if badge_number is not None else ""

		if not company:
			return {"error": "company is required"}
		elif not farm:
			return {"error": "farm is required"}
		elif not badge_number_raw:
			return {"error": "badge_number is required"}
		else:
			try:
				badge_number = int(badge_number_raw)
			except Exception:
				badge_number = None

			if badge_number is None:
				return {"error": "badge_number must be a number"}
			else:
				badge = frappe.db.get_value(
					"Visitor Badge",
					{"company": company, "farm": farm, "badge_number": badge_number},
					["current_appointment", "status"],
					as_dict=True,
				)
				if not badge or not badge.current_appointment:
					try:
						frappe.call(
							"upande_security.api.security_alerts.log_unauthorized_access",
							attempt_type="Invalid Badge Scan",
							reference=str(badge_number),
							detail="Badge " + str(badge_number) + " (" + company + " / " + farm + ") scanned but not currently assigned to any visitor.",
							company=company,
							farm=farm,
						)
					except Exception:
						pass
					return {
						"error": "Badge "
						+ str(badge_number)
						+ " ("
						+ company
						+ " / "
						+ farm
						+ ") is not currently assigned to any visitor."
					}
				else:
					appt = frappe.db.get_value(
						"Appointment",
						badge.current_appointment,
						["name", "customer_name", "custom_meet_with", "custom_host_received_time", "customer_details"],
						as_dict=True,
					)
					if not appt:
						return {
							"error": "Badge "
							+ str(badge_number)
							+ " points to a visit that no longer exists."
						}
					else:
						host_name = (
							frappe.db.get_value("Employee", appt.custom_meet_with, "employee_name")
							or appt.custom_meet_with
							or ""
						)
						return {
							"badge_number": badge_number,
							"company": company,
							"farm": farm,
							"visitor_name": appt.customer_name or "",
							"host_name": host_name,
							"purpose": appt.customer_details or "",
							"already_confirmed": bool(appt.custom_host_received_time),
							"confirmed_at": str(appt.custom_host_received_time)
							if appt.custom_host_received_time
							else None,
						}
	except Exception as e:
		frappe.log_error("get_visitor_badge_info", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def get_visitor_badge_info_by_number(badge_number=None):
	"""Desk counterpart of get_visitor_badge_info for a logged-in host who
	types only the number printed on the card.

	Deliberately NOT allow_guest: a Guest caller is rejected outright. The
	company (and farm) are resolved from the caller's own Employee record
	(Employee.user_id == session user). If the host has a company but no
	custom_farm (group-level role), the lookup spans every farm under the
	company and takes the first badge that is actually assigned to a visit.
	That path uses frappe.db.get_all (not frappe.get_all), as the original did.

	No feature flag. Unassigned lookups log an Invalid Badge Scan; logging
	failures are swallowed.
	"""
	try:
		badge_number_raw = str(badge_number) if badge_number is not None else ""

		if not badge_number_raw:
			return {"error": "badge_number is required"}
		else:
			try:
				badge_number = int(badge_number_raw)
			except Exception:
				badge_number = None

			if badge_number is None:
				return {"error": "badge_number must be a number"}
			else:
				current_user = frappe.session.user
				employee = frappe.db.get_value(
					"Employee", {"user_id": current_user}, ["company", "custom_farm"], as_dict=True
				)
				company = employee.company if employee else ""
				farm = employee.custom_farm if employee else ""

				if not company:
					return {
						"error": "No Employee record linked to this login — cannot determine your company."
					}
				else:
					badge = None
					if farm:
						badge = frappe.db.get_value(
							"Visitor Badge",
							{"company": company, "farm": farm, "badge_number": badge_number},
							["current_appointment", "status", "farm"],
							as_dict=True,
						)
					else:
						candidates = frappe.db.get_all(
							"Visitor Badge",
							filters={"company": company, "badge_number": badge_number},
							fields=["current_appointment", "status", "farm"],
						)
						for c in candidates:
							if c.current_appointment:
								badge = c
								break

					if not badge or not badge.current_appointment:
						try:
							frappe.call(
								"upande_security.api.security_alerts.log_unauthorized_access",
								attempt_type="Invalid Badge Scan",
								reference=str(badge_number),
								detail="Badge " + str(badge_number) + " (" + company + (" / " + farm if farm else "") + ") looked up but not currently assigned to any visitor.",
								company=company,
								farm=farm,
							)
						except Exception:
							pass
						return {
							"error": "Badge "
							+ str(badge_number)
							+ " ("
							+ company
							+ (" / " + farm if farm else "")
							+ ") is not currently assigned to any visitor."
						}
					else:
						appt = frappe.db.get_value(
							"Appointment",
							badge.current_appointment,
							[
								"name",
								"customer_name",
								"custom_meet_with",
								"custom_host_received_time",
								"customer_details",
							],
							as_dict=True,
						)
						if not appt:
							return {
								"error": "Badge "
								+ str(badge_number)
								+ " points to a visit that no longer exists."
							}
						else:
							host_name = (
								frappe.db.get_value("Employee", appt.custom_meet_with, "employee_name")
								or appt.custom_meet_with
								or ""
							)
							return {
								"badge_number": badge_number,
								"company": company,
								"farm": badge.farm or farm,
								"visitor_name": appt.customer_name or "",
								"host_name": host_name,
								"purpose": appt.customer_details or "",
								"already_confirmed": bool(appt.custom_host_received_time),
								"confirmed_at": str(appt.custom_host_received_time)
								if appt.custom_host_received_time
								else None,
							}
	except Exception as e:
		frappe.log_error("get_visitor_badge_info_by_number", str(e))
		return {"error": str(e)}
@frappe.whitelist(allow_guest=True)
def get_supplier_badge_info(badge=None):
	"""QR-scan lookup of a Supplier Badge, keyed by the Supplier Badge doc
	name (the "badge" param) rather than company+number.

	allow_guest=True is load-bearing: anonymous QR scan; a 403 logs the
	mobile user out. No feature flag. Read-only. "supplier_name" falls back to
	the Supplier link value when supplier_name is empty.
	"""
	try:
		badge_name = str(badge or "").strip()

		if not badge_name:
			return {"error": "badge is required"}
		else:
			badge = frappe.db.get_value(
				"Supplier Badge",
				badge_name,
				["name", "company", "supplier", "badge_number", "status"],
				as_dict=True,
			)
			if not badge:
				return {"error": "No Supplier Badge found for that reference."}
			else:
				supplier_name = ""
				if badge.supplier:
					supplier_name = frappe.db.get_value("Supplier", badge.supplier, "supplier_name") or badge.supplier

				return {
					"badge_number": badge.badge_number,
					"company": badge.company,
					"supplier_name": supplier_name,
					"status": badge.status,
				}
	except Exception as e:
		frappe.log_error("get_supplier_badge_info", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def issue_supplier_badge(name=None, badge_number=None):
	"""Assign a physical Supplier Badge (by number) to a contractor/supplier
	Appointment. Gated by feature_supplier_badges.

	Badge pool company resolution order matches issue_visitor_badge: Employee
	linked to this login, then Security Guard matched by the User's full name,
	then the Appointment's own custom_company (stamped at contractor check-in).

	The badge is a reusable physical object: "supplier" is a snapshot of the
	current holder, not a permanent assignment. The badge is loaded and saved
	as a doc (not a raw set_value) for optimistic concurrency, so two guards
	issuing the same number simultaneously cannot both succeed; the loser gets
	a TimestampMismatchError, returned as an error. NOTE: that branch returns
	without rollback or commit, exactly as the original did.

	A badge already Issued to this same appointment is re-issuable (idempotent).
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_supplier_badges") == 0:
			raise Exception("This feature is not enabled on this instance.")

		name = str(name or "").strip()
		badge_number_raw = str(badge_number) if badge_number is not None else ""

		if not name:
			return {"error": "name is required"}
		elif not badge_number_raw:
			return {"error": "badge_number is required"}
		else:
			appt = frappe.db.get_value(
				"Appointment",
				name,
				["name", "custom_supplier_badge", "custom_contractor_ref", "custom_company"],
				as_dict=True,
			)
			if not appt:
				return {"error": "Appointment " + name + " not found"}
			else:
				try:
					badge_number = int(badge_number_raw)
				except Exception:
					badge_number = None

				if badge_number is None:
					return {"error": "badge_number must be a number"}
				else:
					current_user = frappe.session.user
					company = ""
					employee = frappe.db.get_value(
						"Employee", {"user_id": current_user}, "company"
					)
					if employee:
						company = employee
					else:
						user_full = frappe.db.get_value("User", current_user, "full_name") or ""
						if user_full:
							guard_company = frappe.db.get_value(
								"Security Guard", {"full_name": user_full}, "company"
							)
							if guard_company:
								company = guard_company

					if not company:
						company = appt.custom_company or ""

					if not company:
						return {
							"error": "Could not determine which company badge pool to use "
							"- no Employee or Security Guard record linked to this user, "
							"and this visit has no custom_company fallback either"
						}
					else:
						badge = frappe.db.get_value(
							"Supplier Badge",
							{"company": company, "badge_number": badge_number},
							["name", "status", "current_appointment"],
							as_dict=True,
						)
						if not badge:
							return {
								"error": "Badge " + str(badge_number) + " does not exist for " + company
							}
						elif badge.status == "Issued" and badge.current_appointment != name:
							return {
								"error": "Badge "
								+ str(badge_number)
								+ " ("
								+ company
								+ ") is already issued to another visit ("
								+ str(badge.current_appointment)
								+ ")"
							}
						else:
							badge_doc = frappe.get_doc("Supplier Badge", badge.name)
							badge_doc.status = "Issued"
							badge_doc.current_appointment = name
							badge_doc.supplier = appt.custom_contractor_ref or badge_doc.supplier
							try:
								badge_doc.save(ignore_permissions=True)
							except frappe.TimestampMismatchError:
								return {
									"error": "Badge "
									+ str(badge_number)
									+ " ("
									+ company
									+ ") was just issued to another visit - rescan or pick a different badge."
								}
							else:
								frappe.db.set_value("Appointment", name, "custom_supplier_badge", badge.name)
								frappe.db.commit()
								return {
									"badge_number": badge_number,
									"company": company,
									"supplier": badge_doc.supplier or "",
								}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("issue_supplier_badge", str(e))
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


@frappe.whitelist()
def create_staff_attendance(employee=None, vehicle_plate=None, entry_gate=None):
	"""Record a staff member entering the gate.

	Behaviour depends on the per-company "Staff Gate Mode" row in Security Ops
	Settings: "Mark Attendance" (default, also used when the company has no
	row, so nothing changes until someone opts in) inserts an HR Attendance
	draft; "Movement Log Only" inserts a Staff Gate Movement instead, leaving
	attendance to HR. The mobile client submits straight after creating and
	treats any failure as fatal, so the movement branch still returns
	docstatus=1 even though movement rows are not submittable.

	A client-supplied entry_gate wins over the roster-derived one, leaving room
	for a gate picker later.

	The Attendance is inserted with ignore_permissions because Gate Guards have
	no create permission on it; the endpoint is the permission boundary.

	Errors are soft ({"error": ...} at HTTP 200); the feature-flag raise is
	deliberately INSIDE the try so a disabled feature also rolls back, logs and
	soft-fails rather than throwing.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_staff_checkin") == 0:
			raise Exception("This feature is not enabled on this instance.")

		employee = str(employee or "").strip()
		vehicle_plate = str(vehicle_plate or "").strip()
		entry_gate = str(entry_gate or "").strip()

		if not entry_gate:
			entry_gate = _sp_gate_from_roster()

		if not employee:
			return {"error": "employee is required"}

		emp = frappe.db.get_value(
			"Employee",
			employee,
			[
				"name",
				"employee_name",
				"company",
				"department",
				"default_shift",
				"custom_farm",
				"employee_category",
				"status",
			],
			as_dict=True,
		)
		if not emp:
			return {"error": "Employee " + employee + " not found"}
		if emp.status and emp.status != "Active":
			return {"error": "Employee status is " + str(emp.status)}

		today = frappe.utils.today()
		gate_mode = "Mark Attendance"
		if emp.company:
			configured = frappe.db.get_value(
				"Staff Gate Mode",
				{"parent": "Security Ops Settings", "company": emp.company},
				"mode",
			)
			if configured:
				gate_mode = configured

		if gate_mode == "Movement Log Only":
			duplicate = frappe.db.get_value(
				"Staff Gate Movement",
				{"employee": employee, "movement_date": today, "time_out": ["is", "not set"]},
				"name",
			)
			if duplicate:
				return {
					"error": "This person is already signed in",
					"existing": duplicate,
				}
			mv = frappe.new_doc("Staff Gate Movement")
			mv.employee = emp.name
			mv.employee_name = emp.employee_name
			mv.company = emp.company
			mv.movement_date = today
			in_clock = frappe.utils.nowtime()
			mv.time_in = in_clock
			# Where the movement happened - the guard's farm - not where the
			# employee normally works.
			from upande_security.api.gate_vehicle import _resolve_checking_farm

			mv.farm = _resolve_checking_farm(frappe.session.user) or emp.custom_farm
			if vehicle_plate:
				mv.vehicle_plate = vehicle_plate
			from upande_security.api.gate_movement import resolve_gate

			mv.entry_gate = resolve_gate(entry_gate, mv.farm) if mv.farm else entry_gate
			mv.recorded_by = frappe.session.user
			mv.insert(ignore_permissions=True)
			frappe.db.commit()
			return {
				"name": mv.name,
				"employee": emp.name,
				"employee_name": emp.employee_name or "",
				"status": "Movement",
				"in_time": str(today) + " " + str(in_clock),
				"docstatus": 1,
			}

		duplicate = frappe.db.get_value(
			"Attendance",
			{"employee": employee, "attendance_date": today, "docstatus": ["<", 2]},
			"name",
		)
		if duplicate:
			return {
				"error": "Attendance already exists for today",
				"existing": duplicate,
			}
		now = frappe.utils.now_datetime()
		doc = frappe.new_doc("Attendance")
		doc.naming_series = "HR-ATT-.YYYY.-"
		doc.employee = emp.name
		doc.employee_name = emp.employee_name
		doc.status = "Present"
		doc.attendance_date = today
		doc.in_time = now
		if emp.company:
			doc.company = emp.company
		if emp.department:
			doc.department = emp.department
		if emp.default_shift:
			doc.shift = emp.default_shift
		if emp.custom_farm:
			doc.custom_farm = emp.custom_farm
		if emp.employee_category:
			doc.custom_employee_category = emp.employee_category
		if vehicle_plate:
			doc.custom_vehicle_number_plate = vehicle_plate
		if entry_gate:
			doc.custom_entry_gate = entry_gate
		doc.custom_gate_app_entry = 1
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return {
			"name": doc.name,
			"employee": emp.name,
			"employee_name": emp.employee_name or "",
			"status": "Present",
			"in_time": str(now),
			"docstatus": doc.docstatus,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("create_staff_attendance", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def submit_staff_attendance(name=None):
	"""Submit the Attendance draft created by create_staff_attendance.

	Staff Gate Movement rows are not submittable, but the client always calls
	this right after create and treats any failure as fatal - so a movement
	name reports success ("nothing to submit") instead of "not found". That
	check must stay ahead of the Attendance lookup.

	Gate Guards only have a draft to submit because create used
	insert(ignore_permissions=True); the Attendance DocPerm table never grants
	their role "submit" (only System Manager/HR User/HR Manager). Without
	flags.ignore_permissions here every plain Gate Guard check-in hit
	PermissionError, was caught below, and left a committed draft at
	docstatus=0 forever. Load-bearing.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_staff_checkin") == 0:
			raise Exception("This feature is not enabled on this instance.")

		name = str(name or "").strip()

		if not name:
			return {"error": "name is required"}
		if frappe.db.exists("Staff Gate Movement", name):
			return {
				"name": name,
				"docstatus": 1,
				"message": "movement log entry - nothing to submit",
			}
		existing = frappe.db.get_value("Attendance", name, ["name", "docstatus"], as_dict=True)
		if not existing:
			return {"error": "Attendance " + name + " not found"}
		if int(existing.docstatus or 0) == 1:
			return {
				"name": name,
				"docstatus": 1,
				"message": "already submitted",
			}
		doc = frappe.get_doc("Attendance", name)
		doc.flags.ignore_permissions = True
		doc.submit()
		frappe.db.commit()
		return {
			"name": doc.name,
			"docstatus": doc.docstatus,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("submit_staff_attendance", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def staff_gate_checkout(attendance_name=None, exit_gate=None):
	"""Close a staff gate record opened by create_staff_attendance.

	One endpoint closes both kinds of record: the client only holds the name it
	was given at check-in and does not know which mode the company is on, so a
	Staff Gate Movement is tried first, then Attendance.

	Writes with frappe.db.set_value rather than doc.save: Attendance may
	already be submitted and set_value bypasses submitted-doc edit rules and
	permissions (the endpoint is the permission boundary). Movement time_in is
	a clock time, so working hours are computed by pairing it with the row's
	own movement_date. Attendance writes working_hours; Movement does not store
	it but still returns it.

	The `.strip()` calls run on the raw value, so a non-string attendance_name
	raises AttributeError into the except and soft-fails; preserved.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_staff_checkin") == 0:
			raise Exception("This feature is not enabled on this instance.")

		attendance_name = (attendance_name or "").strip()
		exit_gate = (exit_gate or "").strip()

		if not exit_gate:
			exit_gate = _sp_gate_from_roster()

		if not attendance_name:
			return {"error": "attendance_name is required"}

		movement = frappe.db.get_value(
			"Staff Gate Movement",
			attendance_name,
			["name", "movement_date", "time_in", "time_out", "farm"],
			as_dict=True,
		)
		existing = None
		if not movement:
			existing = frappe.db.get_value(
				"Attendance", attendance_name, ["name", "in_time", "out_time"], as_dict=True
			)

		if movement and movement.time_out is not None:
			return {"error": attendance_name + " is already checked out"}
		if movement:
			now_dt = frappe.utils.now_datetime()
			now_str = frappe.utils.get_datetime_str(now_dt)
			working_hours = None
			if movement.time_in and movement.movement_date:
				try:
					in_stamp = str(movement.movement_date) + " " + str(movement.time_in)
					delta = now_dt - frappe.utils.get_datetime(in_stamp)
					working_hours = round(delta.total_seconds() / 3600, 2)
				except Exception:
					working_hours = None
			out_parts = now_str.split(" ")
			out_clock = out_parts[1] if len(out_parts) > 1 else now_str
			mv_updates = {"time_out": out_clock}
			if movement.farm:
				from upande_security.api.gate_movement import resolve_gate

				exit_gate = resolve_gate(exit_gate, movement.farm)
			if exit_gate:
				mv_updates["exit_gate"] = exit_gate
			frappe.db.set_value(
				"Staff Gate Movement", attendance_name, mv_updates, update_modified=True
			)
			frappe.db.commit()
			watchlist.track("Staff Gate Movement", attendance_name, "Staff Check-out")
			return {
				"success": True,
				"attendance_name": attendance_name,
				"out_time": now_str,
				"working_hours": working_hours,
			}
		if not existing:
			return {"error": "Attendance " + attendance_name + " not found"}
		if existing.out_time:
			return {"error": attendance_name + " is already checked out"}

		now_dt = frappe.utils.now_datetime()
		now_str = frappe.utils.get_datetime_str(now_dt)

		working_hours = None
		if existing.in_time:
			try:
				in_dt = frappe.utils.get_datetime(existing.in_time)
				delta = now_dt - in_dt
				working_hours = round(delta.total_seconds() / 3600, 2)
			except Exception:
				working_hours = None

		updates = {"out_time": now_str}
		if working_hours is not None:
			updates["working_hours"] = working_hours
		if exit_gate:
			updates["custom_exit_gate"] = exit_gate

		frappe.db.set_value("Attendance", attendance_name, updates, update_modified=True)
		frappe.db.commit()
		watchlist.track("Attendance", attendance_name, "Staff Check-out")

		return {
			"success": True,
			"attendance_name": attendance_name,
			"out_time": now_str,
			"working_hours": working_hours,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("staff_gate_checkout", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def list_staff_movements(from_date=None, to_date=None):
	"""Staff Gate Movement list for a date range, newest first.

	Gated by the feature_staff_checkin flag in Security Ops Settings. The
	disabled case is raised INSIDE the try on purpose, so it is caught, logged
	via log_error and returned as {"error": "This feature is not enabled on this
	instance."} at HTTP 200 -- not a thrown HTTP error. Only an explicit 0
	disables it (an unset/None value counts as enabled).

	to_date defaults to today, from_date to to_date - 30 days.

	Scoping is the same as the gate app: System Manager sees everything, a
	Security Head sees their User Permission grants, anyone else is pinned to
	their own company/farm. UNLIKE list_patrol_reports, company and farm are NOT
	OR-ed: if any company scope exists it wins and farm scope is ignored (elif).
	With no scope at all the filter is name = "__no_match__" (show nothing).
	Load bearing.

	time_in/time_out are clock times, so each is joined with the row's own
	movement_date into a full "YYYY-MM-DD HH:MM:SS" string for the client.
	Unpaginated (limit_page_length=0). Read-only.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_staff_checkin") == 0:
			raise Exception("This feature is not enabled on this instance.")

		to_date = (to_date or "").strip() or frappe.utils.today()
		from_date = (from_date or "").strip()
		if not from_date:
			from_date = frappe.utils.add_days(to_date, -30)

		current_user = frappe.session.user
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (current_user,)
		)
		roles = []
		for row in role_rows:
			if row and row[0]:
				roles.append(row[0])

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

		rows = []

		mv_filters = [
			["movement_date", ">=", from_date],
			["movement_date", "<=", to_date],
		]
		if not is_system_manager:
			if scope_companies:
				mv_filters.append(["company", "in", scope_companies])
			elif scope_farms:
				mv_filters.append(["farm", "in", scope_farms])
			else:
				mv_filters.append(["name", "=", "__no_match__"])

		for m in frappe.get_all(
			"Staff Gate Movement",
			filters=mv_filters,
			fields=[
				"name",
				"employee",
				"employee_name",
				"company",
				"farm",
				"movement_date",
				"time_in",
				"time_out",
				"vehicle_plate",
				"entry_gate",
				"exit_gate",
				"party_type",
				"contractor",
				"contractor_badge",
			],
			order_by="movement_date desc, time_in desc",
			limit_page_length=0,
		):
			day = str(m["movement_date"] or "")
			in_stamp = None
			if m["time_in"]:
				in_stamp = day + " " + str(m["time_in"])
			out_stamp = None
			if m["time_out"]:
				out_stamp = day + " " + str(m["time_out"])
			rows.append(
				{
					"name": m["name"],
					"employee": m["employee"],
					"employee_name": m["employee_name"],
					"company": m["company"],
					"farm": m["farm"],
					"date": day,
					"in_time": in_stamp,
					"out_time": out_stamp,
					"plate": m["vehicle_plate"],
					"entry_gate": m["entry_gate"],
					"exit_gate": m["exit_gate"],
					# Staff, or a contractor recorded by a badge scan.
					"party_type": m["party_type"] or "Staff",
					"contractor": (
						frappe.db.get_value("Supplier", m["contractor"], "supplier_name") or m["contractor"]
					)
					if m["contractor"]
					else None,
					"badge": frappe.db.get_value("Contractor Badge", m["contractor_badge"], "badge_number")
					if m["contractor_badge"]
					else None,
				}
			)

		return {"staff": rows}
	except Exception as e:
		frappe.log_error("list_staff_movements", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def list_active_gates_for_farm(farm=None):
	"""Active gate names configured for a farm, in configured order.

	Security Gate Config is a child table of Security Ops Settings with an empty
	permissions array (it relies on the parent's DocPerm when viewed through
	that form), so querying it as a real user fails with "Insufficient
	Permission" -- Administrator bypasses permission checks, which is why this
	slipped through local testing. Gate names for a farm are not sensitive, so
	ignore_permissions=True is deliberate, not lazy.

	Missing farm returns {"gates": []}; an error returns {"gates": [], "error": ...}
	(the empty list is part of the contract so a gate-picker can still render).
	Read-only.
	"""
	try:
		if not farm:
			return {"gates": []}

		rows = frappe.get_all(
			"Security Gate Config",
			filters={"parent": "Security Ops Settings", "farm": farm, "active": 1},
			fields=["gate_name"],
			order_by="idx asc",
			ignore_permissions=True,
		)
		names = []
		for row in rows:
			if row.gate_name:
				names.append(row.gate_name)
		return {"gates": names}
	except Exception as e:
		frappe.log_error("list_active_gates_for_farm", str(e))
		return {"gates": [], "error": str(e)}


# =============================================================================
# SECTION 6   PATROLS
# =============================================================================


@frappe.whitelist()
def submit_patrol_points():
	"""Batch-insert Patrol GPS Log rows. Returns a LIST of per-point results.

	Takes no named parameters on purpose: the client posts a bare JSON array
	(or a single object, or form-encoded fields) and the body is read directly
	from frappe.request. Frappe wraps a non-dict JSON body in form_dict as
	{"data": [...], "cmd": ...}, and the original also unwraps a {"data": [...]}
	dict - both forms are handled, then form_dict is the last resort. The
	list-ness probe (`raw[0]`) is kept as-is, quirks included: a JSON string
	body counts as a "list" and an empty list falls through to [raw].

	Guard identity comes from the session user, never the payload: Employee by
	user_id, else Security Guard by user, else Security Guard by full_name
	(legacy, fragile, kept until every guard has a User link). The payload's
	"guard" key is read but only ever used as a fallback that cannot trigger,
	because resolved_guard always ends up non-empty.

	Farm is resolved once per batch from the guard's Active shift, falling back
	to the farm on their own master record. The fallback is NOT an edge case:
	external guards (most patrol traffic) never have external_guard set on a
	shift assignment, so without it every point had a blank farm and the Patrol
	Map's farm filter made them vanish.

	Duplicates (same patrol + captured_at) report success so the client can
	clear its offline queue. Commit happens only if at least one row inserted;
	otherwise rollback. A per-row failure is logged and reported without
	aborting the batch.
	"""
	try:
		raw = None
		try:
			raw = frappe.request.get_json(silent=True)
		except Exception:
			raw = None

		data_list = []
		if raw is not None:
			is_list = False
			try:
				probe = raw[0]
				is_list = True
			except Exception:
				is_list = False
			if is_list:
				data_list = raw
			else:
				wrapped = _sp_lookup(raw, "data")
				wrapped_is_list = False
				if wrapped is not None:
					try:
						probe2 = wrapped[0]
						wrapped_is_list = True
					except Exception:
						wrapped_is_list = False
				if wrapped_is_list:
					data_list = wrapped
				else:
					data_list = [raw]
		if not data_list:
			f = dict(frappe.form_dict or {})
			wrapped_fd = _sp_lookup(f, "data")
			wrapped_fd_is_list = False
			if wrapped_fd is not None:
				try:
					probe3 = wrapped_fd[0]
					wrapped_fd_is_list = True
				except Exception:
					wrapped_fd_is_list = False
			if wrapped_fd_is_list:
				data_list = wrapped_fd
			elif f:
				data_list = [f]

		if not data_list:
			return [{"status": "error", "message": "GPS data missing"}]

		results = []
		any_success = False
		current_user = frappe.session.user

		user_full = ""
		try:
			user_full = frappe.db.get_value("User", current_user, "full_name") or ""
		except Exception:
			user_full = ""

		resolved_type = ""
		resolved_guard = ""
		emp = frappe.db.get_value("Employee", {"user_id": current_user}, "name")
		if emp:
			resolved_type = "Employee"
			resolved_guard = emp
		else:
			sg = frappe.db.get_value("Security Guard", {"user": current_user}, "name")
			if not sg and user_full:
				sg = frappe.db.get_value("Security Guard", {"full_name": user_full}, "name")
			if sg:
				resolved_type = "Security Guard"
				resolved_guard = sg

		if not resolved_guard:
			resolved_guard = user_full or current_user

		resolved_farm = ""
		try:
			if resolved_type == "Employee":
				resolved_farm = frappe.db.get_value(
					"Security Guard Shift Assignment",
					{"internal_guard": resolved_guard, "status": "Active"},
					"farm",
				) or ""
				if not resolved_farm:
					resolved_farm = frappe.db.get_value(
						"Employee", resolved_guard, "custom_farm"
					) or ""
			elif resolved_type == "Security Guard":
				resolved_farm = frappe.db.get_value(
					"Security Guard Shift Assignment",
					{"external_guard": resolved_guard, "status": "Active"},
					"farm",
				) or ""
				if not resolved_farm:
					resolved_farm = frappe.db.get_value(
						"Security Guard", resolved_guard, "farm"
					) or ""
		except Exception:
			resolved_farm = ""

		for entry in data_list:
			try:
				patrol_tag = str(_sp_lookup(entry, "patrol_tag") or "").strip()
				if not patrol_tag:
					patrol_tag = str(_sp_lookup(entry, "patrol") or "").strip()

				guard_code = str(_sp_lookup(entry, "guard") or "").strip()

				latitude = _sp_lookup(entry, "latitude")
				longitude = _sp_lookup(entry, "longitude")
				accuracy = _sp_lookup(entry, "accuracy")
				captured_at = _sp_lookup(entry, "captured_at")

				if not patrol_tag:
					results.append({"status": "error", "message": "patrol_tag is required"})
					continue

				if not latitude or not longitude or not captured_at:
					results.append(
						{
							"status": "error",
							"message": "latitude, longitude and captured_at are required",
							"patrol_tag": patrol_tag,
						}
					)
					continue

				existing = frappe.db.get_value(
					"Patrol GPS Log",
					{"patrol": patrol_tag, "captured_at": captured_at},
					"name",
				)
				if existing:
					results.append(
						{
							"status": "success",
							"message": "Duplicate - already synced",
							"name": existing,
							"patrol_tag": patrol_tag,
							"duplicate": True,
						}
					)
					continue

				guard = resolved_guard
				if not guard:
					guard = guard_code

				log = frappe.new_doc("Patrol GPS Log")
				log.patrol = patrol_tag
				if resolved_farm:
					log.farm = resolved_farm
				if resolved_type == "Employee":
					log.personel = "Internal Guard"
					log.internal_guard = guard
				elif resolved_type == "Security Guard":
					log.personel = "External Guard"
					log.external_guard = guard
				log.captured_at = captured_at
				log.latitude = str(latitude)
				log.longitude = str(longitude)
				if accuracy:
					log.gps_accuracy = str(accuracy)
				log.flags.ignore_links = True
				log.insert(ignore_permissions=True)

				any_success = True
				results.append(
					{
						"status": "success",
						"name": log.name,
						"patrol_tag": patrol_tag,
						"captured_at": str(captured_at),
					}
				)
			except Exception as row_err:
				frappe.log_error("submit_patrol_points row", str(row_err))
				results.append({"status": "error", "message": str(row_err)})

		if any_success:
			frappe.db.commit()
		else:
			frappe.db.rollback()

		return results
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("submit_patrol_points", str(e))
		return [{"status": "error", "message": str(e)}]
@frappe.whitelist()
def file_patrol_report(
	patrol=None,
	report_type=None,
	observations=None,
	severity=None,
	nature_of_incident=None,
	incident_report=None,
	farm=None,
	started_at=None,
	ended_at=None,
	attachment_1=None,
	attachment_2=None,
	attachment_3=None,
	attachment_4=None,
):
	"""File (or amend) a guard's patrol observation/incident report.

	Tied to the guard's GPS patrol tag, or an ad-hoc client-generated tag when
	no patrol is running. `patrol` is a UNIQUE field on Patrol Report, so a
	resubmit for the same tag is treated as an edit (idempotent) rather than a
	hard failure - a guard may re-tap after a typo or amend before review. On
	edit the status is left alone; on create it is set to "Submitted".

	Guard identity is session-derived: Employee by user_id (also supplies the
	default farm), else Security Guard by full_name. The shift assignment link
	is a nice-to-have in its own try/except because sites can have a
	differently-shaped (or absent) Shift Assignment doctype and a schema
	mismatch must never abort the filing. Link validation is skipped
	(flags.ignore_links) for the same cross-site-shape reason. Routine reports
	deliberately blank severity/nature/incident_report.
	"""
	try:
		patrol = str(patrol or "").strip()
		observations = str(observations or "").strip()

		if not patrol:
			return {"error": "Missing patrol tag"}
		if report_type not in ["Routine", "Incident"]:
			return {"error": "report_type must be Routine or Incident"}
		if not observations:
			return {"error": "Observations are required"}

		if report_type == "Incident" and not nature_of_incident:
			return {"error": "Nature of incident is required for Incident reports"}
		if incident_report and not frappe.db.exists("Incident Report", incident_report):
			return {"error": "Linked incident report not found"}

		current_user = frappe.session.user

		personel = None
		internal_guard = None
		external_guard = None
		resolved_farm = farm

		emp = frappe.db.get_value(
			"Employee", {"user_id": current_user}, ["name", "custom_farm"], as_dict=True
		)
		if emp:
			personel = "Internal Guard"
			internal_guard = emp["name"]
			if not resolved_farm:
				resolved_farm = emp["custom_farm"]
		else:
			user_full = frappe.db.get_value("User", current_user, "full_name") or ""
			guard_name = None
			if user_full:
				guard_name = frappe.db.get_value("Security Guard", {"full_name": user_full}, "name")
			if guard_name:
				personel = "External Guard"
				external_guard = guard_name

		resolved_shift = None
		try:
			if internal_guard:
				resolved_shift = frappe.db.get_value(
					"Security Guard Shift Assignment",
					{"internal_guard": internal_guard, "status": "Active"},
					"name",
				)
			elif external_guard:
				resolved_shift = frappe.db.get_value(
					"Security Guard Shift Assignment",
					{"external_guard": external_guard, "status": "Active"},
					"name",
				)
		except Exception:
			resolved_shift = None

		points_logged = frappe.db.count("Patrol GPS Log", {"patrol": patrol})

		existing_name = frappe.db.exists("Patrol Report", {"patrol": patrol})
		if existing_name:
			report = frappe.get_doc("Patrol Report", existing_name)
		else:
			report = frappe.new_doc("Patrol Report")
			report.patrol = patrol

		report.report_type = report_type
		report.farm = resolved_farm
		report.personel = personel
		report.internal_guard = internal_guard
		report.external_guard = external_guard
		report.shift_assignment = resolved_shift
		report.started_at = started_at
		report.ended_at = ended_at
		report.points_logged = points_logged
		report.filed_at = frappe.utils.now()
		report.observations = observations
		if report_type == "Incident":
			report.severity = severity if severity else "Medium"
			report.nature_of_incident = nature_of_incident
			report.incident_report = incident_report
		else:
			report.severity = None
			report.nature_of_incident = None
			report.incident_report = None
		report.attachment_1 = attachment_1
		report.attachment_2 = attachment_2
		report.attachment_3 = attachment_3
		report.attachment_4 = attachment_4
		report.flags.ignore_links = True
		if existing_name:
			report.save(ignore_permissions=True)
		else:
			report.status = "Submitted"
			report.insert(ignore_permissions=True)
		frappe.db.commit()

		return {
			"name": report.name,
			"patrol": report.patrol,
			"report_type": report.report_type,
			"status": report.status,
			"filed_at": str(report.filed_at),
			"points_logged": report.points_logged,
			"updated": True if existing_name else False,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("file_patrol_report", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def get_patrol_report(name=None):
	"""Single Patrol Report fetch with an ownership/scope check.

	Hierarchy mirrors get_incident_report: System Manager sees everything, the
	filer (owner) always sees their own, a Security Head sees whatever their own
	User Permission rows grant (Company and/or Farm), anyone else only their own
	company/farm.

	Patrol Report has no `company` column (only `farm`), so a Company-level grant
	is checked by resolving the report's farm to its company through Farm.

	Errors are returned at HTTP 200 as {"error": ...} (the mobile client's
	call<T> wrapper promotes them to thrown Errors); never raise.
	Read-only.
	"""
	try:
		name = str(name or "").strip()

		if not name:
			return {"error": "name is required"}

		r = frappe.db.get_value(
			"Patrol Report",
			name,
			[
				"name",
				"patrol",
				"report_type",
				"farm",
				"personel",
				"internal_guard",
				"external_guard",
				"shift_assignment",
				"started_at",
				"ended_at",
				"points_logged",
				"filed_at",
				"observations",
				"severity",
				"nature_of_incident",
				"incident_report",
				"attachment_1",
				"attachment_2",
				"attachment_3",
				"attachment_4",
				"status",
				"reviewed_by",
				"reviewed_on",
				"supervisor_remarks",
				"owner",
			],
			as_dict=True,
		)
		if not r:
			return {"error": "Patrol Report " + name + " not found"}

		current_user = frappe.session.user
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (current_user,)
		)
		roles = []
		for row in role_rows:
			if row and row[0]:
				roles.append(row[0])

		is_system_manager = "System Manager" in roles
		is_security_head = "Security Head" in roles

		allowed = is_system_manager or r.owner == current_user

		if not allowed:
			report_company = None
			if r.farm:
				report_company = frappe.db.get_value("Farm", r.farm, "company")

			scope_companies = []
			scope_farms = []
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

			if report_company and report_company in scope_companies:
				allowed = True
			elif r.farm and r.farm in scope_farms:
				allowed = True

		if not allowed:
			return {"error": "You do not have access to this patrol report"}

		return {
			"name": r.name,
			"patrol": r.patrol or "",
			"report_type": r.report_type or "",
			"farm": r.farm or "",
			"personel": r.personel or "",
			"internal_guard": r.internal_guard or "",
			"external_guard": r.external_guard or "",
			"shift_assignment": r.shift_assignment or "",
			"started_at": str(r.started_at) if r.started_at else "",
			"ended_at": str(r.ended_at) if r.ended_at else "",
			"points_logged": r.points_logged or 0,
			"filed_at": str(r.filed_at) if r.filed_at else "",
			"observations": r.observations or "",
			"severity": r.severity or "",
			"nature_of_incident": r.nature_of_incident or "",
			"incident_report": r.incident_report or "",
			"attachment_1": r.attachment_1 or "",
			"attachment_2": r.attachment_2 or "",
			"attachment_3": r.attachment_3 or "",
			"attachment_4": r.attachment_4 or "",
			"status": r.status or "",
			"reviewed_by": r.reviewed_by or "",
			"reviewed_on": str(r.reviewed_on) if r.reviewed_on else "",
			"supervisor_remarks": r.supervisor_remarks or "",
		}
	except Exception as e:
		frappe.log_error("get_patrol_report", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def list_patrol_reports(from_date=None, to_date=None, status=None, report_type=None, limit=None):
	"""Supervisor-facing list of filed Patrol Reports, newest first.

	Same scoping as list_incidents: System Manager sees everything; a Security
	Head sees whatever their User Permission grants (Company and/or Farm);
	anyone else is scoped to their own company/farm.

	Patrol Report has no `company` column, so a Company grant is matched via a
	LEFT JOIN to Farm (farm is already on this doctype, unlike list_incidents
	which has to infer it from the filer's Employee row). Company and farm
	grants are OR-ed together here.

	If a non-System-Manager has no resolvable company or farm the query gets
	`1=0` -- show nothing rather than falling through to "everything". Load
	bearing; do not "simplify" away.

	`limit` defaults to 200 and is clamped to 1..1000; an unparseable value
	silently falls back to 200. from_date/to_date compare against DATE(filed_at).
	The IN lists are built from generated placeholders with bound values.
	Read-only.
	"""
	try:
		from_date = from_date or ""
		to_date = to_date or ""
		status_filter = status or ""
		report_type_filter = report_type or ""

		row_limit = 200
		try:
			if limit:
				row_limit = int(limit)
		except (TypeError, ValueError):
			row_limit = 200
		if row_limit < 1:
			row_limit = 1
		if row_limit > 1000:
			row_limit = 1000

		current_user = frappe.session.user
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (current_user,)
		)
		roles = []
		for row in role_rows:
			if row and row[0]:
				roles.append(row[0])

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
		params = {}
		if from_date:
			where_parts.append("DATE(p.filed_at) >= %(from_date)s")
			params["from_date"] = from_date
		if to_date:
			where_parts.append("DATE(p.filed_at) <= %(to_date)s")
			params["to_date"] = to_date
		if status_filter:
			where_parts.append("p.status = %(status_filter)s")
			params["status_filter"] = status_filter
		if report_type_filter:
			where_parts.append("p.report_type = %(report_type_filter)s")
			params["report_type_filter"] = report_type_filter

		if not is_system_manager:
			conditions = []
			if scope_companies:
				placeholders = ", ".join(["%(c" + str(idx) + ")s" for idx in range(len(scope_companies))])
				conditions.append("f.company IN (" + placeholders + ")")
				for idx in range(len(scope_companies)):
					params["c" + str(idx)] = scope_companies[idx]
			if scope_farms:
				placeholders = ", ".join(["%(f" + str(idx) + ")s" for idx in range(len(scope_farms))])
				conditions.append("p.farm IN (" + placeholders + ")")
				for idx in range(len(scope_farms)):
					params["f" + str(idx)] = scope_farms[idx]
			if conditions:
				where_parts.append("(" + " OR ".join(conditions) + ")")
			else:
				where_parts.append("1=0")

		params["row_limit"] = row_limit

		where_clause = " AND ".join(where_parts)
		sql = (
			"SELECT p.name, p.patrol, p.report_type, p.farm, p.severity, p.nature_of_incident, "
			"p.status, p.filed_at, p.points_logged, p.personel, p.internal_guard, p.external_guard "
			"FROM `tabPatrol Report` p "
			"LEFT JOIN `tabFarm` f ON f.name = p.farm "
			"WHERE " + where_clause + " "
			"ORDER BY p.filed_at DESC "
			"LIMIT %(row_limit)s"
		)

		rows = frappe.db.sql(sql, params, as_dict=True)
		out = []
		for r in rows:
			out.append(
				{
					"name": r.name,
					"patrol": r.patrol or "",
					"report_type": r.report_type or "",
					"farm": r.farm or "",
					"severity": r.severity or "",
					"nature_of_incident": r.nature_of_incident or "",
					"status": r.status or "",
					"filed_at": str(r.filed_at) if r.filed_at else "",
					"points_logged": r.points_logged or 0,
					"personel": r.personel or "",
					"internal_guard": r.internal_guard or "",
					"external_guard": r.external_guard or "",
				}
			)
		return out
	except Exception as e:
		frappe.log_error("list_patrol_reports", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def my_patrol_reports():
	"""The calling guard's own filed Patrol Reports, most recent first (max 50).

	Filters on `owner` (the standard Frappe creator field) rather than
	internal_guard/external_guard: always correct without having to re-resolve
	guard identity. Mirrors my_incidents. No pagination beyond the hard LIMIT 50.
	Read-only.
	"""
	try:
		user = frappe.session.user
		rows = frappe.db.sql(
			"""
			SELECT name, patrol, report_type, farm, severity, nature_of_incident,
                   status, filed_at, points_logged
			FROM `tabPatrol Report`
			WHERE owner = %s
			ORDER BY filed_at DESC
			LIMIT 50
			""",
			(user,),
			as_dict=True,
		)
		out = []
		for r in rows:
			out.append(
				{
					"name": r.name,
					"patrol": r.patrol or "",
					"report_type": r.report_type or "",
					"farm": r.farm or "",
					"severity": r.severity or "",
					"nature_of_incident": r.nature_of_incident or "",
					"status": r.status or "",
					"filed_at": str(r.filed_at) if r.filed_at else "",
					"points_logged": r.points_logged or 0,
				}
			)
		return out
	except Exception as e:
		frappe.log_error("my_patrol_reports", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def createPatrolEntry():
	"""Deliberate no-op stub.

	The live Server Script body is the single statement `pass`: it does nothing
	and writes no response message. The mobile app (app/(tabs)/patrol.tsx)
	comment claims createPatrolEntry "lazy-creates the Patrol Session on the
	first successful upload", but no such behaviour exists on the server. Ported
	as-is (returns None -> Frappe sends no message) so the endpoint stays
	callable and parity is exact. Writes nothing.
	"""
	return None


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


def farm_at_point(location):
	"""The farm whose boundary contains a "lat, lng" string, or None."""
	parts = [p.strip() for p in str(location or "").split(",")]
	if len(parts) != 2:
		return None
	try:
		lat, lng = float(parts[0]), float(parts[1])
	except ValueError:
		return None
	from shapely.geometry import Point

	from upande_security.api.patrol_coverage import _load_farm_polygon

	point = Point(lng, lat)
	for farm in frappe.get_all("Farm", pluck="name"):
		try:
			poly = _load_farm_polygon(farm)
		except Exception:
			continue
		if poly is not None and poly.contains(point):
			return farm
	return None


def incident_farm(user, location=None):
	"""The farm an incident belongs to - what the dashboard's farm and company
	filters go by. A location that names a farm wins (the guard said where),
	then GPS coordinates ("lat, lng", what the app sends from the map) inside
	a farm's boundary, then wherever the reporter is posted (today's roster,
	then their own farm). None when none of these is known."""
	location = (location or "").strip()
	if location:
		named = frappe.db.get_value("Farm", {"name": location}, "name")
		if named:
			return named
		at_point = farm_at_point(location)
		if at_point:
			return at_point
	from upande_security.api.gate_vehicle import _resolve_checking_farm

	return _resolve_checking_farm(user) or None


@frappe.whitelist()
def create_incident(
	incident_datetime=None,
	location=None,
	nature_of_incident=None,
	severity=None,
	description=None,
	attachment_1=None,
	attachment_2=None,
	attachment_3=None,
	attachment_4=None,
	is_fatal=None,
	activity_at_time_of_injury=None,
	body_part_affected=None,
	nature_of_injury=None,
	injury_current_location=None,
):
	"""Create an Incident Report from the mobile app.

	Every input is normalised to a stripped string (None -> ""), including
	is_fatal, which is true only for "1"/"true"/"True" - a JSON boolean true
	arrives as "True" after str(). Severity defaults to Medium.

	nature_of_incident is validated against the Incident Category master ONLY
	when that master has rows: some sites model it as a Link to a populated
	master, others as a plain Select where "Incident Category" exists but is
	empty. Where the master is unused the Select's own option list is enforced
	by Frappe on insert.

	Workplace Injury adds fatality/injury fields and a DOSHS reporting
	deadline: incident date + 2 days if fatal, else + 7. An unparseable
	incident_datetime silently leaves the deadline blank instead of failing the
	report (the insert itself may still reject the datetime).
	"""
	try:
		def s(v):
			if v is None:
				return ""
			return str(v).strip()

		incident_datetime = s(incident_datetime)
		location = s(location)
		nature_of_incident = s(nature_of_incident)
		severity = s(severity) or "Medium"
		description = s(description)
		attachment_1 = s(attachment_1)
		attachment_2 = s(attachment_2)
		attachment_3 = s(attachment_3)
		attachment_4 = s(attachment_4)

		if not incident_datetime:
			incident_datetime = str(frappe.utils.now_datetime())

		if not nature_of_incident:
			return {"error": "nature_of_incident is required"}
		if severity not in ("Low", "Medium", "High", "Critical"):
			return {"error": "severity must be Low/Medium/High/Critical"}

		category_master_in_use = frappe.db.count("Incident Category") > 0
		cat_ok = True
		if category_master_in_use:
			cat_ok = bool(frappe.db.get_value("Incident Category", nature_of_incident, "name"))
		if not cat_ok:
			return {"error": "Incident Category '" + nature_of_incident + "' does not exist"}

		user = frappe.session.user
		full_name = frappe.db.get_value("User", user, "full_name") or user
		now = frappe.utils.now_datetime()

		doc = frappe.new_doc("Incident Report")
		doc.incident_datetime = incident_datetime
		doc.location = location
		farm = incident_farm(user, location)
		if farm:
			doc.farm = farm
		doc.nature_of_incident = nature_of_incident
		doc.severity = severity
		doc.description = description
		doc.reported_by = user
		doc.reporter_name = full_name
		doc.reported_datetime = now
		doc.status = "Open"
		if attachment_1:
			doc.attachment_1 = attachment_1
		if attachment_2:
			doc.attachment_2 = attachment_2
		if attachment_3:
			doc.attachment_3 = attachment_3
		if attachment_4:
			doc.attachment_4 = attachment_4

		doshs_deadline = ""
		if nature_of_incident == "Workplace Injury":
			is_fatal_flag = s(is_fatal) in ("1", "true", "True")
			doc.is_fatal = 1 if is_fatal_flag else 0
			doc.injury_case_status = "Reported"

			activity_at_time_of_injury = s(activity_at_time_of_injury)
			if activity_at_time_of_injury:
				doc.activity_at_time_of_injury = activity_at_time_of_injury
			body_part_affected = s(body_part_affected)
			if body_part_affected:
				doc.body_part_affected = body_part_affected
			nature_of_injury = s(nature_of_injury)
			if nature_of_injury:
				doc.nature_of_injury = nature_of_injury
			injury_current_location = s(injury_current_location)
			if injury_current_location:
				doc.injury_current_location = injury_current_location

			try:
				incident_dt = frappe.utils.get_datetime(incident_datetime)
				days = 2 if is_fatal_flag else 7
				doshs_deadline = str(frappe.utils.add_days(incident_dt, days).date())
				doc.doshs_deadline = doshs_deadline
			except Exception:
				doshs_deadline = ""

		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return {
			"name": doc.name,
			"incident_datetime": incident_datetime,
			"location": location,
			"nature_of_incident": nature_of_incident,
			"severity": severity,
			"description": description,
			"reported_by": user,
			"reporter_name": full_name,
			"status": "Open",
			"doshs_deadline": doshs_deadline,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("create_incident", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def update_incident(name=None, status=None, resolution=None, corrective_actions=None):
	"""Edit an Incident Report from the Command Center incident-review screen.

	Access is strictly the Security Head or System Manager role, read straight
	from Has Role (no allowlist). Note this is NOT frappe.get_roles: it ignores
	automatic roles and an Administrator with no explicit Has Role row is
	denied.

	Only "name" is required; only fields PRESENT in the payload are applied.
	Presence matters because an explicit null/"" clears resolution or
	corrective_actions while an absent key leaves them untouched - something a
	default-None parameter cannot express. So status/resolution/
	corrective_actions are declared for the whitelist signature but presence
	and value are read from the raw payload (JSON body, else form_dict), as the
	original did. Valid statuses mirror the Incident Report status Select,
	hand-synced; an explicit null status is rejected as "Invalid status.".

	The final save has its own try/except that rolls back and soft-fails
	without logging (unlike the outer handler, which logs).
	"""
	try:
		current_user = frappe.session.user
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (current_user,)
		)
		roles = []
		for row in role_rows:
			if row and row[0]:
				roles.append(row[0])
		has_access = "Security Head" in roles or "System Manager" in roles

		if not has_access:
			return {"error": "You do not have access to this action."}

		data = {}
		try:
			data = frappe.request.get_json(silent=True) or {}
		except Exception:
			data = {}
		if not data:
			data = dict(frappe.form_dict or {})

		name = str(_sp_lookup(data, "name") or "").strip()

		if not name:
			return {"error": "name is required"}
		if not frappe.db.exists("Incident Report", name):
			return {"error": "Incident Report not found."}

		valid_statuses = ("Open", "In Progress", "Resolved", "Closed")

		has_status = True
		status_val = None
		try:
			status_val = data["status"]
		except (KeyError, TypeError):
			has_status = False

		has_resolution = True
		resolution_val = None
		try:
			resolution_val = data["resolution"]
		except (KeyError, TypeError):
			has_resolution = False

		has_corrective_actions = True
		corrective_actions_val = None
		try:
			corrective_actions_val = data["corrective_actions"]
		except (KeyError, TypeError):
			has_corrective_actions = False

		if has_status and status_val not in valid_statuses:
			return {"error": "Invalid status."}

		doc = frappe.get_doc("Incident Report", name)
		applied = False
		if has_status:
			doc.status = status_val
			applied = True
		if has_resolution:
			doc.resolution = resolution_val
			applied = True
		if has_corrective_actions:
			doc.corrective_actions = corrective_actions_val
			applied = True

		if not applied:
			return {"error": "No updatable fields were sent"}

		try:
			doc.save(ignore_permissions=True)
			frappe.db.commit()
			return {
				"success": True,
				"name": doc.name,
				"status": doc.status,
				"resolution": doc.resolution or "",
				"corrective_actions": doc.corrective_actions or "",
			}
		except Exception as e:
			frappe.db.rollback()
			return {"error": str(e)}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("update_incident", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def get_incident_report(name=None):
	"""Single Incident Report fetch (incl. witnesses and victims) with scoping.

	Hierarchy mirrors list_incidents: System Manager sees everything; the
	reporter always sees their own; a Security Head is scoped to their own User
	Permission grants; anyone else only their own company/farm. Unlike Patrol
	Report, Incident Report has no farm/company column, so the company/farm of
	the incident is INFERRED from the reporter's Employee row (company,
	custom_farm). A reporter with no Employee record therefore yields no
	company/farm and only owner/System Manager access applies.

	Witnesses/victims are Incident Person child rows read with get_all (no
	permission check beyond the parent gate above); they include id_number and
	contact (PII).

	Errors are returned at HTTP 200 as {"error": ...}. Read-only.
	"""
	try:
		name = str(name or "").strip()

		if not name:
			return {"error": "name is required"}

		r = frappe.db.get_value(
			"Incident Report",
			name,
			[
				"name",
				"incident_datetime",
				"location",
				"nature_of_incident",
				"severity",
				"description",
				"status",
				"reported_by",
				"reporter_name",
				"reported_datetime",
				"activity_at_time_of_injury",
				"body_part_affected",
				"nature_of_injury",
				"is_fatal",
				"doshs_deadline",
				"doshs_reported",
				"doshs_reported_date",
				"doshs_reference_number",
				"attending_physician",
				"injury_case_status",
				"injury_current_location",
				"days_off_work",
				"return_to_work_date",
				"first_aid_given",
				"first_aider_name",
				"ambulance_needed",
				"ambulance_provider",
				"ambulance_called_at",
				"taken_to_hospital",
				"hospital_name",
				"hospital_admission_type",
				"treatment_summary",
				"police_report_required",
				"ob_number",
				"police_station",
				"compensation_required",
				"wiba_claim_filed",
				"wiba_claim_number",
				"payment_status",
				"amount_paid",
			],
			as_dict=True,
		)
		if not r:
			return {"error": "Incident Report " + name + " not found"}

		current_user = frappe.session.user
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (current_user,)
		)
		roles = []
		for row in role_rows:
			if row and row[0]:
				roles.append(row[0])

		is_system_manager = "System Manager" in roles
		is_security_head = "Security Head" in roles

		allowed = is_system_manager or r.reported_by == current_user

		if not allowed:
			reporter_employee = frappe.db.get_value(
				"Employee", {"user_id": r.reported_by}, ["company", "custom_farm"], as_dict=True
			)
			reporter_company = reporter_employee.company if reporter_employee else None
			reporter_farm = reporter_employee.custom_farm if reporter_employee else None

			scope_companies = []
			scope_farms = []
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

			if reporter_company and reporter_company in scope_companies:
				allowed = True
			elif reporter_farm and reporter_farm in scope_farms:
				allowed = True

		if not allowed:
			return {"error": "You do not have access to this incident"}

		witnesses = frappe.get_all(
			"Incident Person",
			filters={"parent": name, "parentfield": "witnesses"},
			fields=["person_name", "person_type", "contact", "id_number", "notes"],
		)
		victims = frappe.get_all(
			"Incident Person",
			filters={"parent": name, "parentfield": "victims"},
			fields=["person_name", "person_type", "contact", "id_number", "notes"],
		)
		return {
			"name": r.name,
			"incident_datetime": str(r.incident_datetime) if r.incident_datetime else "",
			"location": r.location or "",
			"nature_of_incident": r.nature_of_incident or "",
			"severity": r.severity or "",
			"description": r.description or "",
			"status": r.status or "",
			"reported_by": r.reported_by or "",
			"reporter_name": r.reporter_name or "",
			"reported_datetime": str(r.reported_datetime) if r.reported_datetime else "",
			"activity_at_time_of_injury": r.activity_at_time_of_injury or "",
			"body_part_affected": r.body_part_affected or "",
			"nature_of_injury": r.nature_of_injury or "",
			"is_fatal": bool(r.is_fatal),
			"doshs_deadline": str(r.doshs_deadline) if r.doshs_deadline else "",
			"doshs_reported": bool(r.doshs_reported),
			"doshs_reported_date": str(r.doshs_reported_date) if r.doshs_reported_date else "",
			"doshs_reference_number": r.doshs_reference_number or "",
			"attending_physician": r.attending_physician or "",
			"injury_case_status": r.injury_case_status or "",
			"injury_current_location": r.injury_current_location or "",
			"days_off_work": r.days_off_work if r.days_off_work is not None else None,
			"return_to_work_date": str(r.return_to_work_date) if r.return_to_work_date else "",
			"first_aid_given": bool(r.first_aid_given),
			"first_aider_name": r.first_aider_name or "",
			"ambulance_needed": bool(r.ambulance_needed),
			"ambulance_provider": r.ambulance_provider or "",
			"ambulance_called_at": str(r.ambulance_called_at) if r.ambulance_called_at else "",
			"taken_to_hospital": bool(r.taken_to_hospital),
			"hospital_name": r.hospital_name or "",
			"hospital_admission_type": r.hospital_admission_type or "",
			"treatment_summary": r.treatment_summary or "",
			"police_report_required": bool(r.police_report_required),
			"ob_number": r.ob_number or "",
			"police_station": r.police_station or "",
			"compensation_required": bool(r.compensation_required),
			"wiba_claim_filed": bool(r.wiba_claim_filed),
			"wiba_claim_number": r.wiba_claim_number or "",
			"payment_status": r.payment_status or "",
			"amount_paid": r.amount_paid if r.amount_paid is not None else None,
			"witnesses": witnesses,
			"victims": victims,
		}
	except Exception as e:
		frappe.log_error("get_incident_report", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def update_workplace_injury(name=None):
	"""Progressive update of the Workplace Injury case fields on an Incident Report.

	The follow-up screen sends only the fields it changed, so each field is
	touched only when its key is PRESENT in the request. Explicit null differs
	from absent (check -> 0, text -> "", date/datetime -> None, numbers -> None),
	which a `field=None` signature cannot express; presence is therefore tested
	against frappe.local.form_dict (Frappe merges a JSON body into it), and only
	`name` is a named parameter.

	Writes with frappe.db.set_value: NO validate(), no on_update hooks, no
	workflow, and no permission check -- any authenticated caller can update any
	Workplace Injury incident (preserved from the original). Closing the case
	(injury_case_status == "Closed") also sets the parent status to "Resolved"
	so the general incident list reflects it.

	Unparseable days_off_work/amount_paid are silently skipped, not rejected.
	Check fields use truthiness, so a form-encoded "0" counts as 1 (JSON false
	is fine). The except block rolls back, including for errors that happen
	before any write.

	Writes: Incident Report.
	"""
	try:
		data = frappe.local.form_dict

		name = str(name or "").strip()

		if not name:
			return {"error": "name is required"}

		existing = frappe.db.get_value(
			"Incident Report", name, ["name", "nature_of_incident"], as_dict=True
		)
		if not existing:
			return {"error": "Incident Report " + name + " not found"}
		if existing.nature_of_incident != "Workplace Injury":
			return {"error": name + " is not a Workplace Injury incident"}

		check_fields = [
			"first_aid_given",
			"ambulance_needed",
			"taken_to_hospital",
			"police_report_required",
			"compensation_required",
			"wiba_claim_filed",
			"is_fatal",
			"doshs_reported",
		]
		text_fields = [
			"injury_case_status",
			"injury_current_location",
			"first_aider_name",
			"ambulance_provider",
			"hospital_name",
			"hospital_admission_type",
			"attending_physician",
			"treatment_summary",
			"ob_number",
			"police_station",
			"wiba_claim_number",
			"payment_status",
			"activity_at_time_of_injury",
			"body_part_affected",
			"nature_of_injury",
			"doshs_reference_number",
		]
		datetime_fields = ["ambulance_called_at"]
		date_fields = ["return_to_work_date", "doshs_reported_date"]

		updates = {}

		for key in check_fields:
			if key in data:
				v = data[key]
				updates[key] = 1 if v else 0

		for key in text_fields:
			if key in data:
				v = data[key]
				updates[key] = str(v).strip() if v is not None else ""

		for key in datetime_fields + date_fields:
			if key in data:
				v = data[key]
				updates[key] = v if v else None

		if "days_off_work" in data:
			try:
				v = data["days_off_work"]
				if v in (None, ""):
					updates["days_off_work"] = None
				else:
					updates["days_off_work"] = int(v)
			except (TypeError, ValueError):
				pass

		if "amount_paid" in data:
			try:
				v = data["amount_paid"]
				if v in (None, ""):
					updates["amount_paid"] = None
				else:
					updates["amount_paid"] = float(v)
			except (TypeError, ValueError):
				pass

		if not updates:
			return {"error": "No updatable fields were sent"}

		closing = False
		if "injury_case_status" in updates:
			closing = updates["injury_case_status"] == "Closed"
		if closing:
			updates["status"] = "Resolved"

		frappe.db.set_value("Incident Report", name, updates)
		frappe.db.commit()
		return {"name": name, "updated": list(updates.keys())}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("update_workplace_injury", str(e))
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


@frappe.whitelist()
def update_shift_assignment(name=None, status=None, start_date=None, end_date=None, start_time=None, end_time=None, remarks=None):
	"""Edit a Security Guard Shift Assignment from the Command Center shift screen.

	WRITES Security Guard Shift Assignment. Only `name` is required; only the
	fields actually present in the request are applied.

	Access: strictly Security Head / System Manager by role, no allowlist (the
	Command Center User allowlist was removed from has_command_center_access,
	so it must not be a back door here either).

	Internal Guard shifts are a read-only HR mirror: their dates/times cannot
	change here. The doctype already enforces that on save, but it is checked
	up front so the caller gets one clean error instead of a half-applied
	change. status and remarks stay editable for every guard type. Overlap
	checking is NOT reimplemented -- validate_no_overlapping_assignment()
	runs inside doc.save() and its throw is caught and returned as {"error"}.

	The date/time comparison is normalised (getdate / get_time) because the
	loaded doc's start_time/end_time are timedeltas whose str() is "8:00:00"
	while the payload sends "08:00:00"; a raw string compare would reject a
	status-only resend. Any parse failure fails CLOSED (treated as an edit,
	so blocked).

	"Present in the request" matters, not "non-null": the original used a
	key-exists check, so an explicit JSON null is applied (e.g. remarks: null
	clears it). A named parameter cannot tell absent from null, so presence is
	taken as value-is-not-None OR key-in-form_dict (frappe merges the JSON
	body into form_dict). Direct Python calls passing None explicitly are
	treated as absent.
	"""
	try:
		roles = _user_roles(frappe.session.user)
		has_access = "Security Head" in roles or "System Manager" in roles

		if not has_access:
			return {"error": "You do not have access to this action."}

		def present(key, val):
			return val is not None or key in frappe.form_dict

		name = str(name or "").strip()

		if not name:
			return {"error": "name is required"}
		if not frappe.db.exists("Security Guard Shift Assignment", name):
			return {"error": "Shift assignment not found."}

		doc = frappe.get_doc("Security Guard Shift Assignment", name)

		has_start_date = present("start_date", start_date)
		has_end_date = present("end_date", end_date)
		has_start_time = present("start_time", start_time)
		has_end_time = present("end_time", end_time)
		has_status = present("status", status)
		has_remarks = present("remarks", remarks)

		blocked = False
		if doc.security_guard == "Internal Guard":
			if has_start_date:
				try:
					if frappe.utils.getdate(start_date) != frappe.utils.getdate(doc.start_date):
						blocked = True
				except Exception:
					blocked = True
			if has_end_date:
				try:
					if frappe.utils.getdate(end_date) != frappe.utils.getdate(doc.end_date):
						blocked = True
				except Exception:
					blocked = True
			if has_start_time:
				try:
					if frappe.utils.get_time(start_time) != frappe.utils.get_time(doc.start_time):
						blocked = True
				except Exception:
					blocked = True
			if has_end_time:
				try:
					if frappe.utils.get_time(end_time) != frappe.utils.get_time(doc.end_time):
						blocked = True
				except Exception:
					blocked = True

		if blocked:
			return {
				"error": "Internal Guard shifts mirror HR and cannot have their dates/times "
				"edited here. Only status can be changed."
			}

		applied = False
		if has_status:
			doc.status = status
			applied = True
		if has_start_date:
			doc.start_date = start_date
			applied = True
		if has_end_date:
			doc.end_date = end_date
			applied = True
		if has_start_time:
			doc.start_time = start_time
			applied = True
		if has_end_time:
			doc.end_time = end_time
			applied = True
		if has_remarks:
			doc.remarks = remarks
			applied = True

		if not applied:
			return {"error": "No updatable fields were sent"}

		try:
			# ignore_permissions: access was already gated by role above.
			doc.save(ignore_permissions=True)
			frappe.db.commit()

			start_date_str = ""
			try:
				start_date_str = str(doc.start_date) if doc.start_date else ""
			except Exception:
				start_date_str = ""
			end_date_str = ""
			try:
				end_date_str = str(doc.end_date) if doc.end_date else ""
			except Exception:
				end_date_str = ""
			start_time_str = ""
			try:
				start_time_str = str(doc.start_time) if doc.start_time is not None else ""
			except Exception:
				start_time_str = ""
			end_time_str = ""
			try:
				end_time_str = str(doc.end_time) if doc.end_time is not None else ""
			except Exception:
				end_time_str = ""

			return {
				"success": True,
				"name": doc.name,
				"status": doc.status,
				"start_date": start_date_str,
				"end_date": end_date_str,
				"start_time": start_time_str,
				"end_time": end_time_str,
				"remarks": doc.remarks or "",
				"security_guard": doc.security_guard,
			}
		except Exception as e:
			frappe.db.rollback()
			return {"error": str(e)}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("update_shift_assignment", str(e))
		return {"error": str(e)}


_SHIFT_FARM_PALETTE = [
	{"bg": "#E6F1FB", "text": "#0C447C"},
	{"bg": "#EAF3DE", "text": "#27500A"},
	{"bg": "#FAEEDA", "text": "#633806"},
	{"bg": "#EEEDFE", "text": "#3C3489"},
	{"bg": "#FCEBEB", "text": "#791F1F"},
	{"bg": "#CCFBF1", "text": "#115E59"},
	{"bg": "#FFE4E6", "text": "#9F1239"},
	{"bg": "#E0E7FF", "text": "#3730A3"},
]


def _shift_farm_colors(farm_names):
	"""Stable colour per farm: sorted farm names, palette assigned in order."""
	colors = {}
	for i, name in enumerate(sorted({n for n in farm_names if n})):
		colors[name] = _SHIFT_FARM_PALETTE[i % len(_SHIFT_FARM_PALETTE)]
	return colors


def _shift_guard_key(row):
	if row.get("internal_guard"):
		return "employee::" + row.get("internal_guard")
	if row.get("external_guard"):
		return "security_guard::" + row.get("external_guard")
	return None


def _shift_guard_name(row, employee_names, security_guard_names):
	internal_guard = row.get("internal_guard")
	if internal_guard:
		return employee_names.get(internal_guard, internal_guard)
	external_guard = row.get("external_guard")
	if external_guard:
		return security_guard_names.get(external_guard, external_guard)
	return "Unassigned"


@frappe.whitelist()
def security_shift_assignment_tab_fetch(
	period=None, from_date=None, to_date=None, farm=None, shift_type=None, status=None, company=None
):
	"""Shift assignments, today's Day/Night coverage per farm, and filter options.

	READ-ONLY. Was the "Security Shift Assignment Tab Fetch (stopgap)" Server
	Script; nothing in this repo calls it, which is exactly why it is kept
	(see tests/test_bare_paths.py on "no in-repo caller").

	period: "custom" (with from_date and to_date), "last_7_days",
	"last_30_days", anything else = today only.

	No explicit permission check: every query goes through frappe.get_list,
	so the caller's own read permission applies and an unauthorised caller
	gets empty results rather than real data.

	Farm's display field is "farm" on upande_kaitet and "farm_name" on
	upande_core, so Farm.name (which both autoname from it) is used instead.
	The company filter only narrows farms where Farm actually has a company
	field; elsewhere it is a no-op rather than a field-permission error.

	Failure returns {"success": False, "error": ...}, never logs - as the
	Server Script did.
	"""
	try:
		today = frappe.utils.getdate()

		if period == "custom" and from_date and to_date:
			range_from = frappe.utils.getdate(from_date)
			range_to = frappe.utils.getdate(to_date)
		elif period == "last_7_days":
			range_from = frappe.utils.add_days(today, -6)
			range_to = today
		elif period == "last_30_days":
			range_from = frappe.utils.add_days(today, -29)
			range_to = today
		else:
			range_from = today
			range_to = today

		doctype = "Security Guard Shift Assignment"

		if company and frappe.get_meta("Farm").has_field("company"):
			company_farm_filters = {"company": company}
		else:
			company_farm_filters = {}

		company_farms_raw = frappe.get_list(
			"Farm",
			filters=company_farm_filters,
			fields=["name"],
			order_by="name asc",
			page_length=500,
		)
		company_farms = [{"name": f["name"], "farm": f["name"]} for f in company_farms_raw]

		if farm:
			farm_scope = [farm]
		elif company:
			farm_scope = [f["name"] for f in company_farms] or ["__no_farm_matches__"]
		else:
			farm_scope = None

		range_filters = [
			["start_date", "<=", str(range_to) + " 23:59:59"],
			["end_date", ">=", str(range_from) + " 00:00:00"],
		]
		if farm_scope is not None:
			range_filters.append(["farm", "in", farm_scope])
		if shift_type:
			range_filters.append(["shift_type", "=", shift_type])
		if status:
			range_filters.append(["status", "=", status])

		range_rows = frappe.get_list(
			doctype,
			filters=range_filters,
			fields=[
				"name", "security_guard", "internal_guard", "external_guard",
				"farm", "block", "shift_type", "start_date", "end_date", "status",
				"assigned_by", "remarks", "modified",
			],
			order_by="start_date desc",
			page_length=1000,
		)

		all_rows_filters = {"status": "Active"}
		if farm_scope is not None:
			all_rows_filters["farm"] = ["in", farm_scope]

		all_rows = frappe.get_list(
			doctype,
			filters=all_rows_filters,
			fields=[
				"name", "security_guard", "internal_guard", "external_guard",
				"farm", "shift_type", "start_date", "end_date",
			],
			page_length=5000,
		)

		employee_ids = {r.get("internal_guard") for r in range_rows + all_rows if r.get("internal_guard")}
		security_guard_ids = {r.get("external_guard") for r in range_rows + all_rows if r.get("external_guard")}

		employee_names = {}
		for e in frappe.get_all(
			"Employee", filters={"name": ["in", list(employee_ids)]}, fields=["name", "employee_name"]
		):
			employee_names[e.name] = e.employee_name

		security_guard_names = {}
		for g in frappe.get_all(
			"Security Guard", filters={"name": ["in", list(security_guard_ids)]}, fields=["name", "full_name"]
		):
			security_guard_names[g.name] = g.full_name or g.name

		if farm:
			matching = [f for f in company_farms if f["name"] == farm]
			if matching:
				board_farms = matching
			else:
				fallback_raw = frappe.get_list("Farm", filters={"name": farm}, fields=["name"])
				board_farms = [{"name": f["name"], "farm": f["name"]} for f in fallback_raw]
		else:
			board_farms = company_farms

		farm_colors = _shift_farm_colors([a.get("farm") for a in range_rows])

		rows = []
		for r in range_rows:
			farm_name = r.get("farm") or ""
			start_date = r.get("start_date")
			end_date = r.get("end_date")
			rows.append({
				"name": r["name"],
				"guard_key": _shift_guard_key(r),
				"guard_name": _shift_guard_name(r, employee_names, security_guard_names),
				"guard_type": r.get("security_guard"),
				"farm": farm_name,
				"farm_color": farm_colors.get(farm_name) or {"bg": "#F1EFE8", "text": "#444441"},
				"block": r.get("block") or "",
				"shift_type": r.get("shift_type"),
				"start_date": str(start_date) if start_date else None,
				"end_date": str(end_date) if end_date else None,
				"status": r.get("status"),
				"remarks": r.get("remarks") or "",
			})

		coverage = {}
		for f in board_farms:
			coverage[f["farm"]] = {"Day": None, "Night": None}

		for r in all_rows:
			start = frappe.utils.getdate(r.get("start_date")) if r.get("start_date") else None
			end = frappe.utils.getdate(r.get("end_date")) if r.get("end_date") else None
			if not (start and start <= today and (not end or end >= today)):
				continue
			slot = coverage.setdefault(r.get("farm"), {"Day": None, "Night": None})
			slot[r.get("shift_type")] = _shift_guard_name(r, employee_names, security_guard_names)

		coverage_board = [
			{"farm": farm_name, "day_guard": slots.get("Day"), "night_guard": slots.get("Night")}
			for farm_name, slots in coverage.items()
		]
		coverage_board.sort(key=lambda x: x["farm"] or "")

		filled_slots = sum(bool(c["day_guard"]) + bool(c["night_guard"]) for c in coverage_board)
		total_slots = len(coverage_board) * 2

		guard_farms = {}
		for r in all_rows:
			key = _shift_guard_key(r)
			if key and r.get("farm"):
				guard_farms.setdefault(key, set()).add(r.get("farm"))
		guards_on_rotation = sum(1 for farms in guard_farms.values() if len(farms) > 1)

		day_count = sum(1 for r in rows if r["shift_type"] == "Day" and r["status"] == "Active")
		night_count = sum(1 for r in rows if r["shift_type"] == "Night" and r["status"] == "Active")
		farms_covered = sum(1 for c in coverage_board if c["day_guard"] or c["night_guard"])

		companies = frappe.get_list("Company", fields=["name"], order_by="name asc", page_length=200)

		return {
			"success": True,
			"range_from": str(range_from),
			"range_to": str(range_to),
			"summary": {
				"total_assignments": len(rows),
				"day_shift_count": day_count,
				"night_shift_count": night_count,
				"farms_covered": farms_covered,
				"farms_total": len(coverage_board),
				"unfilled_slots": total_slots - filled_slots,
				"guards_on_rotation": guards_on_rotation,
			},
			"coverage_board": coverage_board,
			"rows": rows,
			"farm_colors": farm_colors,
			"filter_options": {
				"farms": [f["farm"] for f in company_farms],
				"shift_types": ["Day", "Night"],
				"statuses": ["Active", "Cancelled"],
				"companies": [c.name for c in companies],
			},
		}
	except Exception as e:
		return {"success": False, "error": str(e)}


# =============================================================================
# SECTION 9   ASSETS
# =============================================================================
#
# Guards scan the QR on an ERPNext Asset's printed label ("Asset QR Label"
# print format), which encodes the asset's Desk URL
# (https://<site>/app/asset/ASS-IR-00042). Every scan is checked against
# Asset itself - there is no separate security catalogue to keep in step -
# and recorded as one Asset Scan Log row (Found or Missing). Last-seen,
# last status and the averaged position are derived from those rows.
#
# Security Asset, the old auto-registering catalogue for blank pre-printed
# stickers, is no longer written to.

# A scan of one of these is still logged, but raised as an Invalid Asset
# Scan: the asset should not be on a farm any more.
_RETIRED_ASSET_STATUSES = ("Sold", "Scrapped", "Cancelled")


def _asset_name_from_scan(raw):
	"""ASS-IR-00042 from whatever the camera read.

	Accepts the label's full URL (any host, with or without a trailing slash,
	query or fragment) or a bare asset name typed in by hand.
	"""
	raw = _s(raw)
	marker = "/app/asset/"
	if marker in raw:
		raw = raw.split(marker, 1)[1]
		for sep in ("?", "#", "/"):
			raw = raw.split(sep, 1)[0]
		raw = urllib.parse.unquote(raw)
	return raw.strip()


def _asset_scanner():
	"""Who is scanning: (personel, internal_guard, external_guard, farm, company).

	Employee linked to this login first (Internal Guard), else a Security
	Guard matched on the user's full name (External Guard). Any of them may be
	None.
	"""
	emp = frappe.db.get_value(
		"Employee", {"user_id": frappe.session.user}, ["name", "custom_farm", "company"], as_dict=True
	)
	if emp:
		return "Internal Guard", emp.name, None, emp.custom_farm, emp.company

	user_full = frappe.db.get_value("User", frappe.session.user, "full_name") or ""
	guard = None
	if user_full:
		guard = frappe.db.get_value(
			"Security Guard", {"full_name": user_full}, ["name", "farm", "company"], as_dict=True
		)
	if guard:
		return "External Guard", None, guard.name, guard.farm, guard.company
	return None, None, None, None, None


def _asset_fields():
	"""Asset fields to read. `farm` is a site-level custom field on production
	and absent elsewhere, so it is only asked for where it exists."""
	fields = ["name", "asset_name", "asset_category", "company", "location", "status", "docstatus"]
	if frappe.get_meta("Asset").has_field("farm"):
		fields.append("farm")
	return fields


def _asset_is_retired(asset):
	return asset.docstatus == 2 or asset.status in _RETIRED_ASSET_STATUSES


def _log_asset_scan(asset, status, latitude, longitude, accuracy, remarks):
	personel, internal_guard, external_guard, farm, company = _asset_scanner()
	log = frappe.new_doc("Asset Scan Log")
	log.asset = asset.name
	log.asset_name = asset.asset_name
	log.asset_status = asset.status
	log.status = status
	log.scanned_at = frappe.utils.now_datetime()
	log.scanned_by = frappe.session.user
	log.personel = personel
	log.internal_guard = internal_guard
	log.external_guard = external_guard
	log.farm = farm
	log.company = company
	log.latitude = frappe.utils.flt(latitude) if latitude else None
	log.longitude = frappe.utils.flt(longitude) if longitude else None
	log.gps_accuracy = frappe.utils.flt(accuracy) if accuracy else None
	log.remarks = remarks
	log.flags.ignore_links = True
	log.insert(ignore_permissions=True)
	return log


def _invalid_asset_scan(reference, detail):
	"""Best-effort alert; log_unauthorized_access never raises."""
	_, _, _, farm, company = _asset_scanner()
	log_unauthorized_access("Invalid Asset Scan", reference, detail, company, farm)


@frappe.whitelist()
def my_assets_at_farm():
	"""Assets at the calling guard's farm, most recently seen first - feeds the
	"report missing" picker.

	Matched on Asset.farm where the site has that field, else on Asset.location
	(this site's Location names are the farm names). Cancelled, Sold and
	Scrapped assets are left out. Last-seen and last-missing come from Asset
	Scan Log.
	"""
	try:
		_, _, _, farm, _ = _asset_scanner()
		if not farm:
			return {"assets": []}

		farm_column = "farm" if frappe.get_meta("Asset").has_field("farm") else "location"
		rows = frappe.db.sql(
			f"""
			SELECT a.name AS asset_code, a.asset_name, a.asset_category AS category,
			       (SELECT l.status FROM `tabAsset Scan Log` l
			        WHERE l.asset = a.name ORDER BY l.scanned_at DESC LIMIT 1) AS last_status,
			       (SELECT MAX(l.scanned_at) FROM `tabAsset Scan Log` l
			        WHERE l.asset = a.name AND l.status = 'Found') AS last_seen_at,
			       (SELECT MAX(l.scanned_at) FROM `tabAsset Scan Log` l
			        WHERE l.asset = a.name AND l.status = 'Missing') AS last_missing_reported_at
			FROM `tabAsset` a
			WHERE a.`{farm_column}` = %s AND a.docstatus = 1 AND a.status NOT IN %s
			ORDER BY COALESCE(last_seen_at, '1970-01-01') DESC, a.asset_name
			LIMIT 1000
			""",
			(farm, _RETIRED_ASSET_STATUSES),
			as_dict=True,
		)
		return {
			"assets": [
				{
					"asset_code": r.asset_code,
					"asset_name": r.asset_name,
					"category": r.category,
					"last_status": r.last_status,
					"last_seen_at": str(r.last_seen_at) if r.last_seen_at else None,
					"last_missing_reported_at": str(r.last_missing_reported_at)
					if r.last_missing_reported_at
					else None,
				}
				for r in rows
			]
		}
	except Exception as e:
		frappe.log_error("my_assets_at_farm", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def scan_asset(asset_code=None, latitude=None, longitude=None, accuracy=None):
	"""Guard scans an Asset's QR label: logs it as Found.

	asset_code is whatever the camera read - normally the label's URL. It must
	resolve to an existing Asset; anything else is refused and raised as an
	Invalid Asset Scan rather than registered. A Cancelled, Sold or Scrapped
	asset is still logged (it was seen) but also raised, and the response
	carries a `warning` for the guard.

	The response keeps the shape the app already reads: asset_code is the Asset
	name, is_new is always False now, and latitude/longitude are the average of
	every Found scan of this asset.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_asset_scanning") == 0:
			raise Exception("This feature is not enabled on this instance.")

		scanned = _s(asset_code)
		name = _asset_name_from_scan(scanned)
		if not name:
			return {"error": "asset_code is required"}
		if not latitude or not longitude:
			return {"error": "latitude and longitude are required"}

		asset = frappe.db.get_value("Asset", name, _asset_fields(), as_dict=True)
		if not asset:
			_invalid_asset_scan(scanned, "Scanned code '" + scanned + "' is not a registered Asset.")
			return {"error": "This QR code is not a registered asset."}

		warning = None
		if _asset_is_retired(asset):
			status_label = "Cancelled" if asset.docstatus == 2 else asset.status
			warning = asset.name + " is recorded as " + status_label + " - report this to your supervisor."
			_invalid_asset_scan(
				asset.name,
				"Asset " + asset.name + " (" + (asset.asset_name or "") + ") is " + status_label
				+ " but was scanned on patrol.",
			)

		_log_asset_scan(asset, "Found", latitude, longitude, accuracy, warning)
		frappe.db.commit()

		agg = frappe.db.sql(
			"""
			SELECT AVG(latitude) AS lat, AVG(longitude) AS lng, COUNT(*) AS n
			FROM `tabAsset Scan Log`
			WHERE asset = %s AND status = 'Found' AND latitude IS NOT NULL AND longitude IS NOT NULL
			""",
			(asset.name,),
			as_dict=True,
		)[0]

		return {
			"asset_code": asset.name,
			"asset_name": asset.asset_name,
			"category": asset.asset_category,
			"farm": asset.get("farm") or asset.location,
			"asset_status": asset.status,
			"is_new": False,
			"warning": warning,
			"latitude": str(agg.lat) if agg.lat is not None else None,
			"longitude": str(agg.lng) if agg.lng is not None else None,
			"location_sample_count": agg.n,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("scan_asset", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def report_asset_missing(asset_code=None, latitude=None, longitude=None, accuracy=None, remarks=None):
	"""Guard reports an Asset as missing: logs it as Missing. GPS is optional.

	asset_code is an Asset name (from the my_assets_at_farm picker) or a label
	URL. Unknown assets are refused.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_asset_scanning") == 0:
			raise Exception("This feature is not enabled on this instance.")

		name = _asset_name_from_scan(asset_code)
		if not name:
			return {"error": "asset_code is required"}

		asset = frappe.db.get_value("Asset", name, _asset_fields(), as_dict=True)
		if not asset:
			return {"error": "Unknown asset " + name + "."}

		log = _log_asset_scan(asset, "Missing", latitude, longitude, accuracy, _s(remarks) or None)
		frappe.db.commit()

		return {"asset_code": asset.name, "status": "Missing", "reported_at": str(log.scanned_at)}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("report_asset_missing", str(e))
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


@frappe.whitelist()
def approve_staff_sticker_request(request_name=None):
	"""Approve a pending Staff Vehicle Sticker Request: mint the next sticker
	number for the employee's company and create an Active Staff Vehicle Sticker.

	Only System Manager / Security Head (roles read straight from tabHas Role).

	Known weak spots, kept as-is: (1) next sticker_number is MAX()+1 read then
	written with no lock, so two concurrent approvals for one company can mint the
	same number; (2) the sticker is committed before the request is flipped to
	Approved, so a failure in between leaves an Active sticker and a still-Pending
	request (a retry would create a second sticker). The two commits are load-bearing
	in that order. Employee.status is fetched but not checked.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_vehicle_stickers") == 0:
			raise Exception("This feature is not enabled on this instance.")
		allowed_roles = ("System Manager", "Security Head")
		role_rows = frappe.db.sql(
			"SELECT role FROM `tabHas Role` WHERE parent = %s", (frappe.session.user,)
		)
		caller_roles = []
		for row in role_rows:
			if row and row[0]:
				caller_roles.append(row[0])
		if not any(r in caller_roles for r in allowed_roles):
			return {"error": "Only System Manager or Security Head can approve a sticker request."}

		request_name = str(request_name or "").strip()

		if not request_name:
			return {"error": "request_name is required."}

		req = frappe.db.get_value(
			"Staff Vehicle Sticker Request",
			request_name,
			["name", "employee", "vehicle_type", "plate_number", "color", "status"],
			as_dict=True,
		)
		if not req:
			return {"error": "Request " + request_name + " not found."}
		if req.status != "Pending":
			return {"error": "This request is already " + str(req.status) + "."}

		emp = frappe.db.get_value("Employee", req.employee, ["name", "company", "status"], as_dict=True)
		if not emp or not emp.company:
			return {"error": "Could not resolve the employee's company."}

		existing_max = frappe.db.sql(
			"SELECT MAX(sticker_number) FROM `tabStaff Vehicle Sticker` WHERE company=%s",
			(emp.company,),
		)
		next_number = 1
		if existing_max and existing_max[0] and existing_max[0][0]:
			next_number = int(existing_max[0][0]) + 1

		sticker = frappe.new_doc("Staff Vehicle Sticker")
		sticker.flags.ignore_permissions = True
		sticker.company = emp.company
		sticker.sticker_number = next_number
		sticker.employee = emp.name
		sticker.vehicle_type = req.vehicle_type
		sticker.plate_number = req.plate_number
		sticker.color = req.color
		sticker.status = "Active"
		sticker.insert(ignore_permissions=True)
		frappe.db.commit()

		frappe.db.set_value(
			"Staff Vehicle Sticker Request",
			request_name,
			{"status": "Approved", "linked_sticker": sticker.name},
		)
		frappe.db.commit()

		return {
			"success": True,
			"sticker": sticker.name,
			"request": request_name,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("approve_staff_sticker_request", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def search_staff_vehicle_sticker(reference=None):
	"""Look up the staff member behind a Staff Vehicle Sticker (gate scan).

	Read-only. Error shape is {"found": False, "error": ...}, including in the
	except, because the mobile client branches on `found`. Only an Active sticker
	with an employee, whose Employee is Active (or has no status), resolves.
	Note: the lookup is by document name, so `reference` must be the sticker's name.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_vehicle_stickers") == 0:
			raise Exception("This feature is not enabled on this instance.")

		reference = str(reference or "").strip()

		if not reference:
			return {"found": False, "error": "A sticker reference is required."}

		sticker = frappe.db.get_value(
			"Staff Vehicle Sticker",
			reference,
			["name", "status", "employee", "vehicle_type", "plate_number", "color"],
			as_dict=True,
		)
		if not sticker:
			return {"found": False, "error": "No Staff Vehicle Sticker found for that reference."}
		if sticker.status != "Active" or not sticker.employee:
			status_label = sticker.status or "Unassigned"
			return {
				"found": False,
				"error": "This sticker is not currently assigned to a staff member (status: " + status_label + ").",
			}

		emp = frappe.db.get_value(
			"Employee",
			sticker.employee,
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
			return {
				"found": False,
				"error": "This sticker points to an employee record that no longer exists.",
			}
		if emp.status and emp.status != "Active":
			return {
				"found": False,
				"error": "Employee status is " + str(emp.status),
			}

		return {
			"found": True,
			"employee_id": emp.name,
			"full_name": emp.employee_name or "",
			"department": emp.department or "",
			"designation": emp.designation or "",
			"company": emp.company or "",
			"default_shift": emp.default_shift or "",
			"custom_farm": emp.custom_farm or "",
			"custom_employee_category": emp.employee_category or "",
			"vehicle_type": sticker.vehicle_type or "",
			"plate_number": sticker.plate_number or "",
			"color": sticker.color or "",
		}
	except Exception as e:
		frappe.log_error("search_staff_vehicle_sticker", str(e))
		return {"found": False, "error": str(e)}


@frappe.whitelist(allow_guest=True)
def submit_staff_sticker_request(
	employee=None,
	vehicle_type=None,
	plate_number=None,
	color=None,
	collection_farm=None,
	collection_point=None,
):
	"""Staff submit a vehicle/motorcycle sticker request by Employee ID.

	allow_guest=True is load-bearing: staff submit this without a login
	(the original is a guest endpoint); a 403 logs the mobile user out.
	Gated by feature_vehicle_stickers. Only Active employees may request
	(a blank status is tolerated). Colour is required for "Vehicle" only,
	not "Motorcycle". A Pending request for the same employee+plate is
	rejected, returning the existing request name under "existing".

	The doc is inserted with ignore_permissions because the caller is a Guest.
	"""
	try:
		if frappe.db.get_single_value("Security Ops Settings", "feature_vehicle_stickers") == 0:
			raise Exception("This feature is not enabled on this instance.")

		employee = str(employee or "").strip()
		vehicle_type = str(vehicle_type or "").strip()
		plate_number = str(plate_number or "").strip()
		color = str(color or "").strip()
		collection_farm = str(collection_farm or "").strip()
		collection_point = str(collection_point or "").strip()

		if not employee:
			return {"error": "Employee ID is required."}
		elif vehicle_type not in ("Vehicle", "Motorcycle"):
			return {"error": "vehicle_type must be Vehicle or Motorcycle."}
		elif not plate_number:
			return {"error": "Plate number is required."}
		elif vehicle_type == "Vehicle" and not color:
			return {"error": "Color is required for a vehicle."}
		elif not collection_farm:
			return {"error": "Collection farm is required."}
		elif not collection_point:
			return {"error": "Collection point is required."}
		else:
			emp = frappe.db.get_value("Employee", employee, ["name", "employee_name", "status"], as_dict=True)
			if not emp:
				return {"error": "Employee " + employee + " not found."}
			elif emp.status and emp.status != "Active":
				return {"error": "Employee status is " + str(emp.status) + " - only active staff can request a sticker."}
			else:
				existing = frappe.db.get_value(
					"Staff Vehicle Sticker Request",
					{"employee": emp.name, "plate_number": plate_number, "status": "Pending"},
					"name",
				)
				if existing:
					return {
						"error": "A request for this plate is already pending review.",
						"existing": existing,
					}
				else:
					req = frappe.new_doc("Staff Vehicle Sticker Request")
					req.flags.ignore_permissions = True
					req.employee = emp.name
					req.vehicle_type = vehicle_type
					req.plate_number = plate_number
					req.color = color
					req.collection_farm = collection_farm
					req.collection_point = collection_point
					req.status = "Pending"
					req.insert(ignore_permissions=True)
					frappe.db.commit()
					return {
						"success": True,
						"name": req.name,
						"employee_name": emp.employee_name or "",
					}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("submit_staff_sticker_request", str(e))
		return {"error": str(e)}


# =============================================================================
# SECTION 11   DASHBOARDS & REPORTS
# =============================================================================


@frappe.whitelist()
def daily_summary(date=None):
	"""Gate-guard 'Summary' tab: one day's appointments plus check-in/out counts.

	Read-only. `date` is YYYY-MM-DD and defaults to today. The day is selected
	on Appointment.scheduled_time, NOT on check-in time, so a visitor who was
	scheduled yesterday but checked in today is not counted here.

	Access scoping (this endpoint is the only thing standing between a guard
	and other companies' visitor data, so the order matters):
	  - System Manager: everything.
	  - Security Head: whatever their own User Permission rows (Company and/or
		Farm) grant, which can be broader or narrower than a single farm.
	  - Anyone else (gate guard): their own company/farm, resolved the same way
		as get_security_head_contact -- Employee first, then Security Guard
		matched by full name.
	A user with no resolvable company/farm gets `AND 1=0` (empty), never
	"everything". Rows are filtered on the stamped custom_company /
	custom_farmunit columns on Appointment.

	still_inside = checked in but not checked out, within the day's rows only
	(and the 200-row LIMIT), so it is a day-view figure, not a live headcount.
	"""
	try:
		date_str = ""
		try:
			date_str = str(date or "").strip()
		except (KeyError, TypeError):
			date_str = ""
		if not date_str:
			date_str = str(frappe.utils.nowdate())

		start = date_str + " 00:00:00"
		end = date_str + " 23:59:59"

		current_user = frappe.session.user
		roles = _user_roles(current_user)

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

		# Only placeholders are generated dynamically; every value is bound.
		scope_sql = ""
		scope_params = []
		if not is_system_manager:
			conditions = []
			if scope_companies:
				placeholders = ", ".join(["%s"] * len(scope_companies))
				conditions.append("a.custom_company IN (" + placeholders + ")")
				scope_params = scope_params + scope_companies
			if scope_farms:
				placeholders = ", ".join(["%s"] * len(scope_farms))
				conditions.append("a.custom_farmunit IN (" + placeholders + ")")
				scope_params = scope_params + scope_farms
			if conditions:
				scope_sql = " AND (" + " OR ".join(conditions) + ")"
			else:
				scope_sql = " AND 1=0"

		rows = frappe.db.sql(
			"""
			SELECT a.name, a.customer_name, a.customer_phone_number,
				   a.customer_organization,
				   a.custom_meet_with, e.employee_name AS host_name,
				   a.workflow_state, a.custom_reporting_status,
				   a.custom_check_in_time, a.custom_check_out_time,
				   a.scheduled_time, a.custom_mode_of_transport,
				   a.custom_vehicles_number_plate, a.custom_vehicles_colour,
				   a.custom_number_of_passengers, a.custom_visitor_type,
				   a.custom_contractor_ref, a.custom_temp_exit_time,
				   a.customer_details
			FROM `tabAppointment` a
			LEFT JOIN `tabEmployee` e ON e.name = a.custom_meet_with
			WHERE a.scheduled_time BETWEEN %s AND %s
			"""
			+ scope_sql
			+ """
			ORDER BY a.custom_check_in_time DESC, a.scheduled_time DESC
			LIMIT 200
			""",
			[start, end] + scope_params,
			as_dict=True,
		)

		all_records = []
		for r in rows:
			all_records.append(
				{
					"name": r.name,
					"customer_name": r.customer_name or "",
					"customer_phone_number": r.customer_phone_number or "",
					"customer_organization": r.customer_organization or "",
					"custom_meet_with": r.custom_meet_with or "",
					"host_name": r.host_name or r.custom_meet_with or "",
					"workflow_state": r.workflow_state or "",
					"custom_reporting_status": r.custom_reporting_status or "",
					"custom_check_in_time": str(r.custom_check_in_time) if r.custom_check_in_time else "",
					"custom_check_out_time": str(r.custom_check_out_time) if r.custom_check_out_time else "",
					"scheduled_time": str(r.scheduled_time) if r.scheduled_time else "",
					"custom_mode_of_transport": r.custom_mode_of_transport or "",
					"custom_vehicles_number_plate": r.custom_vehicles_number_plate or "",
					"custom_vehicles_colour": r.custom_vehicles_colour or "",
					"custom_number_of_passengers": r.custom_number_of_passengers or 0,
					"custom_visitor_type": r.custom_visitor_type or "Visitor",
					"custom_contractor_ref": r.custom_contractor_ref or "",
					"custom_temp_exit_time": str(r.custom_temp_exit_time) if r.custom_temp_exit_time else "",
					"customer_details": r.customer_details or "",
				}
			)

		checked_in = 0
		checked_out = 0
		still_inside = []
		for a in all_records:
			if a["custom_check_in_time"]:
				checked_in = checked_in + 1
				if not a["custom_check_out_time"]:
					still_inside.append(a)
			if a["custom_check_out_time"]:
				checked_out = checked_out + 1

		return {
			"date": date_str,
			"total_checked_in": checked_in,
			"total_checked_out": checked_out,
			"still_inside": len(still_inside),
			"still_inside_list": still_inside,
			"all": all_records,
		}
	except Exception as e:
		frappe.log_error("daily_summary", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def gate_activity():
	"""Gate-guard 'Activity' tab: recent appointments in states the other tabs don't cover.

	Read-only, takes no parameters, and has NO company/farm scoping (unlike
	daily_summary) -- every guard sees every farm's rows. Pre-existing; kept.

	Approved-by-Host / Checked-In appear on the Approved tab and Checked-Out on
	the Summary tab, so this feed is everything else: pending reviews,
	reschedules, redirects and rejections. The window is the last 7 days on
	`modified` (not scheduled_time) because pending/rescheduled/redirected
	states often span days and a rejection may not have been seen yet.
	Rows are ordered by actionability (Pending Host Review first, rejections
	last), then most recently modified, capped at 200.

	For rejected/rescheduled/redirected rows the actor and reason are not
	fields on Appointment; they live in the latest matching Comment the
	client script wrote, which is parsed back out of its HTML.
	"""
	try:
		states = (
			"Open",
			"Pending Secretary Review",
			"Pending Host Review",
			"Approved by Secretary",
			"Rescheduled by Secretary",
			"Rescheduled by Host",
			"Redirected to Another Host",
			"Rejected by Secretary",
			"Rejected by Host",
		)

		today = frappe.utils.nowdate()
		window_start = str(frappe.utils.add_days(today, -7)) + " 00:00:00"

		placeholders = ",".join(["%s"] * len(states))

		rows = frappe.db.sql(
			"""
			SELECT a.name, a.customer_name, a.customer_phone_number,
				   a.customer_details, a.scheduled_time, a.workflow_state,
				   a.modified, a.custom_meet_with,
				   e.employee_name AS host_name
			FROM `tabAppointment` a
			LEFT JOIN `tabEmployee` e ON e.name = a.custom_meet_with
			WHERE a.workflow_state IN ("""
			+ placeholders
			+ """)
			  AND a.modified >= %s
			ORDER BY
			  CASE a.workflow_state
				WHEN 'Pending Host Review'        THEN 1
				WHEN 'Pending Secretary Review'   THEN 2
				WHEN 'Approved by Secretary'      THEN 3
				WHEN 'Rescheduled by Host'        THEN 4
				WHEN 'Rescheduled by Secretary'   THEN 5
				WHEN 'Redirected to Another Host' THEN 6
				WHEN 'Open'                       THEN 7
				WHEN 'Rejected by Host'           THEN 8
				WHEN 'Rejected by Secretary'      THEN 9
				ELSE 99
			  END,
			  a.modified DESC
			LIMIT 200
			""",
			tuple(states) + (window_start,),
			as_dict=True,
		)

		# State -> Comment content prefix the client script writes.
		state_prefix = {
			"Rejected by Host": "<b>Rejected by",
			"Rejected by Secretary": "<b>Rejected by",
			"Rescheduled by Host": "<b>Rescheduled by",
			"Rescheduled by Secretary": "<b>Rescheduled by",
			"Redirected to Another Host": "<b>Redirected by",
		}

		result = []
		for r in rows:
			# The original wrapped each lookup in try/except KeyError only
			# because the sandbox forbids dict.get(); all columns are always
			# selected, so .get() is behaviourally identical.
			nm = str(r.get("name")) if r.get("name") else ""
			cust = str(r.get("customer_name")) if r.get("customer_name") else ""
			phone = str(r.get("customer_phone_number")) if r.get("customer_phone_number") else ""
			purpose = str(r.get("customer_details")) if r.get("customer_details") else ""
			sched = str(r.get("scheduled_time")) if r.get("scheduled_time") else ""
			wf = str(r.get("workflow_state")) if r.get("workflow_state") else ""
			mod = str(r.get("modified")) if r.get("modified") else ""
			host_id = str(r.get("custom_meet_with")) if r.get("custom_meet_with") else ""
			hname = str(r.get("host_name")) if r.get("host_name") else host_id

			actor = ""
			reason = ""
			extra_label = ""
			extra_value = ""
			prefix = state_prefix.get(wf, "")
			if prefix and nm:
				c_rows = frappe.db.sql(
					"""
					SELECT content
					FROM `tabComment`
					WHERE reference_doctype = 'Appointment'
					  AND reference_name = %s
					  AND comment_type = 'Comment'
					  AND content LIKE %s
					ORDER BY creation DESC
					LIMIT 1
					""",
					(nm, prefix + "%"),
					as_dict=True,
				)
				if c_rows:
					parsed = _parse_gate_activity_comment(wf, c_rows[0].content)
					actor = parsed["actor"]
					reason = parsed["reason"]
					extra_label = parsed["extra_label"]
					extra_value = parsed["extra_value"]

			result.append({
				"name": nm,
				"customer_name": cust,
				"phone": phone,
				"purpose": purpose,
				"scheduled_time": sched,
				"workflow_state": wf,
				"modified": mod,
				"host_id": host_id,
				"host_name": hname,
				"actor": actor,
				"reason": reason,
				"extra_label": extra_label,
				"extra_value": extra_value,
			})

		return result
	except Exception as e:
		frappe.log_error("gate_activity", str(e))
		return {"error": str(e)}
@frappe.whitelist()
def security_report(tab=None, from_date=None, to_date=None, farm=None, location=None):
	"""Command Center / dashboard report, one payload shape for seven tabs.

	Read-only. Response: {tab, from_date, to_date, kpis[], tables[], watch[]}
	plus tab-specific extras (farms / locations / details / points). `tab` is
	one of visitors, contractors, staff, vehicles, incidents, patrols;
	anything else (including empty) falls through to the overview.

	What the numbers mean:
	  - Appointment counts are by custom_check_in_time / custom_check_out_time
		inside the range; "Still Inside" ignores the range (checked in, never
		checked out, right now). Visitors = everything not a Contractor.
	  - "Vehicles" are Timesheets linked from a Tractor Daily Task: docstatus 0
		(draft) means the vehicle is still inside, docstatus 1 means exited.
	  - Overstay watchlists: visitors/contractors inside > 8h, vehicles > 12h.
	  - Overview "On Premises" = visitors/contractors inside + vehicles inside
		(all-time, unfiltered); "Open Incidents" is likewise all-time.
	  - Patrol distance is a haversine sum over consecutive GPS points per
		patrol, ignoring jumps >= 0.5 degree lat/lng (GPS glitches).

	Filters: `farm` only applies to the visitors/contractors tabs (via
	Appointment.custom_farmunit); `location` only to the incidents tab. The
	staff, vehicles, patrols and overview tabs ignore both. Pre-existing.

	Only placeholders / fixed constants are concatenated into SQL; every
	user-supplied value is bound. scalar() swallows any query error and
	returns 0, so a broken query shows as a zero KPI rather than an error --
	load-bearing for the dashboard but it hides schema drift.
	"""
	try:
		def s(v):
			if v is None:
				return ""
			return str(v).strip()

		tab = s(tab) or "overview"
		fromd = s(from_date) or str(frappe.utils.nowdate())
		tod = s(to_date) or str(frappe.utils.nowdate())
		farm = s(farm)
		loc = s(location)
		start = fromd + " 00:00:00"
		end = tod + " 23:59:59"
		now = frappe.utils.now_datetime()

		FARM_SQL = ""
		FARM_P = []
		if farm:
			FARM_SQL = " AND a.custom_farmunit = %s"
			FARM_P = [farm]
		LOC_SQL = ""
		LOC_P = []
		if loc:
			LOC_SQL = " AND location = %s"
			LOC_P = [loc]

		kpis = []
		tables = []
		watch = []
		extra = {}

		def scalar(q, params):
			try:
				r = frappe.db.sql(q, params)
				if r and r[0] and r[0][0] is not None:
					return r[0][0]
			except Exception:
				return 0
			return 0

		def kpi(label, value, sub):
			kpis.append({"label": label, "value": value, "sub": sub})

		def add_table(title, columns, rows):
			tables.append({"title": title, "columns": columns, "rows": rows})

		def add_watch(title, tone, rows):
			watch.append({"title": title, "tone": tone, "rows": rows})

		def farm_options():
			fl = []
			fr = frappe.db.sql("SELECT DISTINCT custom_farmunit FROM `tabAppointment` WHERE custom_farmunit IS NOT NULL AND custom_farmunit != '' ORDER BY custom_farmunit LIMIT 100", ())
			for row in fr:
				fl.append(row[0])
			return fl

		VIS = "(COALESCE(a.custom_visitor_type,'') <> 'Contractor')"
		CON = "a.custom_visitor_type = 'Contractor'"

		def appt_kpis(who):
			ci = scalar("SELECT COUNT(*) FROM `tabAppointment` a WHERE " + who + FARM_SQL + " AND a.custom_check_in_time BETWEEN %s AND %s", tuple(FARM_P + [start, end]))
			co = scalar("SELECT COUNT(*) FROM `tabAppointment` a WHERE " + who + FARM_SQL + " AND a.custom_check_out_time BETWEEN %s AND %s", tuple(FARM_P + [start, end]))
			inside = scalar("SELECT COUNT(*) FROM `tabAppointment` a WHERE " + who + FARM_SQL + " AND a.custom_check_in_time IS NOT NULL AND a.custom_check_out_time IS NULL", tuple(FARM_P))
			avg = scalar("SELECT ROUND(AVG(TIMESTAMPDIFF(MINUTE, a.custom_check_in_time, a.custom_check_out_time))) FROM `tabAppointment` a WHERE " + who + FARM_SQL + " AND a.custom_check_out_time BETWEEN %s AND %s", tuple(FARM_P + [start, end]))
			return [ci, co, inside, avg]

		def host_rows(who):
			rows = []
			r = frappe.db.sql("SELECT COALESCE(NULLIF(e.employee_name,''), a.custom_meet_with, '—') h, COUNT(*) c FROM `tabAppointment` a LEFT JOIN `tabEmployee` e ON e.name = a.custom_meet_with WHERE " + who + FARM_SQL + " AND a.custom_check_in_time BETWEEN %s AND %s GROUP BY h ORDER BY c DESC LIMIT 10", tuple(FARM_P + [start, end]))
			for row in r:
				rows.append({"host": row[0] or "—", "count": row[1]})
			return rows

		def overstay_rows(who):
			rows = []
			r = frappe.db.sql("SELECT a.customer_name, COALESCE(NULLIF(e.employee_name,''), a.custom_meet_with, '—'), a.custom_check_in_time FROM `tabAppointment` a LEFT JOIN `tabEmployee` e ON e.name = a.custom_meet_with WHERE " + who + FARM_SQL + " AND a.custom_check_in_time IS NOT NULL AND a.custom_check_out_time IS NULL AND a.custom_check_in_time < %s ORDER BY a.custom_check_in_time ASC LIMIT 25", tuple(FARM_P + [frappe.utils.add_to_date(now, hours=-8)]))
			for row in r:
				hrs = 0
				try:
					hrs = round(frappe.utils.time_diff_in_hours(now, row[2]), 1)
				except Exception:
					hrs = 0
				rows.append({"label": (row[0] or "—") + " · " + str(row[1]), "detail": str(hrs) + "h inside"})
			return rows

		if tab == "visitors":
			k = appt_kpis(VIS)
			kpi("Checked In", k[0], "in range")
			kpi("Checked Out", k[1], "in range")
			kpi("Still Inside", k[2], "now")
			kpi("Avg Visit", (str(k[3]) + "m") if k[3] else "—", "duration")
			add_table("Top Hosts", [{"key": "host", "label": "Host"}, {"key": "count", "label": "Visits", "align": "right"}], host_rows(VIS))
			fr = []
			# Approval states are counted by creation date, not check-in.
			r = frappe.db.sql("SELECT COALESCE(NULLIF(a.workflow_state,''),'—') w, COUNT(*) c FROM `tabAppointment` a WHERE " + VIS + FARM_SQL + " AND a.creation BETWEEN %s AND %s GROUP BY w ORDER BY c DESC", tuple(FARM_P + [start, end]))
			for row in r:
				fr.append({"state": row[0], "count": row[1]})
			add_table("Approval States", [{"key": "state", "label": "Workflow State"}, {"key": "count", "label": "Count", "align": "right"}], fr)
			add_watch("Overstays (>8h inside)", "danger", overstay_rows(VIS))
			extra["farms"] = farm_options()

		elif tab == "contractors":
			k = appt_kpis(CON)
			companies = scalar("SELECT COUNT(DISTINCT COALESCE(a.custom_contractor_ref, a.customer_name)) FROM `tabAppointment` a WHERE " + CON + FARM_SQL + " AND a.custom_check_in_time BETWEEN %s AND %s", tuple(FARM_P + [start, end]))
			kpi("Visits", k[0], "checked in")
			kpi("On Site", k[2], "now")
			kpi("Avg Visit", (str(k[3]) + "m") if k[3] else "—", "duration")
			kpi("Companies", companies, "distinct")
			crows = []
			r = frappe.db.sql("SELECT COALESCE(a.custom_contractor_ref, a.customer_name, '—') n, COUNT(*) c FROM `tabAppointment` a WHERE " + CON + FARM_SQL + " AND a.custom_check_in_time BETWEEN %s AND %s GROUP BY n ORDER BY c DESC LIMIT 10", tuple(FARM_P + [start, end]))
			for row in r:
				crows.append({"company": row[0] or "—", "count": row[1]})
			add_table("By Contractor", [{"key": "company", "label": "Contractor"}, {"key": "count", "label": "Visits", "align": "right"}], crows)
			add_table("Top Hosts", [{"key": "host", "label": "Host"}, {"key": "count", "label": "Visits", "align": "right"}], host_rows(CON))
			add_watch("On-site overstays (>8h)", "warn", overstay_rows(CON))
			extra["farms"] = farm_options()

		elif tab == "staff":
			total = scalar("SELECT COUNT(*) FROM `tabAttendance` WHERE attendance_date BETWEEN %s AND %s AND docstatus < 2", (fromd, tod))
			present = scalar("SELECT COUNT(*) FROM `tabAttendance` WHERE attendance_date BETWEEN %s AND %s AND status = 'Present' AND docstatus < 2", (fromd, tod))
			distinct_emp = scalar("SELECT COUNT(DISTINCT employee) FROM `tabAttendance` WHERE attendance_date BETWEEN %s AND %s AND docstatus < 2", (fromd, tod))
			late = scalar("SELECT COUNT(*) FROM `tabAttendance` WHERE attendance_date BETWEEN %s AND %s AND in_time IS NOT NULL AND TIME(in_time) > '08:00:00' AND docstatus < 2", (fromd, tod))
			kpi("Check-ins", total, "in range")
			kpi("Present", present, "records")
			kpi("Staff", distinct_emp, "distinct")
			kpi("Late (>8am)", late, "arrivals")
			drows = []
			r = frappe.db.sql("SELECT COALESCE(NULLIF(department,''),'—') d, COUNT(*) c FROM `tabAttendance` WHERE attendance_date BETWEEN %s AND %s AND docstatus < 2 GROUP BY d ORDER BY c DESC LIMIT 12", (fromd, tod))
			for row in r:
				drows.append({"dept": row[0], "count": row[1]})
			add_table("By Department", [{"key": "dept", "label": "Department"}, {"key": "count", "label": "Records", "align": "right"}], drows)

		elif tab == "vehicles":
			GTS = "`tabTimesheet` ts JOIN `tabTractor Daily Task` tdt ON tdt.timesheet = ts.name"
			inside = scalar("SELECT COUNT(*) FROM " + GTS + " WHERE ts.docstatus = 0", ())
			entries = scalar("SELECT COUNT(*) FROM " + GTS + " WHERE ts.creation BETWEEN %s AND %s", (start, end))
			exited = scalar("SELECT COUNT(*) FROM " + GTS + " WHERE ts.docstatus = 1 AND ts.modified BETWEEN %s AND %s", (start, end))
			avgh = scalar("SELECT ROUND(AVG(td.hours),1) FROM `tabTimesheet Detail` td JOIN `tabTimesheet` ts ON ts.name = td.parent JOIN `tabTractor Daily Task` tdt ON tdt.timesheet = ts.name WHERE ts.docstatus = 1 AND ts.modified BETWEEN %s AND %s", (start, end))
			kpi("Inside", inside, "now")
			kpi("Entries", entries, "in range")
			kpi("Exited", exited, "in range")
			kpi("Avg Time", (str(avgh) + "h") if avgh else "—", "inside")
			frows = []
			r = frappe.db.sql("SELECT COALESCE(NULLIF(tdt.farm,''),'—') f, COUNT(*) c FROM " + GTS + " WHERE ts.creation BETWEEN %s AND %s GROUP BY f ORDER BY c DESC LIMIT 10", (start, end))
			for row in r:
				frows.append({"farm": row[0], "count": row[1]})
			add_table("By Farm", [{"key": "farm", "label": "Farm"}, {"key": "count", "label": "Entries", "align": "right"}], frows)
			vrows = []
			r = frappe.db.sql("SELECT COALESCE(NULLIF(tdt.motor_vehicle,''),'—') v, COUNT(*) c FROM " + GTS + " WHERE ts.creation BETWEEN %s AND %s GROUP BY v ORDER BY c DESC LIMIT 10", (start, end))
			for row in r:
				vrows.append({"vehicle": row[0], "count": row[1]})
			add_table("By Vehicle", [{"key": "vehicle", "label": "Vehicle"}, {"key": "count", "label": "Entries", "align": "right"}], vrows)
			wrows = []
			r = frappe.db.sql("SELECT tdt.motor_vehicle, tdt.name, td.from_time FROM `tabTimesheet` ts JOIN `tabTractor Daily Task` tdt ON tdt.timesheet = ts.name JOIN `tabTimesheet Detail` td ON td.parent = ts.name WHERE ts.docstatus = 0 AND td.from_time < %s ORDER BY td.from_time ASC LIMIT 25", (frappe.utils.add_to_date(now, hours=-12),))
			for row in r:
				wrows.append({"label": str(row[0] or row[1]), "detail": "in since " + str(row[2])})
			add_watch("Vehicles inside >12h", "danger", wrows)

		elif tab == "incidents":
			total = scalar("SELECT COUNT(*) FROM `tabIncident Report` WHERE incident_datetime BETWEEN %s AND %s" + LOC_SQL, tuple([start, end] + LOC_P))
			openc = scalar("SELECT COUNT(*) FROM `tabIncident Report` WHERE incident_datetime BETWEEN %s AND %s AND status = 'Open'" + LOC_SQL, tuple([start, end] + LOC_P))
			crit = scalar("SELECT COUNT(*) FROM `tabIncident Report` WHERE incident_datetime BETWEEN %s AND %s AND severity IN ('High','Critical')" + LOC_SQL, tuple([start, end] + LOC_P))
			kpi("Incidents", total, "in range")
			kpi("Open", openc, "unresolved")
			kpi("High/Critical", crit, "severity")
			sev = []
			r = frappe.db.sql("SELECT COALESCE(NULLIF(severity,''),'—') sv, COUNT(*) c FROM `tabIncident Report` WHERE incident_datetime BETWEEN %s AND %s" + LOC_SQL + " GROUP BY sv ORDER BY c DESC", tuple([start, end] + LOC_P))
			for row in r:
				sev.append({"sev": row[0], "count": row[1]})
			add_table("By Severity", [{"key": "sev", "label": "Severity"}, {"key": "count", "label": "Count", "align": "right"}], sev)
			cat = []
			r = frappe.db.sql("SELECT COALESCE(NULLIF(nature_of_incident,''),'—') n, COUNT(*) c FROM `tabIncident Report` WHERE incident_datetime BETWEEN %s AND %s" + LOC_SQL + " GROUP BY n ORDER BY c DESC LIMIT 10", tuple([start, end] + LOC_P))
			for row in r:
				cat.append({"cat": row[0], "count": row[1]})
			add_table("By Category", [{"key": "cat", "label": "Nature"}, {"key": "count", "label": "Count", "align": "right"}], cat)
			wrows = []
			r = frappe.db.sql("SELECT nature_of_incident, location, severity, incident_datetime FROM `tabIncident Report` WHERE status = 'Open' AND severity IN ('High','Critical')" + LOC_SQL + " ORDER BY incident_datetime DESC LIMIT 25", tuple(LOC_P))
			for row in r:
				wrows.append({"label": str(row[2]) + " · " + str(row[0] or "—"), "detail": str(row[1] or "") + " " + str(row[3])})
			add_watch("Open High/Critical", "danger", wrows)

			def people(nm, pf):
				out = []
				pr = frappe.db.sql("SELECT person_name, person_type, id_number, contact, notes FROM `tabIncident Person` WHERE parent = %s AND parentfield = %s ORDER BY idx", (nm, pf))
				for p in pr:
					out.append({"name": p[0] or "—", "type": p[1] or "", "id_number": p[2] or "", "contact": p[3] or "", "notes": p[4] or ""})
				return out

			details = []
			r = frappe.db.sql("SELECT name, incident_datetime, severity, status, nature_of_incident, location, reporter_name, description, remarks, corrective_actions, resolution, resolution_datetime, assigned_to, attachment_1, attachment_2, attachment_3, attachment_4 FROM `tabIncident Report` WHERE incident_datetime BETWEEN %s AND %s" + LOC_SQL + " ORDER BY incident_datetime DESC LIMIT 40", tuple([start, end] + LOC_P))
			for row in r:
				nm = row[0]
				atts = []
				for att in [row[13], row[14], row[15], row[16]]:
					if att:
						atts.append(att)
				details.append({
					"name": nm,
					"datetime": str(row[1] or ""),
					"severity": row[2] or "",
					"status": row[3] or "",
					"nature": row[4] or "",
					"location": row[5] or "",
					"reporter": row[6] or "",
					"description": row[7] or "",
					"remarks": row[8] or "",
					"corrective_actions": row[9] or "",
					"resolution": row[10] or "",
					"resolution_datetime": str(row[11] or ""),
					"assigned_to": row[12] or "",
					"attachments": atts,
					"witnesses": people(nm, "witnesses"),
					"victims": people(nm, "victims"),
					"responsible": people(nm, "responsible_persons"),
				})
			extra["details"] = details
			ll = []
			lr = frappe.db.sql("SELECT DISTINCT location FROM `tabIncident Report` WHERE location IS NOT NULL AND location != '' ORDER BY location LIMIT 200", ())
			for row in lr:
				ll.append(row[0])
			extra["locations"] = ll

		elif tab == "patrols":
			points = scalar("SELECT COUNT(*) FROM `tabPatrol GPS Log` WHERE captured_at BETWEEN %s AND %s", (start, end))
			routes = scalar("SELECT COUNT(DISTINCT patrol) FROM `tabPatrol GPS Log` WHERE captured_at BETWEEN %s AND %s", (start, end))
			guards = scalar("SELECT COUNT(DISTINCT COALESCE(internal_guard, external_guard)) FROM `tabPatrol GPS Log` WHERE captured_at BETWEEN %s AND %s AND COALESCE(internal_guard, external_guard) IS NOT NULL AND COALESCE(internal_guard, external_guard) != ''", (start, end))
			dist = scalar("SELECT ROUND(SUM(6371 * ACOS(LEAST(1, GREATEST(-1, COS(RADIANS(plat)) * COS(RADIANS(lat)) * COS(RADIANS(lng) - RADIANS(plng)) + SIN(RADIANS(plat)) * SIN(RADIANS(lat)))))), 1) FROM (SELECT CAST(latitude AS DECIMAL(12,7)) lat, CAST(longitude AS DECIMAL(12,7)) lng, LAG(CAST(latitude AS DECIMAL(12,7))) OVER (PARTITION BY patrol ORDER BY captured_at) plat, LAG(CAST(longitude AS DECIMAL(12,7))) OVER (PARTITION BY patrol ORDER BY captured_at) plng FROM `tabPatrol GPS Log` WHERE captured_at BETWEEN %s AND %s AND latitude != '' AND longitude != '') t WHERE plat IS NOT NULL AND ABS(lat - plat) < 0.5 AND ABS(lng - plng) < 0.5", (start, end))
			kpi("GPS Points", points, "logged")
			kpi("Distance", (str(dist) + " km") if dist else "—", "patrolled")
			kpi("Guards", guards, "patrolling")
			kpi("Routes", routes, "distinct")
			prows = []
			r = frappe.db.sql("SELECT COALESCE(NULLIF(COALESCE(internal_guard, external_guard),''),'—') g, COUNT(*) c, COUNT(DISTINCT patrol) rt, MAX(captured_at) m FROM `tabPatrol GPS Log` WHERE captured_at BETWEEN %s AND %s GROUP BY g ORDER BY c DESC LIMIT 15", (start, end))
			for row in r:
				prows.append({"guard": row[0], "count": row[1], "routes": row[2], "last": str(row[3])})
			add_table("By Guard", [{"key": "guard", "label": "Guard"}, {"key": "count", "label": "Points", "align": "right"}, {"key": "routes", "label": "Routes", "align": "right"}, {"key": "last", "label": "Last Seen"}], prows)
			pts = []
			r = frappe.db.sql("SELECT latitude, longitude, captured_at, COALESCE(internal_guard, external_guard), patrol FROM `tabPatrol GPS Log` WHERE captured_at BETWEEN %s AND %s AND latitude != '' AND longitude != '' ORDER BY captured_at DESC LIMIT 3000", (start, end))
			for row in r:
				pts.append({"lat": row[0], "lng": row[1], "at": str(row[2]), "guard": row[3] or "", "patrol": row[4] or ""})
			extra["points"] = pts

		else:
			vis_inside = scalar("SELECT COUNT(*) FROM `tabAppointment` a WHERE a.custom_check_in_time IS NOT NULL AND a.custom_check_out_time IS NULL", ())
			veh_inside = scalar("SELECT COUNT(*) FROM `tabTractor Daily Task` tdt JOIN `tabTimesheet` ts ON tdt.timesheet = ts.name WHERE ts.docstatus = 0", ())
			entries = scalar("SELECT COUNT(*) FROM `tabAppointment` a WHERE a.custom_check_in_time BETWEEN %s AND %s", (start, end))
			open_inc = scalar("SELECT COUNT(*) FROM `tabIncident Report` WHERE status = 'Open'", ())
			patrol_today = scalar("SELECT COUNT(*) FROM `tabPatrol GPS Log` WHERE captured_at BETWEEN %s AND %s", (start, end))
			kpi("On Premises", vis_inside + veh_inside, "people + vehicles")
			kpi("Entries", entries, "in range")
			kpi("Open Incidents", open_inc, "all-time")
			kpi("Patrol Points", patrol_today, "in range")
			brk = []
			vcount = scalar("SELECT COUNT(*) FROM `tabAppointment` a WHERE " + VIS + " AND a.custom_check_in_time BETWEEN %s AND %s", (start, end))
			ccount = scalar("SELECT COUNT(*) FROM `tabAppointment` a WHERE " + CON + " AND a.custom_check_in_time BETWEEN %s AND %s", (start, end))
			vehcount = scalar("SELECT COUNT(*) FROM `tabTractor Daily Task` tdt JOIN `tabTimesheet` ts ON tdt.timesheet = ts.name WHERE ts.creation BETWEEN %s AND %s", (start, end))
			brk.append({"type": "Visitors", "count": vcount})
			brk.append({"type": "Contractors", "count": ccount})
			brk.append({"type": "Vehicles", "count": vehcount})
			add_table("Entries by Type", [{"key": "type", "label": "Type"}, {"key": "count", "label": "Entries", "align": "right"}], brk)

		msg = {"tab": tab, "from_date": fromd, "to_date": tod, "kpis": kpis, "tables": tables, "watch": watch}
		for kk in extra:
			msg[kk] = extra[kk]
		return msg
	except Exception as e:
		frappe.log_error("security_report", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def security_analytics_summary():
	"""Dashboard analytics: 30-day incident counts, patrol coverage, 7-day visitor trend.

	NO role or company/farm scoping -- any authenticated user receives
	site-wide aggregates (preserved from the original). Aggregates only, no PII.

	patrol_coverage_pct = distinct Active shift assignments with a Patrol GPS
	Log point captured in the last hour / Active shift count; None when there
	are no Active shifts. The join matches the guard by Internal/External type
	plus the matching guard link.

	Near misses are Incident Reports with nature_of_incident = "Near Miss" (the
	standalone Near Miss Report doctype is retired). Read-only.
	"""
	try:
		today_str = frappe.utils.today()
		window_start = frappe.utils.add_days(today_str, -30)

		incidents_by_severity = frappe.db.sql(
			"""
			SELECT severity, COUNT(*) as cnt
			FROM `tabIncident Report`
			WHERE incident_datetime >= %(start)s
			GROUP BY severity
			ORDER BY cnt DESC
			""",
			{"start": window_start},
			as_dict=True,
		)

		incidents_by_location = frappe.db.sql(
			"""
			SELECT COALESCE(location, 'Unspecified') as location, COUNT(*) as cnt
			FROM `tabIncident Report`
			WHERE incident_datetime >= %(start)s
			GROUP BY location
			ORDER BY cnt DESC
			LIMIT 10
			""",
			{"start": window_start},
			as_dict=True,
		)

		active_shift_count = frappe.db.count("Security Guard Shift Assignment", {"status": "Active"})
		hour_ago = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-1)
		covered_shifts = frappe.db.sql(
			"""
			SELECT COUNT(DISTINCT sgsa.name) as cnt
			FROM `tabSecurity Guard Shift Assignment` sgsa
			JOIN `tabPatrol GPS Log` pgl
              ON (
                   (sgsa.security_guard = 'Internal Guard' AND pgl.personel = 'Internal Guard' AND pgl.internal_guard = sgsa.internal_guard)
				OR (sgsa.security_guard = 'External Guard' AND pgl.personel = 'External Guard' AND pgl.external_guard = sgsa.external_guard)
              )
			WHERE sgsa.status = 'Active' AND pgl.captured_at >= %(hour_ago)s
			""",
			{"hour_ago": hour_ago},
			as_dict=True,
		)
		covered = covered_shifts[0].cnt if covered_shifts else 0
		patrol_coverage_pct = round((covered / active_shift_count) * 100, 1) if active_shift_count else None

		visitor_daily_trend = frappe.db.sql(
			"""
			SELECT DATE(custom_check_in_time) as day, COUNT(*) as cnt
			FROM `tabAppointment`
			WHERE custom_check_in_time >= %(start)s
			GROUP BY DATE(custom_check_in_time)
			ORDER BY day
			""",
			{"start": frappe.utils.add_days(today_str, -7)},
			as_dict=True,
		)

		near_miss_count_30d = frappe.db.count(
			"Incident Report",
			{"nature_of_incident": "Near Miss", "incident_datetime": [">=", window_start]},
		)

		return {
			"window_days": 30,
			"incidents_by_severity": incidents_by_severity,
			"incidents_by_location": incidents_by_location,
			"active_shift_count": active_shift_count,
			"patrol_coverage_pct": patrol_coverage_pct,
			"visitor_daily_trend": visitor_daily_trend,
			"near_miss_count_30d": near_miss_count_30d,
		}
	except Exception as e:
		frappe.log_error("security_analytics_summary", str(e))
		return {"error": str(e)}




# =============================================================================
# SECTION 12   LEGACY VEHICLE TICKETS
# =============================================================================
#
# The old Tractor Daily Task gate flow. api/gate_vehicle.py replaced it
# (Gate Vehicle Verification), and its docstring explains why this flow never
# worked end to end. It is kept only because installed handset builds still
# call these bare paths - search_vehicle_tickets was seen in the field on
# 2026-10-10. Ported as-is from their Server Scripts; do not extend. Delete
# once no build in the field calls them.


def _legacy_body():
	"""JSON body if there is one, else form_dict - as the Server Scripts read it."""
	data = {}
	try:
		data = frappe.request.get_json(silent=True) or {}
	except Exception:
		data = {}
	if not data:
		data = dict(frappe.form_dict or {})
	return data


@frappe.whitelist()
def search_vehicle_tickets():
	"""Up to 20 Tractor Daily Tasks whose name or vehicle matches `query`. READ-ONLY.

	Blank query returns [] (a list, not an error).
	"""
	try:
		query = _s(_sp_lookup(_legacy_body(), "query"))
		if not query:
			return []

		like = "%" + query + "%"
		rows = frappe.db.sql(
			"""
			SELECT name, motor_vehicle, farm, operator,
			       company, date, erp_task, timesheet
			FROM `tabTractor Daily Task`
			WHERE name LIKE %s OR motor_vehicle LIKE %s
			ORDER BY modified DESC
			LIMIT 20
			""",
			(like, like),
			as_dict=True,
		)
		return [
			{
				"name": r.name,
				"motor_vehicle": r.motor_vehicle or "",
				"farm": r.farm or "",
				"operator": r.operator or "",
				"custom_employee": r.operator or "",
				"company": r.company or "",
				"date": str(r.date) if r.date else "",
				"erp_task": r.erp_task or "",
				"timesheet": r.timesheet or "",
				"workflow_state": "",
			}
			for r in rows
		]
	except Exception as e:
		frappe.log_error("search_vehicle_tickets", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def get_vehicle_ticket():
	"""One Tractor Daily Task (`name`) with its task rows and operator names. READ-ONLY."""
	try:
		name = _s(_sp_lookup(_legacy_body(), "name"))
		if not name:
			return {"error": "name is required"}

		row = frappe.db.get_value(
			"Tractor Daily Task",
			name,
			["name", "motor_vehicle", "farm", "operator", "company", "date", "erp_task", "timesheet", "location"],
			as_dict=True,
		)
		if not row:
			return {"error": "Ticket " + name + " not found"}

		tasks = frappe.get_all(
			"Timesheet Detail",
			filters={"parent": name},
			fields=[
				"name", "activity_type", "description", "from_time", "to_time",
				"hours", "completed", "task", "is_billable",
			],
			order_by="idx asc",
		)

		operator_name = ""
		employee_name = ""
		if row.operator:
			operator_name = frappe.db.get_value("Driver", row.operator, "full_name") or ""
			employee_name = (
				frappe.db.get_value(
					"Employee",
					frappe.db.get_value("Driver", row.operator, "employee"),
					"employee_name",
				)
				or ""
			)

		return {
			"name": row.name,
			"motor_vehicle": row.motor_vehicle or "",
			"farm": row.farm or "",
			"operator": row.operator or "",
			"operator_name": operator_name,
			"custom_employee": row.operator or "",
			"employee_name": employee_name,
			"company": row.company or "",
			"date": str(row.date) if row.date else "",
			"erp_task": row.erp_task or "",
			"timesheet": row.timesheet or "",
			"workflow_state": "",
			"location": row.location or "",
			"custom_qr_code": "",
			"task": [
				{
					"name": t.name,
					"activity_type": t.activity_type or "",
					"description": t.description or "",
					"from_time": str(t.from_time) if t.from_time else "",
					"to_time": str(t.to_time) if t.to_time else "",
					"hours": float(t.hours or 0),
					"completed": int(t.completed or 0),
					"task": t.task or "",
					"is_billable": int(t.is_billable or 0),
				}
				for t in tasks
			],
		}
	except Exception as e:
		frappe.log_error("get_vehicle_ticket", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def mark_vehicle_task_completed():
	"""Set completed=1 on a ticket's task row (`task_row`, else its first row).

	WRITES Timesheet Detail.completed.
	"""
	try:
		data = _legacy_body()
		ticket = _s(_sp_lookup(data, "ticket"))
		task_row = _s(_sp_lookup(data, "task_row"))

		if not ticket:
			return {"error": "ticket is required"}
		if not frappe.db.get_value("Tractor Daily Task", ticket, "name"):
			return {"error": "Ticket " + ticket + " not found"}

		if task_row:
			if not frappe.db.get_value("Timesheet Detail", {"name": task_row, "parent": ticket}, "name"):
				return {"error": "Task row " + task_row + " not on ticket"}
			frappe.db.set_value("Timesheet Detail", task_row, "completed", 1)
			frappe.db.commit()
			return {"ticket": ticket, "task_row": task_row, "completed": 1}

		rows = frappe.get_all(
			"Timesheet Detail",
			filters={"parent": ticket},
			fields=["name"],
			order_by="idx asc",
			limit_page_length=1,
		)
		if not rows:
			return {"ticket": ticket, "task_row": None, "completed": 0, "message": "no task rows on ticket"}

		frappe.db.set_value("Timesheet Detail", rows[0].name, "completed", 1)
		frappe.db.commit()
		return {"ticket": ticket, "task_row": rows[0].name, "completed": 1}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("mark_vehicle_task_completed", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def create_gate_timesheet():
	"""Open a draft Timesheet for a ticket's vehicle leaving the gate.

	WRITES Timesheet (inserted with ignore_permissions). One time log from
	`entry_time` (default now) with a provisional one-hour end; activity,
	description and task come from the ticket's first task row.
	"""
	try:
		data = _legacy_body()
		ticket = _s(_sp_lookup(data, "ticket"))
		entry_time = _s(_sp_lookup(data, "entry_time"))

		if not ticket:
			return {"error": "ticket is required"}
		if not entry_time:
			entry_time = str(frappe.utils.now_datetime())

		ticket_row = frappe.db.get_value(
			"Tractor Daily Task",
			ticket,
			["name", "motor_vehicle", "operator", "company", "farm", "erp_task"],
			as_dict=True,
		)
		if not ticket_row:
			return {"error": "Ticket " + ticket + " not found"}

		first_task = frappe.db.sql(
			"""
			SELECT activity_type, description, task
			FROM `tabTimesheet Detail`
			WHERE parent = %s
			ORDER BY idx ASC
			LIMIT 1
			""",
			(ticket,),
			as_dict=True,
		)
		activity = "Transport"
		description = ""
		task_link = ticket_row.erp_task or ""
		if first_task:
			ft = first_task[0]
			if ft.activity_type:
				activity = ft.activity_type
			if ft.description:
				description = ft.description
			if ft.task and not task_link:
				task_link = ft.task

		ts = frappe.new_doc("Timesheet")
		ts.naming_series = "TS-.YYYY.-"
		if ticket_row.company:
			ts.company = ticket_row.company
		if ticket_row.operator:
			ts.employee = frappe.db.get_value("Driver", ticket_row.operator, "employee")
		ts.custom_asset = ticket_row.motor_vehicle
		ts.start_date = frappe.utils.nowdate()
		ts.end_date = frappe.utils.nowdate()

		provisional_end = frappe.utils.add_to_date(entry_time, hours=1, as_datetime=True)
		ts.append(
			"time_logs",
			{
				"activity_type": activity,
				"from_time": entry_time,
				"to_time": str(provisional_end),
				"hours": 1,
				"expected_hours": 1,
				"description": description,
				"task": task_link,
				"is_billable": 1,
				"completed": 0,
			},
		)
		ts.insert(ignore_permissions=True)
		frappe.db.commit()
		return {
			"name": ts.name,
			"ticket": ticket,
			"entry_time": entry_time,
			"activity_type": activity,
			"description": description,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("create_gate_timesheet", str(e))
		return {"error": str(e)}


@frappe.whitelist()
def submit_gate_timesheet():
	"""Close and submit the Timesheet create_gate_timesheet opened.

	WRITES Timesheet: first time log gets to_time = `exit_time`, real hours
	(minimum 0.01) and `completion_note`, then the doc is submitted. An
	already-submitted Timesheet is reported as success, not an error.
	"""
	try:
		data = _legacy_body()
		timesheet = _s(_sp_lookup(data, "timesheet"))
		exit_time = _s(_sp_lookup(data, "exit_time"))
		completion_note = _s(_sp_lookup(data, "completion_note"))

		if not timesheet:
			return {"error": "timesheet is required"}
		if not exit_time:
			return {"error": "exit_time is required"}
		if not completion_note:
			return {"error": "completion_note is required"}

		existing = frappe.db.get_value("Timesheet", timesheet, ["name", "docstatus"], as_dict=True)
		if not existing:
			return {"error": "Timesheet " + timesheet + " not found"}
		if int(existing.docstatus or 0) == 1:
			return {"name": timesheet, "docstatus": 1, "message": "already submitted"}

		doc = frappe.get_doc("Timesheet", timesheet)
		if not doc.time_logs:
			return {"error": "Timesheet has no time_logs"}
		row = doc.time_logs[0]

		from_sec = frappe.utils.time_diff_in_seconds(exit_time, str(row.from_time))
		hours = max(float(from_sec or 0) / 3600.0, 0.01)
		row.to_time = exit_time
		row.hours = round(hours, 4)
		row.expected_hours = round(hours, 4)
		row.description = completion_note
		row.completed = 1
		doc.save(ignore_permissions=True)
		doc.submit()
		frappe.db.commit()
		return {
			"name": doc.name,
			"docstatus": doc.docstatus,
			"exit_time": exit_time,
			"hours": round(hours, 4),
			"completion_note": completion_note,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error("submit_gate_timesheet", str(e))
		return {"error": str(e)}
