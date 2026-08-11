# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

# A Cancelled shift never put anyone on a farm, so it can't explain a patrol.
MATCHABLE_SHIFT_STATUSES = ("Scheduled", "Active", "Ended")


class PatrolReport(Document):
	def on_update(self):
		self.sync_incident_report()

	def validate(self):
		self.force_submitted_on_file()
		self.stamp_filed_at()
		self.validate_incident_details()
		self.pull_window_from_gps_log()
		self.resolve_shift_assignment()
		self.pull_farm_and_personel_from_shift()
		self.count_gps_points()
		self.stamp_review()

	# ---------------------------------------------------------------- filing
	def force_submitted_on_file(self):
		"""A newly filed report always starts at Submitted.

		The review fields sit at permlevel 1, so Frappe already strips them from a
		guard's payload — this closes the remaining gap where a Security Head
		creating a report on someone's behalf could file it pre-reviewed.
		"""
		if self.is_new():
			self.status = "Submitted"

	def stamp_filed_at(self):
		"""Record when the guard actually filed, independent of the GPS window.

		A mid-patrol report is filed while the trail is still growing, so its
		filing time is a distinct fact from started_at/ended_at.
		"""
		if not self.filed_at:
			self.filed_at = now_datetime()

	def validate_incident_details(self):
		"""A Routine report must not carry incident fields, and vice versa."""
		if self.report_type == "Incident":
			if not self.severity:
				frappe.throw(
					_("Severity is required when a report is flagged as an Incident."),
					title=_("Incident Details Missing"),
				)
			return

		# Downgraded back to Routine — clear the incident-only fields so they
		# can't linger and mislead a supervisor.
		self.severity = None
		self.nature_of_incident = None

	# ------------------------------------------------------------------ GPS
	def pull_window_from_gps_log(self):
		"""Patrol window and guard identity come from the uploaded GPS trail.

		The trail is the only record of when the guard actually walked and who
		they were, so it is authoritative for these — not hand entry.
		"""
		if not self.patrol:
			return

		rows = frappe.db.sql(
			"""
			SELECT MIN(captured_at) AS first_fix,
			       MAX(captured_at) AS last_fix,
			       MAX(internal_guard) AS internal_guard,
			       MAX(external_guard) AS external_guard
			FROM `tabPatrol GPS Log`
			WHERE patrol = %s
			""",
			(self.patrol,),
			as_dict=True,
		)
		if not rows or not rows[0].first_fix:
			return

		row = rows[0]
		self.started_at = row.first_fix
		self.ended_at = row.last_fix
		self.internal_guard = row.internal_guard
		self.external_guard = row.external_guard

	# ---------------------------------------------------------------- Shift
	def resolve_shift_assignment(self):
		"""Find the Shift Planning entry that covers this patrol.

		Matched on the guard from the GPS trail plus an overlap with the patrol
		window. Left alone if a supervisor has already picked one by hand.
		"""
		if self.shift_assignment:
			return
		if not (self.started_at and self.ended_at):
			return

		if self.internal_guard:
			guard_field, guard_value = "internal_guard", self.internal_guard
		elif self.external_guard:
			guard_field, guard_value = "external_guard", self.external_guard
		else:
			return

		# Security Guard Shift Assignment splits date and time into separate
		# columns (mirroring HR's own Shift Assignment / Shift Type split), so
		# the overlap window is compared as combined datetimes rather than via
		# frappe.get_all's plain per-column filters.
		matches = frappe.db.sql(
			"""
			SELECT name
			FROM `tabSecurity Guard Shift Assignment`
			WHERE {guard_field} = %(guard_value)s
			  AND status IN %(statuses)s
			  AND TIMESTAMP(start_date, start_time) <= %(ended_at)s
			  AND TIMESTAMP(end_date, end_time) >= %(started_at)s
			ORDER BY start_date DESC, start_time DESC
			LIMIT 1
			""".format(guard_field=guard_field),
			{
				"guard_value": guard_value,
				"statuses": MATCHABLE_SHIFT_STATUSES,
				"ended_at": self.ended_at,
				"started_at": self.started_at,
			},
			as_dict=True,
		)
		if matches:
			self.shift_assignment = matches[0].name

	def pull_farm_and_personel_from_shift(self):
		"""Farm and personel are the shift's facts, not the patrol's.

		Shift Planning is what assigns a guard to a farm, so it owns both. If no
		shift matched they stay blank rather than being guessed from the trail —
		a blank field is honest, a wrong farm is not.
		"""
		if not self.shift_assignment:
			self.farm = None
			self.personel = None
			return

		shift = frappe.db.get_value(
			"Security Guard Shift Assignment",
			self.shift_assignment,
			["farm", "security_guard"],
			as_dict=True,
		)
		if not shift:
			return

		self.farm = shift.farm
		self.personel = shift.security_guard

	# ----------------------------------------------------------------- misc
	def count_gps_points(self):
		self.points_logged = (
			frappe.db.count("Patrol GPS Log", {"patrol": self.patrol}) if self.patrol else 0
		)

	def stamp_review(self):
		"""Record who reviewed it, the moment the status leaves Submitted."""
		if self.status == "Submitted":
			self.reviewed_by = None
			self.reviewed_on = None
			return

		previous = self.get_doc_before_save()
		if previous and previous.status == self.status and self.reviewed_by:
			return

		self.reviewed_by = frappe.session.user
		self.reviewed_on = now_datetime()

	# ------------------------------------------------------------- incidents
	def sync_incident_report(self):
		"""Raise the Incident Report automatically when a patrol is flagged.

		The guard fills one form. Everything Incident Report needs is either
		already on this document or derivable: Location is mirrored from the farm,
		the category and severity come from the guard, the narrative and photos
		carry over verbatim.

		Created once. Later edits here are deliberately NOT pushed onward — the
		incident takes on a life of its own once a supervisor starts working it,
		and silently overwriting their notes would be worse than the duplication.
		"""
		if self.report_type != "Incident" or self.incident_report:
			return

		lat, lng = _last_fix_coords(self.patrol)
		guard = self.internal_guard or self.external_guard or ""
		preamble = _("Raised from patrol {0}{1}.").format(
			self.patrol or "-", _(" by {0}").format(guard) if guard else ""
		)

		incident = frappe.new_doc("Incident Report")
		incident.incident_datetime = self.filed_at or self.ended_at or now_datetime()
		incident.location = _location_for_farm(self.farm, lat, lng)
		incident.nature_of_incident = self.nature_of_incident
		incident.severity = self.severity
		incident.status = "Open"
		incident.reported_by = self.owner
		incident.description = f"{preamble}\n\n{self.observations or ''}".strip()
		for i in range(1, 5):
			setattr(incident, f"attachment_{i}", self.get(f"attachment_{i}"))
		incident.flags.ignore_permissions = True
		incident.insert(ignore_permissions=True)

		# db_set, not save() — we are already inside this document's save cycle.
		self.db_set("incident_report", incident.name, update_modified=False)

		frappe.msgprint(
			_("Incident Report {0} raised from this patrol.").format(
				frappe.bold(incident.name)
			),
			indicator="orange",
			alert=True,
		)


