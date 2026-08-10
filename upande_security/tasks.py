# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Scheduled maintenance for Upande Security."""

import datetime
import json

import frappe

from upande_security.upande_security.doctype.security_guard_shift_assignment.security_guard_shift_assignment import (
	derive_status,
)


def refresh_shift_statuses():
	"""Roll Security Guard Shift Assignment statuses forward with the clock.

	Saving a shift derives its status, but a shift that simply *elapses* is never
	saved again — so without this an Active shift would read Active forever.
	Runs hourly.

	Writes go through frappe.db.set_value rather than doc.save() on purpose: the
	document's validate() runs an overlap check that can legitimately throw on
	historical data, and one bad row must not stop the whole sweep.
	"""
	rows = frappe.get_all(
		"Security Guard Shift Assignment",
		filters={"status": ["!=", "Cancelled"]},
		fields=["name", "start_date", "end_date", "status"],
		limit_page_length=0,
	)

	changed = 0
	for row in rows:
		derived = derive_status(row.start_date, row.end_date, row.status)
		if not derived or derived == row.status:
			continue
		frappe.db.set_value(
			"Security Guard Shift Assignment",
			row.name,
			"status",
			derived,
			update_modified=False,
		)
		changed += 1

	if changed:
		frappe.db.commit()

	return {"checked": len(rows), "updated": changed}


def sync_shifts_from_hr_roster():
	"""Create today's Security Guard Shift Assignment for every guard HR's
	own roster (Shift Assignment) says is on duty today, so Security never
	has to re-plan what HR already scheduled — and, just as importantly,
	never rosters someone HR has NOT scheduled. There's no separate Leave
	doctype in real use on this site, so an "off day" per HR is simply a
	day with no Active Shift Assignment covering it — nothing to create.

	HR's roster has no farm/location at all, so a synced record's farm is
	only ever a starting guess: whatever farm this guard was posted to most
	recently. It's left blank if there's no prior posting to guess from —
	visible as a gap for a Security Head to fill in, not a wrong guess.

	Only ever creates — never touches an existing record (synced or made
	by hand), so a Security Head's own edits (farm, block, a Cancelled
	override for a guard who called in sick despite HR still showing them
	rostered) are never fought or overwritten on the next run.

	Runs daily.
	"""
	today = frappe.utils.today()

	rostered = frappe.db.sql(
		"""
		SELECT sa.name AS hr_shift_assignment, sa.employee, sa.shift_type,
		       st.start_time, st.end_time
		FROM `tabShift Assignment` sa
		JOIN `tabEmployee` emp ON emp.name = sa.employee
		JOIN `tabShift Type` st ON st.name = sa.shift_type
		WHERE sa.docstatus = 1
		  AND sa.status = 'Active'
		  AND emp.designation = 'Security Guard'
		  AND sa.start_date <= %(today)s
		  AND (sa.end_date IS NULL OR sa.end_date >= %(today)s)
		""",
		{"today": today},
		as_dict=True,
	)

	created = 0
	already_existed = 0
	for row in rostered:
		start_dt = frappe.utils.get_datetime(today) + row.start_time
		end_dt = frappe.utils.get_datetime(today) + row.end_time
		if row.end_time <= row.start_time:
			# Overnight shift (e.g. 18:00 -> 06:00) — end falls the next
			# calendar day.
			end_dt = end_dt + datetime.timedelta(days=1)

		# Any existing shift overlapping this window counts as "already
		# covered" — not just an exact start_date match. Cancelled is
		# included on purpose: if a Security Head deliberately cancelled a
		# guard's synced shift for this specific day (called in sick, say),
		# a re-run of this sync must never resurrect it. It only stops that
		# one occurrence — a later day's independently-computed window is
		# untouched, so the guard is still picked up normally next time
		# HR's roster covers them.
		exists = frappe.db.exists(
			"Security Guard Shift Assignment",
			{
				"internal_guard": row.employee,
				"status": ["in", ("Scheduled", "Active", "Ended", "Cancelled")],
				"start_date": ["<=", end_dt],
				"end_date": [">=", start_dt],
			},
		)
		if exists:
			already_existed += 1
			continue

		last_farm = frappe.db.get_value(
			"Security Guard Shift Assignment",
			{"internal_guard": row.employee},
			"farm",
			order_by="start_date desc",
		)

		shift_label = "Night" if "night" in (row.shift_type or "").lower() else "Day"

		shift = frappe.new_doc("Security Guard Shift Assignment")
		shift.security_guard = "Internal Guard"
		shift.internal_guard = row.employee
		shift.shift_type = shift_label
		shift.start_date = start_dt
		shift.end_date = end_dt
		shift.farm = last_farm
		shift.synced_from_hr_shift = row.hr_shift_assignment
		shift.remarks = "Auto-synced from HR roster (" + row.hr_shift_assignment + ")"
		try:
			shift.insert(ignore_permissions=True)
			created += 1
		except Exception as e:
			# One guard's bad data (e.g. an overlap the sync itself can't
			# see coming) must never stop the rest of the sweep.
			frappe.log_error("sync_shifts_from_hr_roster row", str(e))

	if created:
		frappe.db.commit()

	return {"rostered_today": len(rostered), "created": created, "already_existed": already_existed}


