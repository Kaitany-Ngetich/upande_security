# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Fill Security Ops Settings > Standard Shift Times with the times the farms
run today, so picking a shift type fills its times. Rows already there are
kept; only missing shift types are added."""

import frappe

from upande_security.api.shift_times import DEFAULT_SHIFT_TIMES


def execute():
	frappe.reload_doc("upande_security", "doctype", "security_shift_time")
	frappe.reload_doc("upande_security", "doctype", "security_ops_settings")
	settings = frappe.get_single("Security Ops Settings")
	have = {row.shift_type for row in settings.get("standard_shift_times") or []}
	added = False
	for shift_type, (start, end) in DEFAULT_SHIFT_TIMES.items():
		if shift_type not in have:
			settings.append("standard_shift_times", {"shift_type": shift_type, "start_time": start, "end_time": end})
			added = True
	if added:
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
