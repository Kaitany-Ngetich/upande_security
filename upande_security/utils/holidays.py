# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Off-day lookup for External Guards.

Off days are a bespoke, guard-scoped mechanism: each External Guard may have
at most one "Security Guard Off Days" record (autoname field:external_guard),
whose `off_days` child table (Security Guard Off Day) holds specific dated
rows. This intentionally does NOT reuse core HR's shared Holiday List
mechanism - a guard's off days are configured per-guard and reused across
that guard's own Security Guard Shift Assignment / Rotation Plan records
only, not shared with any other guard.

Shared by anything that needs to skip a guard's off days when planning
ahead - today just Security Guard Rotation Plan's generate_preview(), but
kept here rather than inlined into that controller so a second call site
never has to duplicate the query.
"""

import frappe
from frappe.utils import getdate


def is_guard_off(external_guard, check_date):
	"""True if check_date is one of external_guard's configured off days.

	No "Security Guard Off Days" record for this guard yet (a common,
	valid state - nobody has configured off days for them) always reads
	as "not an off day", same as no dates configured at all.
	"""
	if not external_guard or not check_date:
		return False

	off_days_record = frappe.db.get_value("Security Guard Off Days", {"external_guard": external_guard}, "name")
	if not off_days_record:
		return False

	return bool(
		frappe.db.exists(
			"Security Guard Off Day",
			{
				"parent": off_days_record,
				"parenttype": "Security Guard Off Days",
				"parentfield": "off_days",
				"off_date": getdate(check_date),
			},
		)
	)