def check_contractor_document_expiry():
	"""Warn Security Heads/System Managers about contractor compliance
	documents (insurance, safety certs, permits) that have expired or are
	about to, so access isn't quietly running on a lapsed certificate until
	someone happens to notice at the gate.

	One Notification Log per affected Supplier per day, not per document —
	a contractor with three expiring documents gets one bell notification
	listing all three, not three separate ones. Re-sends daily on purpose
	(unlike the HR roster sync's insert-once pattern) since an unresolved
	expiry is exactly the kind of thing that should keep nagging until
	someone renews the document or the record is updated.

	Runs daily.
	"""
	horizon = frappe.utils.add_days(frappe.utils.today(), 14)

	expiring = frappe.db.sql(
		"""
		SELECT cd.parent AS supplier, cd.document_type, cd.title, cd.expiry_date
		FROM `tabContractor Compliance Document` cd
		WHERE cd.parenttype = 'Supplier'
		  AND cd.expiry_date <= %(horizon)s
		ORDER BY cd.parent, cd.expiry_date
		""",
		{"horizon": horizon},
		as_dict=True,
	)

	if not expiring:
		return {"suppliers_flagged": 0}

	by_supplier = {}
	for row in expiring:
		by_supplier.setdefault(row.supplier, []).append(row)

	# parenttype must be filtered to "User" — Has Role is a generic child
	# table also used by Role Profile, so an unfiltered query pulls in
	# Role Profile names (e.g. "General Manager-Kaitet LTD") alongside real
	# User logins, and Notification Log.for_user rejects anything that isn't
	# an actual User.
	recipients = frappe.get_all(
		"Has Role",
		filters={"role": ["in", ("Security Head", "System Manager")], "parenttype": "User"},
		fields=["parent"],
		distinct=True,
	)
	recipient_users = [r.parent for r in recipients if r.parent != "Administrator"]

	today_str = frappe.utils.today()
	today_date = frappe.utils.getdate(today_str)
	flagged = 0
	for supplier, docs in by_supplier.items():
		supplier_name = frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier
		lines = []
		for d in docs:
			status_word = "EXPIRED" if d.expiry_date < today_date else "expiring"
			lines.append(
				"- "
				+ d.document_type
				+ (" (" + d.title + ")" if d.title else "")
				+ ": "
				+ status_word
				+ " "
				+ str(d.expiry_date)
			)
		message = "Contractor " + supplier_name + " has compliance documents needing attention:\n" + "\n".join(lines)

		already_sent_today = frappe.db.exists(
			"Notification Log",
			{
				"document_type": "Supplier",
				"document_name": supplier,
				"subject": ["like", "Contractor compliance:%"],
				"creation": [">=", today_str],
			},
		)
		if already_sent_today:
			continue

		for user in recipient_users:
			notification = frappe.new_doc("Notification Log")
			notification.for_user = user
			notification.subject = "Contractor compliance: " + supplier_name
			notification.email_content = message.replace("\n", "<br>")
			notification.document_type = "Supplier"
			notification.document_name = supplier
			notification.type = "Alert"
			try:
				notification.insert(ignore_permissions=True)
			except Exception as e:
				# One bad recipient (e.g. a disabled/deleted User) must never
				# stop the rest from being notified.
				frappe.log_error("check_contractor_document_expiry notify", str(e))
		flagged += 1

	if flagged:
		frappe.db.commit()

	return {"suppliers_flagged": flagged}


