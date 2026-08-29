# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt
"""Gate-level movement tracing.

Security Gate Config (child table on the Security Ops Settings single doc,
under `farm_gates`) records which physical gates each farm has. This module
is the one place that reads it, so a vehicle/visitor's entry and exit gate
can be captured and compared - a mismatch (entered through Gate A, left
through Gate B) is a real anomaly worth flagging, not just a data point.
"""

import frappe


@frappe.whitelist()
def get_farm_gates(farm):
	"""Active gates configured for a farm, main gate first. Used by the
	mobile app to populate the "which gate?" picker at gate entry/exit -
	for a single-gate farm this is a one-item list (auto-flagged as the
	main gate by Security Ops Settings' own validate()), so the picker can
	just as easily be skipped and defaulted client-side.

	A farm with ZERO rows in Security Ops Settings gets a synthetic single
	"Main Gate" entry rather than an empty list - most farms only have one
	physical gate, and a single gate has nothing to disambiguate anyway, so
	requiring someone to add a row per farm just to get a non-blank value
	recorded would be pure busywork with no security benefit. The moment a
	farm gets real rows configured (e.g. Kapkolia's actual 3 gates), those
	take over automatically - this fallback only fires for a farm nobody
	has configured yet.
	"""
	if not farm:
		return []
	settings = frappe.get_single("Security Ops Settings")
	gates = [
		{"gate_name": row.gate_name, "is_main_gate": bool(row.is_main_gate)}
		for row in (settings.farm_gates or [])
		if row.farm == farm and row.active
	]
	if not gates:
		return [{"gate_name": "Main Gate", "is_main_gate": True}]
	gates.sort(key=lambda g: (not g["is_main_gate"], g["gate_name"]))
	return gates


def compute_gate_mismatch(entry_gate, exit_gate):
	"""True only when both ends are known and genuinely differ - a blank
	gate (guard skipped the picker, or the site predates this feature) is
	never treated as a mismatch, since that would just be noise.

	Kept here as the one shared definition, even though the two consumers
	(Appointment for visitors/contractors, Timesheet for the Company
	Vehicle gate-tracking flow - NOT Tractor Daily Task's custom_gate_*
	fields, which were only ever a design-doc spec and were never actually
	wired up) each set their own custom_gate_mismatch inline via
	frappe.db.set_value from a sandboxed Server Script, which can't import
	this module. This function documents the rule those scripts duplicate.
	"""
	return bool(entry_gate and exit_gate and entry_gate != exit_gate)
