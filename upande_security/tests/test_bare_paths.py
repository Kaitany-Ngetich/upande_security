# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Every short `/api/method/<name>` path the gate app posts to must resolve.

The gate app addresses its endpoints by bare name, not by dotted path. Frappe
resolves a bare name in exactly two ways - `override_whitelisted_methods`
(hooks.py) or the API-type Server Script map - so an endpoint that loses both
is a 404 on every handset already installed at a gate, with no warning from
this repository.

That failure is invisible from inside the codebase, which is why it is pinned
here. upande_scp dropped a batch of Server Scripts after an audit reported "no
in-repo caller" - true of its repository, false of the handset app, where the
callers actually lived - and every handset lost its spray list. This test makes
the same mistake fail CI instead of a farm.

The list below is every bare name `lib/services/api.ts` calls. Keep it in step
with that file: adding an endpoint there means adding it here, and removing one
from the list is a deliberate statement that no build in the field still calls
it. A build can outlive several releases, so that statement needs evidence -
the mobile source alone is not enough.
"""

import unittest

import frappe

from upande_security import hooks


#: Bare paths the gate app posts to. Resolution may come from either an alias
#: in `override_whitelisted_methods` or a Server Script - this test does not
#: care which, only that the path reaches something.
GATE_APP_BARE_PATHS = (
	"approved_appointments",
	"approve_staff_sticker_request",
	"book_customer_appointment",
	"check_in_shift",
	"check_in_visitor",
	"check_out_visitor",
	"contractor_gate_checkin",
	"contractor_gate_checkout",
	"create_contractor_notify",
	"create_incident",
	"create_staff_attendance",
	"create_walk_in",
	"create_walk_in_notify",
	"daily_summary",
	"file_patrol_report",
	"gate_activity",
	"gate_temp_exit",
	"get_appointment",
	"getContractorContract",
	"get_employee",
	"get_security_head_contact",
	"get_security_ops_settings",
	"get_session_info",
	"get_today_attendance",
	"get_visitor_history",
	"issue_visitor_badge",
	"list_checked_in_staff",
	"list_incident_categories",
	"list_incidents",
	"list_sticker_requests",
	"list_supplier_badges",
	"list_today_staff_attendance",
	"my_assets_at_farm",
	"my_current_shift",
	"my_incidents",
	"notify_host",
	"pending_approvals",
	"reject_staff_sticker_request",
	"report_asset_missing",
	"scan_asset",
	"search_customers",
	"search_employees",
	"search_staff",
	"search_staff_vehicle_sticker",
	"search_visitor_appointment",
	"security_report",
	"staff_gate_checkout",
	"submit_patrol_points",
	"submit_staff_attendance",
	"update_incident",
	"update_security_ops_settings",
	"update_shift_assignment",
	"update_supplier_badge",
)

#: Called by `api.ts` (getContractorPersonnelHistory) but implemented nowhere -
#: not in this repo's Server Script fixture, and not on kaitetv16 either. It
#: 404s today and did so before this migration; it is excluded so this test
#: reports real regressions rather than a known pre-existing gap. Implement it
#: or drop the client call, then delete this.
KNOWN_UNIMPLEMENTED = ("get_contractor_personnel_history",)


def _resolves(cmd):
	"""True when `/api/method/<cmd>` would reach something, by Frappe's own
	rules - the same two lookups `frappe.handler.execute_cmd` performs, in
	the same order."""
	from frappe.core.doctype.server_script.server_script_utils import (
		get_server_script_map,
	)
	from frappe.handler import get_attr

	resolved = frappe.override_whitelisted_method(cmd)
	if get_server_script_map().get("_api", {}).get(resolved):
		return True
	try:
		get_attr(resolved)
		return True
	except Exception:
		return False


class TestGateAppBarePaths(unittest.TestCase):
	def test_every_bare_path_the_app_calls_resolves(self):
		unreachable = [n for n in GATE_APP_BARE_PATHS if not _resolves(n)]
		self.assertEqual(
			unreachable,
			[],
			"these bare paths 404 for every handset in the field: " + str(unreachable),
		)

	def test_every_alias_target_is_importable(self):
		broken = []
		for bare, dotted in hooks.override_whitelisted_methods.items():
			try:
				frappe.get_attr(dotted)
			except Exception as e:
				broken.append(bare + " -> " + dotted + ": " + str(e))
		self.assertEqual(broken, [], "aliases pointing at nothing: " + str(broken))

	def test_every_alias_target_is_whitelisted(self):
		# An alias onto a function without @frappe.whitelist() is a 403 rather
		# than a 404 - the same outage with a different status code, and a 403
		# is worse: lib/api/client.ts treats it as a dead session, calls
		# forgetDevice() and redirects the guard to the login screen.
		unwhitelisted = []
		for bare, dotted in hooks.override_whitelisted_methods.items():
			try:
				fn = frappe.get_attr(dotted)
			except Exception:
				continue
			if fn not in frappe.whitelisted:
				unwhitelisted.append(bare + " -> " + dotted)
		self.assertEqual(
			unwhitelisted,
			[],
			"aliases onto non-whitelisted functions (403, logs the guard out): "
			+ str(unwhitelisted),
		)

	def test_aliased_names_are_paths_the_app_actually_calls(self):
		# Guards against a typo in hooks.py silently aliasing a name nothing
		# posts to, which would look fine while the real endpoint still runs
		# the old Server Script.
		known = set(GATE_APP_BARE_PATHS) | set(KNOWN_UNIMPLEMENTED)
		stray = sorted(set(hooks.override_whitelisted_methods) - known)
		self.assertEqual(stray, [], "aliased but never called by the app: " + str(stray))
