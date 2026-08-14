# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""One-time cleanup: Appointment.custom_taxi_driver_name and
custom_taxi_driver_phone were an earlier design for the Taxi transport mode
(capture the driver's own details) that got explicitly scoped back down to
"numberplate only" - the code that ever read/wrote them (in Check In
Visitor / Create Walk In Server Scripts) has already been removed, and
neither field was ever added to this app's fixture allowlist, so they were
never really part of the shipped design - just two leftover columns on
whichever site happened to have them. This patch deletes both, everywhere
this app deploys.

custom_taxi_driver_check_out_time (a real, still-used field - tracks when
the taxi/driver itself departs, independent of the visitor's own
check-out) is untouched here; only its fixture insert_after anchor was
repointed away from custom_taxi_driver_phone in the same change.

Idempotent: only deletes whichever of the two is still there.
"""

import frappe


def execute():
	for name in ("Appointment-custom_taxi_driver_name", "Appointment-custom_taxi_driver_phone"):
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)

	frappe.db.commit()

	logger = frappe.logger("upande_security", allow_site=True)
	logger.info("upande_security remove_dead_taxi_driver_fields: done")
	print("upande_security remove_dead_taxi_driver_fields: done")
