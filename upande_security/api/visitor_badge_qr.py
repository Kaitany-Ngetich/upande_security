# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Releases a visitor's Gate Badge when the visit is checked out.

(Numbering and QR codes now live on Gate Badge itself.)
"""

import frappe


def release_badge_on_checkout(doc, method=None):
	"""Releases the visitor's badge back to Available the moment an
	Appointment reaches Visitor Checked Out - wired via hooks.py doc_events
	on_update, so it fires no matter HOW the checkout happened.

	Why this can't live only in the mobile-facing check_out_visitor Server
	Script (where the release logic first shipped): a host confirming
	checkout directly in Desk goes through Frappe's own workflow engine
	(apply_workflow -> a real doc.save()), not through that script at all -
	"Appointment Gate Workflow Actions" (the Client Script driving that
	button) only ever touches custom_check_out_time/custom_reporting_status
	client-side, never the badge. Two genuinely separate checkout paths
	need one shared place that always runs, regardless of which UI
	triggered it - this hook is that place.

	Idempotent and safe to run on every single save, not just the one that
	flips the state: only acts when this exact appointment is still the
	badge's current_appointment (so it never fires again once already
	released, and never touches a badge that's since been reissued to a
	different visit).
	"""
	if doc.workflow_state != "Visitor Checked Out":
		return
	if not doc.custom_visitor_badge:
		return

	badge = frappe.db.get_value(
		"Gate Badge", doc.custom_visitor_badge, ["status", "current_appointment"], as_dict=True
	)
	if not badge or badge.current_appointment != doc.name:
		return

	frappe.db.set_value(
		"Gate Badge", doc.custom_visitor_badge, {"status": "Available", "current_appointment": None}
	)
