# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time cleanup: delete the Server and Client Scripts this app replaced.

Every Upande Security script now lives in app code, and the Server/Client
Script fixtures are gone. But fixture sync never deletes, so a site that had
the records keeps them, and they are not harmless:

- API Server Scripts whose bare path is aliased in
  override_whitelisted_methods are dead: execute_cmd applies the alias before
  it looks at the Server Script map, so they never run. Deleted.
- DocType Event / Permission Query Server Scripts still run, on top of the
  doc_events / permission_query_conditions hooks that replaced them, so their
  logic runs twice. The ported ones are deleted, by name.
- Client Scripts load alongside the app's JS files, so buttons appear twice
  and handlers fire twice. The nine moved into the app in 43b0ada are
  deleted, by name.

Deliberately NOT deleted, and anything else this patch does not recognise:

- An API script whose bare path has no alias - it is still the only thing
  answering that path, and deleting it would 404 every handset calling it.
  "Dead" is decided by Frappe's own resolution, not by a list, so a site with
  extra scripts this repo never saw keeps them.

"Appointment Host WA Number" has its own patch
(delete_appointment_host_wa_number_script).

Idempotent: only deletes whatever is still there.
"""

import frappe

MODULE = "Upande Security"

# Non-API Server Scripts whose logic now runs from hooks.py.
PORTED_SERVER_SCRIPTS = (
	"Clear Appointment Party",  # doc_events Appointment before_save
	"Clear Appointment Party (Before Insert)",  # doc_events Appointment before_insert
	"Clear Stale Event Participant",  # doc_events Appointment after_save
	"Staff Vehicle Sticker Auto Sync Status",  # doc_events Staff Vehicle Sticker validate
	"Host Sees Own Appointments",  # permission_query_conditions Appointment
	# Not ported - retired. Both only ever wrote custom_secretary_wa /
	# custom_secretary_email, which remove_retired_appointment_contact_fields
	# deleted, so they have done nothing since.
	"Appointment Secretary WA Number",
	"Company Receptionist WA Number",
)

# API Server Scripts whose api_method is a dotted path, so they shadowed the
# real function instead of being shadowed by an alias. Deleting them hands
# the call back to api/gate_receiving.py. The search bridge accepted the
# retired permanent "Active" badges; move_supplier_badges_to_pool_model
# moves those badges onto the pool model the Python expects.
BRIDGE_SERVER_SCRIPTS = (
	"TEMP BRIDGE - Search Receiving By Supplier Badge",
	"TEMP BRIDGE - Verify Receiving At Gate Bulk",
)

# Client Scripts moved into the app's JS in 43b0ada.
PORTED_CLIENT_SCRIPTS = (
	"Appointment Confirm Receipt",  # public/js/appointment.js
	"Appointment Gate Workflow Actions",  # public/js/appointment.js
	"Clear Appointment Party Defaults",  # public/js/appointment.js
	"Delivery Note Security Check Tab",  # public/js/delivery_note.js
	"Staff Vehicle Sticker Request - Gate Picker",  # public/js/staff_vehicle_sticker_request.js
	"Staff Vehicle Sticker Request Approve Reject",  # public/js/staff_vehicle_sticker_request.js
	"Incident Report - Resolution Auto-set",  # doctype/incident_report/incident_report.js
	"Incident Report - Resolve Button",  # doctype/incident_report/incident_report.js
	"Patrol Report - Review Actions",  # doctype/patrol_report/patrol_report.js
)


def _is_aliased(api_method):
	"""True when execute_cmd would never reach a Server Script for this path."""
	return bool(api_method) and frappe.override_whitelisted_method(api_method) != api_method


def execute():
	for script in frappe.get_all(
		"Server Script",
		filters={"module": MODULE, "script_type": "API"},
		fields=["name", "api_method"],
	):
		if _is_aliased(script.api_method):
			frappe.delete_doc("Server Script", script.name, ignore_permissions=True, force=True)

	for name in PORTED_SERVER_SCRIPTS + BRIDGE_SERVER_SCRIPTS:
		if frappe.db.exists("Server Script", name):
			frappe.delete_doc("Server Script", name, ignore_permissions=True, force=True)

	for name in PORTED_CLIENT_SCRIPTS:
		if frappe.db.exists("Client Script", name):
			frappe.delete_doc("Client Script", name, ignore_permissions=True, force=True)

	frappe.db.commit()
