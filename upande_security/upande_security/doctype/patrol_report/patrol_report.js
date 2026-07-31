// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("Patrol Report", {
	refresh(frm) {
		if (frm.doc.patrol && frm.doc.points_logged) {
			frm.add_custom_button(__("View GPS Trail"), () => {
				frappe.set_route("List", "Patrol GPS Log", { patrol: frm.doc.patrol });
			});
		}
	},
});
