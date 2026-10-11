# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Read-only lookup endpoints, moved out of Server Scripts into app code.

These four were API-type Server Scripts (`list_incident_categories`,
`search_employees`, `get_employee`, `search_customers`). They are the first
batch of a wider migration off `safe_exec`: the logic becomes versioned,
greppable, reviewable and testable, and the sandbox's restrictions (no
imports, no f-strings, bracket-only dict access, `frappe.utils.x()` only)
stop applying.

WHY THE OLD BARE URLS STILL WORK
--------------------------------
The gate app posts to short paths like `/api/method/get_employee`, which
Frappe normally resolves only through the Server Script map. `hooks.py`'s
`override_whitelisted_methods` aliases each bare name onto the function
below, and `frappe.handler.execute_cmd` consults that map BEFORE the Server
Script map and before `get_attr`:

        def execute_cmd(cmd, from_async=False):
                cmd = frappe.override_whitelisted_method(cmd)   # <- first
                server_script = get_server_script_map().get("_api", {}).get(cmd)

So every APK already in the field keeps working with no rebuild and no OTA,
and the alias wins over the Server Script record even while that record is
still present - which is deliberate: the records are left in place for now
so that deleting one alias line in hooks.py rolls an endpoint straight back
to its old implementation.

Taken from upande_scp, which migrated this way and left the reasoning in
its own hooks.py. It also left a warning worth repeating: SCP dropped a
batch of Server Scripts after an audit found "no in-repo caller", which was
true of the repository and false of the handset app, and every handset lost
its spray list. Aliases here are load-bearing for builds we cannot inspect.

THE RESPONSE CONTRACT IS NOT NEGOTIABLE
---------------------------------------
Every function here returns its payload (Frappe wraps a return value in
`message`, exactly as `frappe.response["message"] = ...` did) and signals
failure by RETURNING `{"error": "..."}` at HTTP 200. None of them raise.

That is not stylistic. The mobile client turns a returned `{"error": ...}`
into a thrown Error the screen catches and displays, but an HTTP 403 is
intercepted in `lib/api/client.ts` as a dead session - it calls
`forgetDevice()` and redirects to the login screen. A `frappe.throw` here
would therefore not show a guard an error message, it would log them out
mid-shift. Soft-fail, always.

Parameters are deliberately left unannotated. `frappe.whitelist` wraps each
function in `validate_argument_types`, which the safe_exec sandbox never
did; adding `: int` or `: str` would newly enforce coercion on values these
endpoints have always accepted as free-form strings.
"""

import frappe


@frappe.whitelist()
def list_incident_categories():
	"""Categories for the mobile incident-report form's picker.

	Sources Incident Category, NOT Incident Report's own
	`nature_of_incident` Select - the two have drifted apart and the Select
	is what a saved incident is actually validated against. Preserved as-is
	here: this is a straight port, not the place to fix that.
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
def search_employees(query=None):
	"""Type-ahead host search over Active employees.

	Raw SQL rather than get_all because the original matched on either the
	employee ID or the name with a single OR, which get_all's filter syntax
	cannot express without an or_filters split. Parameterised, as the
	sandbox house rules always required.
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
