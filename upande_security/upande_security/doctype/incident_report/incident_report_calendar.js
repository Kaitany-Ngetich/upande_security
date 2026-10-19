// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

// Calendar view of incidents (Incident Report > Calendar), one entry per
// incident at its incident time, coloured by severity (set server-side).
// Filter Nature of Incident = Theft for the theft pattern.

frappe.views.calendar["Incident Report"] = {
	field_map: {
		start: "incident_datetime",
		end: "incident_datetime",
		id: "name",
		title: "nature_of_incident",
		allDay: "all_day",
		color: "color",
	},
	fields: ["name", "nature_of_incident", "incident_datetime", "severity", "farm"],
	get_events_method: "upande_security.api.security_dashboard.incident_calendar_events",
};
