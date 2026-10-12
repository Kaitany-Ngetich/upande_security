# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time cleanup: delete the "Appointment Host WA Number" Server Script.

It was found to stop WhatsApp host alerts going out, so its port
(api/appointment_events.appointment_host_wa_number) is deliberately left
unwired in hooks.py. But the Server Script itself was still enabled on
sites that had it - fixture sync never deletes - so the behaviour kept
running there regardless. This removes it.

To bring the behaviour back, uncomment its hook line in hooks.py rather
than recreating the script.

Idempotent: only deletes it if it is still there.
"""

import frappe

SERVER_SCRIPT = "Appointment Host WA Number"


def execute():
	if frappe.db.exists("Server Script", SERVER_SCRIPT):
		frappe.delete_doc("Server Script", SERVER_SCRIPT, ignore_permissions=True, force=True)
		frappe.db.commit()
