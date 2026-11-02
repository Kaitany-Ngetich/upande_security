# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Standard times of each shift type.

Security Ops Settings > Standard Shift Times holds them; picking a shift type
on a Rotation Plan or a Shift Assignment fills its times from there, so they
are no longer typed by hand (hand-typed plans had drifted - "Day" plans at
06:00-14:00, "Night" ones at 22:00-06:00). A shift type missing from the
table falls back to DEFAULT_SHIFT_TIMES, the times the farms run today.
"""

import frappe

DEFAULT_SHIFT_TIMES = {
	"Day": ("06:00:00", "18:00:00"),
	"Night": ("17:00:00", "06:30:00"),
	"First": ("06:00:00", "14:00:00"),
	"Second": ("14:00:00", "22:00:00"),
	"Third": ("22:00:00", "06:00:00"),
}


def standard_times(shift_type):
	"""(start_time, end_time) of a shift type, as "HH:MM:SS", or (None, None)."""
	if not shift_type:
		return None, None
	row = frappe.db.get_value(
		"Security Shift Time",
		{
			"parent": "Security Ops Settings",
			"parenttype": "Security Ops Settings",
			"parentfield": "standard_shift_times",
			"shift_type": shift_type,
		},
		["start_time", "end_time"],
		as_dict=True,
	)
	if row and row.start_time and row.end_time:
		return str(row.start_time), str(row.end_time)
	return DEFAULT_SHIFT_TIMES.get(shift_type, (None, None))


@frappe.whitelist()
def get_standard_shift_times(shift_type):
	"""For the forms: the times to fill in when a shift type is picked."""
	start, end = standard_times(shift_type)
	return {"shift_type": shift_type, "start_time": start, "end_time": end}