def check_overdue_capa_actions():
	"""Nag whoever a corrective action is assigned to (plus Security Heads/
	System Managers) once a CAPA Action's due_date has passed and it's still
	not Completed — an incident isn't actually closed just because someone
	set status=Resolved on the parent Incident Report if the corrective
	action itself never got done.

	Same one-per-record-per-day dedup as check_contractor_document_expiry,
	same "re-send daily until resolved" philosophy, same reasoning for why
	Has Role is filtered to parenttype='User'.

	Runs daily.
	"""
	today_str = frappe.utils.today()

	overdue = frappe.db.sql(
		"""
		SELECT ca.name AS capa_name, ca.parent AS incident, ca.action_description,
		       ca.assigned_to, ca.due_date
		FROM `tabCAPA Action` ca
		WHERE ca.parenttype = 'Incident Report'
		  AND ca.status != 'Completed'
		  AND ca.due_date < %(today)s
		""",
		{"today": today_str},
		as_dict=True,
	)

	if not overdue:
		return {"actions_flagged": 0}

	head_rows = frappe.get_all(
		"Has Role",
		filters={"role": ["in", ("Security Head", "System Manager")], "parenttype": "User"},
		fields=["parent"],
		distinct=True,
	)
	head_users = [r.parent for r in head_rows if r.parent != "Administrator"]

	flagged = 0
	for row in overdue:
		already_sent_today = frappe.db.exists(
			"Notification Log",
			{
				"document_type": "Incident Report",
				"document_name": row.incident,
				"subject": ["like", "Overdue corrective action:%" + row.capa_name + "%"],
				"creation": [">=", today_str],
			},
		)
		if already_sent_today:
			continue

		message = (
			"Corrective action on "
			+ row.incident
			+ " was due "
			+ str(row.due_date)
			+ " and is still not marked Completed:\n"
			+ row.action_description
		)

		assignee_user = frappe.db.get_value("Employee", row.assigned_to, "user_id")
		recipients = list(head_users)
		if assignee_user and assignee_user not in recipients:
			recipients.append(assignee_user)

		for user in recipients:
			notification = frappe.new_doc("Notification Log")
			notification.for_user = user
			notification.subject = "Overdue corrective action: " + row.incident + " [" + row.capa_name + "]"
			notification.email_content = message.replace("\n", "<br>")
			notification.document_type = "Incident Report"
			notification.document_name = row.incident
			notification.type = "Alert"
			try:
				notification.insert(ignore_permissions=True)
			except Exception as e:
				frappe.log_error("check_overdue_capa_actions notify", str(e))
		flagged += 1

	if flagged:
		frappe.db.commit()

	return {"actions_flagged": flagged}


def _point_in_polygon(lat, lng, ring):
	"""Ray-casting point-in-polygon test. `ring` is a list of (lng, lat)
	pairs — GeoJSON coordinate order, matched by Frappe's Geolocation field.
	Handles simple polygons (no holes) — a farm boundary is always a single
	outer ring, so that's all this needs to support."""
	inside = False
	n = len(ring)
	j = n - 1
	i = 0
	while i < n:
		xi, yi = ring[i]
		xj, yj = ring[j]
		if (yi > lat) != (yj > lat):
			x_intersect = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
			if lng < x_intersect:
				inside = not inside
		j = i
		i = i + 1
	return inside


def _farm_boundary_ring(farm):
	"""Pull the outer ring (list of (lng, lat) pairs) out of a Farm's Geo
	Data boundary, or None if this farm has no boundary on record yet."""
	boundary_json = frappe.db.get_value("Geo Data", {"farm": farm}, "boundary")
	if not boundary_json:
		return None
	try:
		parsed = json.loads(boundary_json)
	except Exception:
		return None
	features = parsed.get("features") or []
	if not features:
		return None
	geometry = features[0].get("geometry") or {}
	coordinates = geometry.get("coordinates") or []
	geom_type = geometry.get("type")
	if geom_type == "Polygon" and coordinates:
		return coordinates[0]
	if geom_type == "MultiPolygon" and coordinates:
		return coordinates[0][0]
	return None


def _recent_alert_exists(shift_name, alert_kind):
	"""One alert per shift per kind per hour — this task runs every 15
	minutes (see hooks.py), and a guard who's genuinely out of zone or
	unreachable should keep getting flagged, just not four times an hour."""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-55)
	return frappe.db.exists(
		"Notification Log",
		{
			"document_type": "Security Guard Shift Assignment",
			"document_name": shift_name,
			"subject": ["like", alert_kind + ":%"],
			"creation": [">=", cutoff],
		},
	)


