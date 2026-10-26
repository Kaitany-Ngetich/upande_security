# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Fixtures for doctypes this app does not require.

Anything listed in hooks.py `fixtures` is imported unconditionally on install
and on every migrate, so a fixture for another app's doctype makes that app
a hard requirement: on a site without it the import fails on the missing
table and the install or migrate stops there. These live in
optional_fixtures/ instead and are imported only where their doctype exists.
A site that installs the other app later gets them on its next migrate.

To refresh one after editing the record on a site that has it, export it
there (Desk > the record > Menu > Export, or `bench export-fixtures` with
the entry temporarily back in hooks.py) and replace the file here.
"""

import os

import frappe
from frappe.core.doctype.data_import.data_import import import_doc

#: doctype -> file in optional_fixtures/. frappe_whatsapp's WhatsApp
#: Notification: the "visitor arrived" host alert over WhatsApp.
OPTIONAL_FIXTURES = {
	"WhatsApp Notification": "whatsapp_notification.json",
}


def sync():
	"""after_install / after_migrate: import each optional fixture whose
	doctype this site has. Never raises - an optional fixture must not stop
	an install or a migrate."""
	folder = frappe.get_app_path("upande_security", "optional_fixtures")
	for doctype, file_name in OPTIONAL_FIXTURES.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		try:
			frappe.flags.in_fixtures = True
			import_doc(os.path.join(folder, file_name))
		except Exception:
			frappe.log_error("Optional fixture " + file_name, frappe.get_traceback())
		finally:
			frappe.flags.in_fixtures = False
