// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("Patrol Report", {
	refresh(frm) {
		if (frm.doc.patrol && frm.doc.points_logged) {
			frm.add_custom_button(__("View GPS Trail"), () => {
				frappe.set_route("List", "Patrol GPS Log", { patrol: frm.doc.patrol });
			});
		}

		// The Incident Report is raised server-side on save, so there is nothing
		// to click for the guard — only somewhere to go once it exists.
		if (frm.doc.incident_report) {
			frm.add_custom_button(__("Open Incident Report"), () => {
				frappe.set_route("Form", "Incident Report", frm.doc.incident_report);
			}).addClass("btn-primary");
		}

		if (frm.is_new() && frm.doc.report_type === "Incident") {
			frm.set_intro(
				__("Saving this will raise an Incident Report automatically — you do not need to fill one in separately."),
				"orange"
			);
		}
	},

	report_type(frm) {
		// Severity and category only mean something on an incident; clear them
		// going the other way so a downgraded report keeps nothing stale.
		if (frm.doc.report_type !== "Incident") {
			frm.set_value("severity", null);
			frm.set_value("nature_of_incident", null);
			frm.set_intro("");
			return;
		}
		if (!frm.doc.severity) frm.set_value("severity", "Medium");
		if (frm.is_new()) {
			frm.set_intro(
				__("Saving this will raise an Incident Report automatically — you do not need to fill one in separately."),
				"orange"
			);
		}
	},
});