def _resolve_security_head_phone(company, farm):
	"""Same farm-then-company-then-org-fallback resolution as the
	get_security_head_contact Server Script — duplicated here rather than
	imported because Server Scripts aren't importable Python modules. Kept
	deliberately small and in lockstep with that script; if the routing
	logic ever changes there, mirror the change here too."""
	contact_name = ""
	phone = ""
	if farm:
		rows = frappe.db.sql(
			"SELECT u.full_name, u.mobile_no, u.phone "
			"FROM `tabUser Permission` up "
			"JOIN `tabHas Role` hr ON hr.parent = up.user AND hr.role = 'Security Head' "
			"JOIN `tabUser` u ON u.name = up.user "
			"WHERE up.allow = 'Farm' AND up.for_value = %s LIMIT 1",
			(farm,),
			as_dict=True,
		)
		if rows:
			contact_name = rows[0].full_name or ""
			phone = rows[0].mobile_no or rows[0].phone or ""
	if not phone and company:
		rows = frappe.db.sql(
			"SELECT u.full_name, u.mobile_no, u.phone "
			"FROM `tabUser Permission` up "
			"JOIN `tabHas Role` hr ON hr.parent = up.user AND hr.role = 'Security Head' "
			"JOIN `tabUser` u ON u.name = up.user "
			"WHERE up.allow = 'Company' AND up.for_value = %s LIMIT 1",
			(company,),
			as_dict=True,
		)
		if rows:
			contact_name = rows[0].full_name or ""
			phone = rows[0].mobile_no or rows[0].phone or ""
	if not phone:
		settings = frappe.db.get_value(
			"Security Ops Settings",
			"Security Ops Settings",
			["fallback_contact_name", "fallback_contact_phone"],
			as_dict=True,
		)
		if settings and settings.fallback_contact_phone:
			contact_name = settings.fallback_contact_name or "Security Operations"
			phone = settings.fallback_contact_phone
	return contact_name, phone


def _escalate_lone_worker(shift_name, guard_label, company, farm, last_seen):
	"""A guard silent for 60+ minutes (double the initial 30-minute
	threshold) gets escalated beyond a Desk bell notification: an actual SOS
	Incident Report is opened (so it's tracked and can't just get missed in
	a notification list), and the alert to Security Heads includes the
	resolved Security Head phone number directly, closing the loop toward
	the same contact a guard's own panic button would reach.

	Only escalates once per silence episode — guarded by checking whether an
	auto-created SOS Incident Report already exists for this shift's current
	gap (marked via a distinctive tag in the description), not by the
	1-hour Notification Log dedup used elsewhere, since an open incident
	should not multiply just because the check keeps running every 15
	minutes while the guard stays unreachable.
	"""
	tag = "[auto-lone-worker:" + shift_name + "]"
	already_escalated = frappe.db.exists(
		"Incident Report",
		{"description": ["like", "%" + tag + "%"], "status": ["!=", "Closed"]},
	)
	if already_escalated:
		return None

	head_name, head_phone = _resolve_security_head_phone(company, farm)
	contact_line = (
		"Security Head on file: " + head_name + " " + head_phone
		if head_phone
		else "No Security Head contact could be resolved for this guard's company/farm — check Security Ops Settings fallback."
	)

	incident = frappe.new_doc("Incident Report")
	incident.flags.ignore_links = True
	incident.flags.ignore_mandatory = True
	incident.incident_datetime = frappe.utils.now_datetime()
	incident.location = farm or ""
	incident.nature_of_incident = "SOS"
	incident.severity = "Critical"
	incident.status = "Open"
	incident.description = (
		"Auto-opened: guard "
		+ guard_label
		+ " (shift "
		+ shift_name
		+ ") has sent no GPS ping since "
		+ str(last_seen)
		+ " — over 60 minutes of silence. "
		+ contact_line
		+ " "
		+ tag
	)
	try:
		incident.insert(ignore_permissions=True)
	except Exception as e:
		frappe.log_error("_escalate_lone_worker", str(e))
		return None
	return incident.name, head_phone


def _notify_security_ops(shift_name, alert_kind, message):
	head_rows = frappe.get_all(
		"Has Role",
		filters={"role": ["in", ("Security Head", "System Manager")], "parenttype": "User"},
		fields=["parent"],
		distinct=True,
	)
	for row in head_rows:
		if row.parent == "Administrator":
			continue
		notification = frappe.new_doc("Notification Log")
		notification.for_user = row.parent
		notification.subject = alert_kind + ": " + shift_name
		notification.email_content = message.replace("\n", "<br>")
		notification.document_type = "Security Guard Shift Assignment"
		notification.document_name = shift_name
		notification.type = "Alert"
		try:
			notification.insert(ignore_permissions=True)
		except Exception as e:
			frappe.log_error("check_patrol_geofence_and_gaps notify", str(e))


