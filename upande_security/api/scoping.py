# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""before_insert doc_events that stamp Farm onto doctypes which otherwise
carry no link back to a company/farm — Patrol GPS Log (raw guard telemetry)
and a standalone (non-patrol-raised) Incident Report.

Only fills the field when it's still empty, so Patrol Report's own
auto-raise flow (which already knows the patrol's actual farm — see
sync_incident_report in patrol_report.py) is never overwritten by a guess
based on whoever happened to be logged in.

This farm value is what makes the Security Head DocPerm row on each of
these doctypes (if_owner=0, relying on the standard Frappe Link + User
Permission engine) actually scope to something, instead of being silently
unrestricted.
"""

import frappe

from upande_security.api.identity import resolve_company_farm


def stamp_patrol_gps_log_farm(doc, method=None):
	if doc.get("farm"):
		return
	_, farm = resolve_company_farm(frappe.session.user)
	if farm:
		doc.farm = farm


def stamp_incident_report_farm(doc, method=None):
	if doc.get("farm"):
		return
	_, farm = resolve_company_farm(frappe.session.user)
	if farm:
		doc.farm = farm
