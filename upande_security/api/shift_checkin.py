# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Ticks a shift's `checked_in` from the gate's biometric punches.

External guards punch into Security Checkin at the gate devices, but nothing
carried that punch onto their Security Guard Shift Assignment - `checked_in`
only ever moved when a guard tapped Check In in the mobile app. So the flag
read 0 for whole shifts of guards who had plainly clocked in.

WHICH SHIFT A PUNCH BELONGS TO
The punch's own time decides, never its arrival time: the devices sync late
(12 minutes typically, over two days at worst), and a punch that lands after
its shift has ended still belongs to that shift. A punch counts for a shift
from an hour before it starts until it ends - guards arrive early - and the
devices' IN/OUT key is ignored, because guards press either one (see
security_dashboard's note on biometric attendance).

When two shifts both cover the punch - a reliever working First then Second
back to back, where 13:30 sits in both windows - the one starting nearest the
punch takes it, so one arrival never ticks two shifts.

Only ever sets the flag, never clears it: a tick can also come from the app's
own check-in, and a later punch has no business undoing that.

Best-effort by design. This runs inside the device's own insert, and a
failure here must never cost the gate its punch.
"""

import datetime

import frappe
from frappe.utils import get_datetime

from upande_security.api.feature_flags import is_feature_enabled
from upande_security.upande_security.doctype.security_guard_shift_assignment.security_guard_shift_assignment import (
	combine_date_time,
)

#: How long before a shift starts a punch already counts for it.
EARLY = datetime.timedelta(minutes=60)


def _window(row):
	"""(start, end) of a shift, end rolled into the next day when the clock
	wraps past midnight - the reading derive_status uses."""
	start = combine_date_time(row.start_date, row.start_time)
	end = combine_date_time(row.end_date, row.end_time)
	if start and end and end <= start:
		end = end + datetime.timedelta(days=1)
	return start, end


def pick_shift(rows, punch_time):
	"""The shift `punch_time` belongs to, or None. Nearest start wins when
	more than one window covers it."""
	best = None
	for row in rows:
		start, end = _window(row)
		if not start or not end or not (start - EARLY <= punch_time <= end):
			continue
		gap = abs((punch_time - start).total_seconds())
		if best is None or gap < best[0]:
			best = (gap, row)
	return best[1] if best else None


def mark_shift_from_punch(doc, method=None):
	"""Security Checkin.after_insert."""
	if not is_feature_enabled("feature_biometric_shift_checkin"):
		return
	if not doc.security_guard or not doc.time:
		return
	try:
		punch_time = get_datetime(doc.time)
		# A night shift that started yesterday can still be running.
		rows = frappe.get_all(
			"Security Guard Shift Assignment",
			filters={
				"external_guard": doc.security_guard,
				"status": ["!=", "Cancelled"],
				"start_date": ["between", [punch_time.date() - datetime.timedelta(days=1), punch_time.date()]],
			},
			fields=["name", "start_date", "start_time", "end_date", "end_time", "checked_in"],
		)
		shift = pick_shift(rows, punch_time)
		if shift and not shift.checked_in:
			# set_value, not save(): validate() and its overlap check have
			# nothing to do with an attendance tick (same reason as
			# security_api.check_in_shift).
			frappe.db.set_value(
				"Security Guard Shift Assignment", shift.name, "checked_in", 1, update_modified=True
			)
	except Exception:
		frappe.log_error(
			"shift_checkin.mark_shift_from_punch " + str(doc.name), frappe.get_traceback()
		)