def check_patrol_geofence_and_gaps():
	"""For every currently Active shift: flag a guard who's gone quiet (no
	GPS ping in the last 30 minutes) and, separately, flag a guard whose most
	recent ping falls outside their assigned farm's boundary — a live
	real-time check, not just the after-the-fact Patrol Map visualization.

	A shift with no farm assigned, or a farm with no Geo Data boundary on
	record yet, only gets the missed-check-in test — there's nothing to
	geofence against. This is a real, known local-bench gap (no Geo Data
	boundaries exist here yet, only on production) — the missed-check-in
	half of this task works regardless and is fully testable without one.

	A guard silent for 60+ minutes (double the missed-check-in threshold)
	gets escalated beyond a Desk notification — see _escalate_lone_worker.
	This is this app's answer to a "lone worker check-in timer": there's no
	separate button-press check-in from the guard, the GPS ping itself IS
	the check-in signal, and losing it long enough auto-opens a tracked SOS
	incident with the Security Head's phone number attached.

	Runs every 15 minutes.
	"""
	active_shifts = frappe.get_all(
		"Security Guard Shift Assignment",
		filters={"status": "Active"},
		fields=["name", "security_guard", "internal_guard", "external_guard", "farm"],
	)

	gap_flagged = 0
	geofence_flagged = 0
	escalated = 0
	stale_cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-30)
	escalation_cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-60)

	for shift in active_shifts:
		if shift.security_guard == "Internal Guard":
			guard_filter = {"personel": "Internal Guard", "internal_guard": shift.internal_guard}
			guard_label = shift.internal_guard
			company = frappe.db.get_value("Employee", shift.internal_guard, "company")
		else:
			guard_filter = {"personel": "External Guard", "external_guard": shift.external_guard}
			guard_label = shift.external_guard
			company = frappe.db.get_value("Security Guard", shift.external_guard, "company")

		if not guard_label:
			continue

		latest = frappe.get_all(
			"Patrol GPS Log",
			filters=guard_filter,
			fields=["captured_at", "latitude", "longitude"],
			order_by="captured_at desc",
			limit_page_length=1,
		)

		if not latest or frappe.utils.get_datetime(latest[0].captured_at) < frappe.utils.get_datetime(stale_cutoff):
			last_seen = str(latest[0].captured_at) if latest else "never this shift"

			# 60+ minutes of total silence (not just past this run's 30-minute
			# threshold) escalates to an actual tracked SOS incident, on top
			# of the regular Desk notification below.
			if not latest or frappe.utils.get_datetime(latest[0].captured_at) < frappe.utils.get_datetime(escalation_cutoff):
				result = _escalate_lone_worker(shift.name, guard_label, company, shift.farm, last_seen)
				if result:
					escalated += 1

			if not _recent_alert_exists(shift.name, "Missed check-in"):
				_notify_security_ops(
					shift.name,
					"Missed check-in",
					"Guard " + guard_label + " (shift " + shift.name + ") has sent no GPS ping in over 30 minutes. Last seen: " + last_seen,
				)
				gap_flagged += 1
			continue

		if not shift.farm:
			continue

		ring = _farm_boundary_ring(shift.farm)
		if not ring:
			continue

		try:
			lat = float(latest[0].latitude)
			lng = float(latest[0].longitude)
		except (TypeError, ValueError):
			continue

		if not _point_in_polygon(lat, lng, ring):
			if not _recent_alert_exists(shift.name, "Outside assigned zone"):
				_notify_security_ops(
					shift.name,
					"Outside assigned zone",
					"Guard " + guard_label + " (shift " + shift.name + ") is currently outside the boundary of their assigned farm ("
					+ shift.farm + "). Last position: " + str(lat) + ", " + str(lng)
					+ " at " + str(latest[0].captured_at),
				)
				geofence_flagged += 1

	if gap_flagged or geofence_flagged or escalated:
		frappe.db.commit()

	return {
		"shifts_checked": len(active_shifts),
		"missed_checkin_alerts": gap_flagged,
		"geofence_alerts": geofence_flagged,
		"lone_worker_escalations": escalated,
	}
