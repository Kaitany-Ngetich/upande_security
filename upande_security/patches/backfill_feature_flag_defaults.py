# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time backfill: every feature_* Check field on Security Ops Settings
is meant to ship "on" by default (an instance opts OUT of a feature, it
never has to opt in) - each field's own DocField default is "1" for
exactly that reason. But Security Ops Settings is deliberately NOT
fixture-tracked (so a redeploy can never reset an admin's real choices
back to defaults - see the fixtures-revert gotcha this app has hit
before), which means nothing ever backfills that "1" into the actual
Single record when a brand-new flag field first reaches a site. A plain
`bench migrate`/reload-doc only defines the field; it never touches the
already-existing singleton's stored data, so every new flag lands there
as an unset/0 value - the opposite of "on by default" - until this runs.

Confirmed on this app's own local bench: after the first 13 feature flags
were added, `frappe.db.get_singles_dict("Security Ops Settings")` showed
every single one of them stored as "0", not "1" - meaning every
require_feature()-gated endpoint (SOS alerts, Gate Dispatch, Gate
Receiving, Supplier Badges) would have started throwing PermissionError
for every user the moment this shipped, despite nobody ever intending to
turn any of them off.

Idempotent and safe to re-run: only touches a field that's currently
falsy (0/None) - an admin who explicitly disabled a flag before this
patch happens to run again is never overridden, since Frappe patches only
ever execute once per site (tracked in Patch Log) - but the guard is here
regardless, since a plain "set them all to 1" would be wrong if this ever
had to be manually re-run for a newly-added flag in the future.
"""

import frappe

from upande_security.api.feature_flags import FEATURE_FIELDS


def execute():
	if not frappe.db.exists("DocType", "Security Ops Settings"):
		return

	# frappe.db.get_singles_dict() returns raw, uncast column values (a
	# Check field reads back as the string "0", never the int 0) - `not
	# "0"` is False in Python, since a non-empty string is truthy, so a
	# naive falsy-check against that dict silently never fires. get_value()
	# with an explicit fieldtype (via get_single_value) casts properly, so
	# check each field that way instead - only 14 fields, one-time patch,
	# the extra queries don't matter.
	for field in FEATURE_FIELDS:
		if not frappe.db.get_single_value("Security Ops Settings", field):
			frappe.db.set_single_value("Security Ops Settings", field, 1)

	frappe.db.commit()
