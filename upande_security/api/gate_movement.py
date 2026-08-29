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
	"""
	if not farm:
		return []
	settings = frappe.get_single("Security Ops Settings")
	gates = [
		{"gate_name": row.gate_name, "is_main_gate": bool(row.is_main_gate)}
		for row in (settings.farm_gates or [])
		if row.farm == farm and row.active
	]
	gates.sort(key=lambda g: (not g["is_main_gate"], g["gate_name"]))
	return gates


def compute_gate_mismatch(entry_gate, exit_gate):
	"""True only when both ends are known and genuinely differ - a blank
	gate (guard skipped the picker, or the site predates this feature) is
	never treated as a mismatch, since that would just be noise."""
	return bool(entry_gate and exit_gate and entry_gate != exit_gate)