def _location_for_farm(farm, latitude=None, longitude=None):
	"""Get or create the Location that stands for a farm.

	Incident Report requires a Location, but patrols only know their Farm. The
	two masters are unrelated on this site, so mirror the farm as a Location
	(autoname is field:location_name, so the name IS the farm name) and stamp it
	with the patrol's coordinates when we have them.
	"""
	name = farm or _("Unspecified Farm")
	if frappe.db.exists("Location", name):
		return name

	loc = frappe.new_doc("Location")
	loc.location_name = name
	if latitude is not None:
		loc.latitude = latitude
	if longitude is not None:
		loc.longitude = longitude
	loc.flags.ignore_permissions = True
	loc.insert(ignore_permissions=True)
	return loc.name


def _last_fix_coords(patrol):
	"""Latitude/longitude of the patrol's most recent GPS point, if any."""
	if not patrol:
		return None, None
	row = frappe.db.sql(
		"""
		SELECT latitude, longitude FROM `tabPatrol GPS Log`
		WHERE patrol = %s AND latitude != '' AND longitude != ''
		ORDER BY captured_at DESC LIMIT 1
		""",
		(patrol,),
		as_dict=True,
	)
	if not row:
		return None, None
	try:
		return float(row[0].latitude), float(row[0].longitude)
	except (TypeError, ValueError):
		return None, None


@frappe.whitelist()
def link_incident_report(patrol_report, incident_report):
	"""Record the Incident Report a supervisor created from this patrol report."""
	doc = frappe.get_doc("Patrol Report", patrol_report)
	doc.check_permission("write")

	if not frappe.db.exists("Incident Report", incident_report):
		frappe.throw(_("Incident Report {0} not found.").format(incident_report))

	doc.db_set("incident_report", incident_report, update_modified=True)
	return {"success": True, "incident_report": incident_report}
