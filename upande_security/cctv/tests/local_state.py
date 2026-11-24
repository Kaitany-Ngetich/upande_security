"""Keep the developer's local CCTV set-up across test runs.

The checks switch CCTV on, load and clear the demo, and used to leave the
module OFF afterwards - wiping a demo someone was looking at. snapshot() at
the start and restore() at the end put back exactly what was there: the
switches, the Ops flag, and the demo (reloaded if it had been loaded).
"""

import frappe

from upande_security.cctv import settings

FARM = "Kapkolia"


def snapshot():
	return {
		"switches": {k: frappe.db.get_single_value("CCTV Settings", k) or 0 for k in settings.SWITCHES},
		"ops": frappe.db.get_single_value("Security Ops Settings", "feature_cctv") or 0,
		"demo": bool(frappe.db.get_value("CCTV Camera", {"camera_name": ["like", "DEMO %"]})),
	}


def restore(snap):
	for k, v in snap["switches"].items():
		frappe.db.set_single_value("CCTV Settings", k, v)
	frappe.db.set_single_value("Security Ops Settings", "feature_cctv", snap["ops"])
	frappe.db.commit()
	settings.clear()
	if snap["demo"] and not frappe.db.get_value("CCTV Camera", {"camera_name": ["like", "DEMO %"]}):
		try:
			from upande_security.cctv import admin

			admin.load_demo(FARM)
			frappe.db.commit()
			print("Demo reloaded (it was loaded before the test).")
		except Exception as e:
			frappe.db.rollback()
			print("Could not reload the demo:", e)
	frappe.clear_cache()
