# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Keeps the Security Workspace's native shortcuts in sync with whatever
doctypes this app actually owns - dynamically, by querying
DocType.module="Upande Security" at migrate time, not a hardcoded list of
names maintained by hand.

Why an after_migrate hook and not a one-time patch: a patch only ever
runs once per site (tracked in Patch Log) - fine for a one-off cleanup,
wrong for something that needs to stay correct forever. Worse, Workspace
is itself fixture-tracked (hooks.py's fixtures list), and fixture import
happens *after* patches within the same `bench migrate` run - so a
one-time patch's changes here would just get silently overwritten the
moment fixtures re-import the old static snapshot. after_migrate hooks
run at the very end of migrate, after fixture sync, so this always gets
the last word and keeps working automatically as doctypes are added to
(or removed from) the app in the future, on every site this app deploys
to, without anyone touching a list by hand again.

Idempotent and additive only:
- Only ADDS a shortcut for a doctype that doesn't have one yet (matched by
  link_to) - never touches, reorders, or relabels an existing shortcut, so
  any manual customization made via the Workspace editor in Desk (a
  renamed label, a reordering, a recolor) survives future runs.
- Only removes a shortcut if its target doctype is no longer owned by
  this module at all (e.g. Appointment/Vehicle, which belong to CRM /
  Upande Kaitet respectively, not this app) - never removes a shortcut
  just because this function didn't itself create it.
- Child tables (istable=1) are skipped - they have no standalone list
  view to link to.
"""

import frappe

WORKSPACE_NAME = "Security"
OWNING_MODULE = "Upande Security"


def sync_shortcuts():
	if not frappe.db.exists("Workspace", WORKSPACE_NAME):
		return

	doc = frappe.get_doc("Workspace", WORKSPACE_NAME)

	owned_doctypes = frappe.get_all(
		"DocType",
		filters={"module": OWNING_MODULE, "istable": 0},
		pluck="name",
	)
	owned_set = set(owned_doctypes)

	existing_links = {row.link_to for row in doc.shortcuts if row.type == "DocType"}

	added = []
	for dt in owned_doctypes:
		if dt in existing_links:
			continue
		doc.append(
			"shortcuts",
			{
				"type": "DocType",
				"link_to": dt,
				"label": dt,
				"doc_view": "List",
			},
		)
		added.append(dt)

	removed = []
	kept_shortcuts = []
	for row in doc.shortcuts:
		if row.type == "DocType" and row.link_to not in owned_set:
			removed.append(row.link_to)
			continue
		kept_shortcuts.append(row.as_dict())

	if not added and not removed:
		return

	doc.shortcuts = []
	for row in kept_shortcuts:
		doc.append("shortcuts", row)

	doc.save(ignore_permissions=True)
	frappe.db.commit()

	logger = frappe.logger("upande_security", allow_site=True)
	summary = "upande_security sync_workspace: added={0} removed={1}".format(added, removed)
	logger.info(summary)
	print(summary)
