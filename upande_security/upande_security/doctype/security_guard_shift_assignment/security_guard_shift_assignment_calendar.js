frappe.views.calendar["Security Guard Shift Assignment"] = {
	field_map: {
		start: "start_date",
		end: "end_date",
		id: "name",
		title: "title",
		color: "color",
		allDay: "allDay",
	},
	gantt: {
		field_map: {
			start: "start_date",
			end: "end_date",
			id: "name",
			title: "title",
			color: "color",
			progress: "progress",
		},
	},
	filters: [
		{
			fieldtype: "Link",
			fieldname: "farm",
			options: "Farm",
			label: __("Farm"),
		},
		{
			fieldtype: "Select",
			fieldname: "status",
			options: "\nScheduled\nActive\nEnded\nCancelled",
			label: __("Status"),
		},
	],
	get_events_method:
		"upande_security.upande_security.doctype.security_guard_shift_assignment.security_guard_shift_assignment.get_shift_events",
};
