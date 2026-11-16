# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Standard times of each shift type.

Security Ops Settings > Standard Shift Times holds them; picking a shift type
on a Rotation Plan or a Shift Assignment fills its times from there, so they
are no longer typed by hand (hand-typed plans had drifted - "Day" plans at
06:00-14:00, "Night" ones at 22:00-06:00). A shift type missing from the
table falls back to DEFAULT_SHIFT_TIMES, the times the farms run today.

FARM-SPECIFIC TIMES
Some farms run other hours (e.g. First 06:00-13:00 for the outsourced
guards). A row with Farms picked applies to those farms only; a row with
Farms blank applies to every other farm. So the table can hold:

	First  06:00-14:00   (blank - every farm)
	First  06:00-13:00   Kapkolia, Chepsito
	Second 13:00-22:00   Kapkolia, Chepsito

Given a farm, its own row for the shift wins, then the blank row, then the
default. Security Ops Settings refuses a farm picked twice for one shift.
"""

import frappe

DEFAULT_SHIFT_TIMES = {
	"Day": ("06:00:00", "18:00:00"),
	"Night": ("17:00:00", "06:30:00"),
	"First": ("06:00:00", "14:00:00"),
	"Second": ("14:00:00", "22:00:00"),
	"Third": ("22:00:00", "06:00:00"),
}


def parse_farms(value):
	"""The farm names in a row's Farms box (one per line; commas tolerated)."""
	return [f.strip() for f in (value or "").replace(",", "\n").split("\n") if f.strip()]


def _rows():
	"""The Standard Shift Times rows, read fresh (a handful of rows)."""
	return frappe.get_all(
		"Security Shift Time",
		filters={
			"parent": "Security Ops Settings",
			"parenttype": "Security Ops Settings",
			"parentfield": "standard_shift_times",
		},
		fields=["shift_type", "start_time", "end_time", "farms"],
		order_by="idx asc",
	)


def _pair(row):
	if row and row.start_time and row.end_time:
		return str(row.start_time), str(row.end_time)
	return None, None


def farm_times(shift_type, farm, rows=None):
	"""(start_time, end_time) from the row that picks this farm for this shift,
	or (None, None) when the farm has no row of its own."""
	if not shift_type or not farm:
		return None, None
	for row in rows if rows is not None else _rows():
		if row.shift_type == shift_type and farm in parse_farms(row.farms):
			return _pair(row)
	return None, None


def standard_times(shift_type, farm=None):
	"""(start_time, end_time) of a shift type, as "HH:MM:SS", or (None, None).
	With a farm, that farm's own row comes first."""
	if not shift_type:
		return None, None
	rows = _rows()
	start, end = farm_times(shift_type, farm, rows)
	if start and end:
		return start, end
	for row in rows:
		if row.shift_type == shift_type and not parse_farms(row.farms):
			start, end = _pair(row)
			if start and end:
				return start, end
	return DEFAULT_SHIFT_TIMES.get(shift_type, (None, None))


@frappe.whitelist()
def get_standard_shift_times(shift_type, farm=None):
	"""For the forms: the times to fill in when a shift type (or farm) is picked."""
	start, end = standard_times(shift_type, farm)
	return {"shift_type": shift_type, "farm": farm, "start_time": start, "end_time": end}


def all_farm_times():
	"""{farm: {shift_type: (start, end)}} for every farm with rows of its own,
	so a page can show the right times as farms are picked."""
	out = {}
	for row in _rows():
		start, end = _pair(row)
		if not (start and end):
			continue
		for farm in parse_farms(row.farms):
			out.setdefault(farm, {})[row.shift_type] = (start, end)
	return out
