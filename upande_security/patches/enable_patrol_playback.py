# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Switch Patrol Playback on, with On-Duty positions and a 7-day window, when
the fields first arrive. A field added to an existing Single gets no stored
value, so its default would never apply - and the Desk form would show the
switch off, turning Playback off the first time anyone saved the settings.
Leaves any value already set alone."""

import frappe

SETTINGS = "Security Ops Settings"


def execute():
	for field, value in (
		("feature_patrol_playback", 1),
		("playback_include_on_duty", 1),
		("playback_max_window_days", 7),
	):
		if not frappe.db.exists("Singles", {"doctype": SETTINGS, "field": field}):
			frappe.db.set_single_value(SETTINGS, field, value)
