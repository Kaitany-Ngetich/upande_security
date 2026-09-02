# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Inline off-day management for an External Guard, called from the
Rotation & Off-Days tab on Security Guard Shift Assignment.

Off days are a bespoke, guard-scoped child table (Security Guard Off
Day) hung off a single "Security Guard Off Days" record per guard
(autoname field:external_guard) - see upande_security.utils.holidays for
the read side this feeds (Security Guard Rotation Plan.generate_preview).
This module is the write side: add/remove a single dated row without the
Security Head ever leaving the Shift Assignment form to visit a separate
doctype.

Both entry points are idempotent-ish by design: adding a date that's
already present does not create a duplicate row, and removing a date
that isn't present is a no-op rather than an error - a guard's off-day
list is small and hand-edited, and a double-click on "+ Add" or "x"
should never blow up the form.
"""

import frappe
from frappe import _
from frappe.utils import getdate


def _check_permission(ptype):
	if not frappe.has_permission("Security Guard Off Days", ptype):
		frappe.throw(
			_("You do not have permission to manage guard off days."),
			frappe.PermissionError,
		)


def _get_or_create_off_days_doc(external_guard, for_write=False):
	"""Fetch this guard's Security Guard Off Days record, creating an
	empty one on first use when for_write is set. Returns None when the
	record doesn't exist and for_write is False - "no off days configured
	yet" is a valid, common state callers must handle, not an error."""
	if not frappe.db.exists("Security Guard", external_guard):
		frappe.throw(_("{0} is not a valid Security Guard record.").format(external_guard))

	name = frappe.db.get_value("Security Guard Off Days", {"external_guard": external_guard}, "name")
	if name:
		return frappe.get_doc("Security Guard Off Days", name)

	if not for_write:
		return None

	doc = frappe.new_doc("Security Guard Off Days")
	doc.external_guard = external_guard
	doc.insert()
	return doc


@frappe.whitelist()
def add_guard_off_day(external_guard, off_date, remarks=None):
	"""Append off_date to external_guard's off-days list, creating the
	guard's Security Guard Off Days record on first use. A date already
	present is left as-is (remarks is NOT overwritten on a repeat call -
	the first entry wins) rather than adding a duplicate row.

	Returns {"name": <Security Guard Off Days record name>, "off_days":
	[{"off_date": "YYYY-MM-DD", "remarks": <str or None>}, ...]} sorted by
	off_date ascending.
	"""
	_check_permission("write")

	off_date = getdate(off_date)
	doc = _get_or_create_off_days_doc(external_guard, for_write=True)

	already_present = any(getdate(row.off_date) == off_date for row in doc.off_days)
	if not already_present:
		doc.append("off_days", {"off_date": off_date, "remarks": remarks})
		doc.save()

	return _off_days_response(doc)


@frappe.whitelist()
def remove_guard_off_day(external_guard, off_date):
	"""Remove off_date from external_guard's off-days list. A guard with
	no Security Guard Off Days record yet, or a date not present in it,
	is a no-op - not an error.

	Returns {"name": <Security Guard Off Days record name or None>,
	"off_days": [{"off_date": "YYYY-MM-DD", "remarks": <str or None>}, ...]}
	sorted by off_date ascending.
	"""
	_check_permission("write")

	off_date = getdate(off_date)
	doc = _get_or_create_off_days_doc(external_guard, for_write=False)
	if not doc:
		return {"name": None, "off_days": []}

	remaining = [row for row in doc.off_days if getdate(row.off_date) != off_date]
	if len(remaining) != len(doc.off_days):
		doc.set("off_days", [])
		for row in remaining:
			doc.append("off_days", {"off_date": row.off_date, "remarks": row.remarks})
		doc.save()

	return _off_days_response(doc)


def _off_days_response(doc):
	rows = sorted(doc.off_days, key=lambda row: getdate(row.off_date))
	return {
		"name": doc.name,
		"off_days": [{"off_date": str(getdate(row.off_date)), "remarks": row.remarks} for row in rows],
	}
