import frappe


def sync_shift_checkin(doc, method=None):
	if not doc.employee or not doc.in_time:
		return

	assignments = frappe.get_all(
		"Security Guard Shift Assignment",
		filters={
			"internal_guard": doc.employee,
			"status": "Active",
			"checked_in": 0,
			"start_date": ["<=", doc.attendance_date],
			"end_date": [">=", doc.attendance_date],
		},
		pluck="name",
	)

	for name in assignments:
		frappe.db.set_value("Security Guard Shift Assignment", name, "checked_in", 1)
