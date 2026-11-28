# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SecurityOpsSettings(Document):
	def validate(self):
		if (
			self.missed_checkin_minutes
			and self.escalation_minutes
			and self.escalation_minutes < self.missed_checkin_minutes
		):
			frappe.throw(
				"SOS Escalation Threshold ({0} min) must be longer than the Missed Check-in"
				" Threshold ({1} min), otherwise every missed check-in escalates immediately.".format(
					self.escalation_minutes, self.missed_checkin_minutes
				)
			)
		self.validate_coverage_grid()
		self.fill_appointment_recipient_contacts()
		self.auto_mark_single_gate_farms_as_main()
		self.validate_report_subscriptions()
		self.validate_custom_words()
		self.validate_shift_times()

	def validate_shift_times(self):
		"""Standard Shift Times: one row per shift for every farm (Farms
		blank), and any farm picked at most once per shift - otherwise which
		times a farm gets would depend on row order."""
		from upande_security.api.shift_times import parse_farms

		blank, picked = set(), {}
		for row in self.standard_shift_times:
			farms = parse_farms(row.farms)
			if not farms:
				if row.shift_type in blank:
					frappe.throw(
						_("Standard Shift Times: the {0} shift has more than one row for every farm (Farms blank).").format(
							frappe.bold(row.shift_type)
						),
						title=_("Duplicate Shift"),
					)
				blank.add(row.shift_type)
				continue
			unknown = [f for f in farms if not frappe.db.exists("Farm", f)]
			if unknown:
				frappe.throw(
					_("Standard Shift Times row {0}: farm not found: {1}").format(row.idx, ", ".join(unknown)),
					title=_("Unknown Farm"),
				)
			for farm in farms:
				key = (row.shift_type, farm)
				if key in picked:
					frappe.throw(
						_("Standard Shift Times: {0} is picked for the {1} shift in rows {2} and {3}.").format(
							frappe.bold(farm), frappe.bold(row.shift_type), picked[key], row.idx
						),
						title=_("Farm Picked Twice"),
					)
				picked[key] = row.idx
			# Stored one per line, de-duplicated, so the list view reads cleanly.
			row.farms = "\n".join(dict.fromkeys(farms))

	def validate_custom_words(self):
		"""Use Custom Words on: all four words are needed."""
		if not self.use_custom_words:
			return
		for key in ("site_label", "site_label_plural", "area_label", "area_label_plural"):
			value = (self.get(key) or "").strip()
			if not value:
				frappe.throw(
					"Fill in '{0}' or turn Use Custom Words off.".format(self.meta.get_label(key)),
					frappe.MandatoryError,
				)
			self.set(key, value)

	def on_update(self):
		# Words Used changed: relabel the Farm / Block fields in Desk to match.
		from upande_security.api.terms import on_settings_update

		on_settings_update(self)

	def validate_report_subscriptions(self):
		"""Each security report row stays within its person's own access:
		Kaitet Ltd. people get Kaitet Ltd. farms, Karen Roses people Karen
		Roses farms, and so on for whatever companies a site has. A row
		left blank for someone limited to one company or farm is filled in
		with it; a row reaching beyond their access is refused."""
		from upande_security.api.security_report import covers, default_scope, doctype_problem, parse_doctypes

		for row in self.get("security_report_subscriptions") or []:
			# Day / Night halves are a daily report's; weekly and monthly
			# reports always cover whole days.
			if row.frequency != "Daily" or not row.covers:
				row.covers = "Full day"
			if row.covers == "Day and night" and not row.night_send_at:
				row.night_send_at = "06:00:00"
			if row.user and not row.email:
				row.email = frappe.db.get_value("User", row.user, "email")
			user = row.user or frappe.db.get_value("User", {"email": row.email, "enabled": 1}, "name")
			# Picked doctypes: one per line, each one this person may read.
			picked = parse_doctypes(row.doctypes)
			for dt in picked:
				problem = doctype_problem(dt, user)
				if problem:
					frappe.throw("Security Reports row {0}: {1}".format(row.idx, problem))
			row.doctypes = "\n".join(picked)
			if not user:
				continue
			if row.farm:
				row.company = frappe.db.get_value("Farm", row.farm, "company")
			if not row.farm and not row.company:
				row.farm, row.company = default_scope(user)
				if row.farm:
					row.company = frappe.db.get_value("Farm", row.farm, "company")
			if not covers(user, row.farm, row.company):
				frappe.throw(
					"Security Reports row {0}: {1} cannot see all of {2}. Pick their own company or farm.".format(
						row.idx, row.email or user, frappe.bold(row.farm or row.company or "every farm")
					)
				)

	def validate_coverage_grid(self):
		for label, value in (
			("Grid Cell Width", self.coverage_grid_cell_width_m),
			("Grid Cell Height", self.coverage_grid_cell_height_m),
			("Patrol Influence Radius", self.coverage_influence_radius_m),
		):
			if value and not 10 <= value <= 500:
				frappe.throw("{0} must be between 10 and 500 meters.".format(label))
		if self.coverage_boundary_tolerance_m and not 0 <= self.coverage_boundary_tolerance_m <= 500:
			frappe.throw("Boundary Tolerance must be between 0 and 500 meters.")
		if self.coverage_sweep_offset_m and not 1 <= self.coverage_sweep_offset_m <= 500:
			frappe.throw("Patrol Sweep Offset must be between 1 and 500 meters.")
		if (
			self.coverage_fresh_hours
			and self.coverage_stale_hours
			and self.coverage_stale_hours <= self.coverage_fresh_hours
		):
			frappe.throw(
				"Not Patrolled After ({0} h) must be longer than Fully Patrolled Within ({1} h).".format(
					self.coverage_stale_hours, self.coverage_fresh_hours
				)
			)

	def fill_appointment_recipient_contacts(self):
		"""Resolve each recipient's email/WhatsApp off their Employee record.
		Done here rather than in the child controller because Frappe never
		calls a child table's own validate() - the row would save with the
		contact columns blank even though delivery resolves them later."""
		from upande_security.upande_security.doctype.appointment_notification_recipient.appointment_notification_recipient import (
			employee_contact,
		)

		for row in self.appointment_notification_recipients or []:
			if row.employee:
				email, phone = employee_contact(row.employee)
				if not row.email:
					row.email = email
				if not row.whatsapp_no:
					row.whatsapp_no = phone
				# Defaults to the farm this person actually works at, which is
				# nearly always the one whose appointments they want. Still
				# editable, and still blank-means-every-farm if cleared.
				if not row.farm:
					row.farm = frappe.db.get_value("Employee", row.employee, "custom_farm")
			if not row.email and not row.whatsapp_no:
				frappe.throw(
					"Appointment notification recipient row {0}: no email or phone number "
					"on {1}'s Employee record - add one there, or type it in the row.".format(
						row.idx, row.employee or "this row"
					)
				)

	def auto_mark_single_gate_farms_as_main(self):
		"""A farm with exactly one active gate has nothing to disambiguate -
		its one gate IS the main gate. Rather than making every single-gate
		farm remember to tick "Main Gate" by hand, set it for them. Farms
		with 2+ active gates are left alone - that's a real choice someone
		has to make.
		"""
		by_farm = {}
		for row in self.farm_gates or []:
			if row.active:
				by_farm.setdefault(row.farm, []).append(row)
		for farm, rows in by_farm.items():
			if len(rows) == 1:
				rows[0].is_main_gate = 1
