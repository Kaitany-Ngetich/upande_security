const VEH_API = "upande_security.cctv.vehicles";

frappe.ui.form.on("CCTV Vehicle Visit", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Vehicles board"), () => window.open("/security-dashboard-v2#/cctv-vehicles", "_blank"));
		if (!["On Premises", "Overstayed", "Exit Not Recorded"].includes(frm.doc.status)) return;
		if (!frm.doc.guard_confirmed) {
			frm.add_custom_button(__("Confirm"), () =>
				frappe.xcall(`${VEH_API}.confirm_visit`, { name: frm.doc.name }).then(() => frm.reload_doc())).addClass("btn-primary");
		}
		frm.add_custom_button(__("Correct plate"), () =>
			frappe.prompt({ fieldname: "plate", fieldtype: "Data", label: __("Plate"), default: frm.doc.plate, reqd: 1 },
				(v) => frappe.xcall(`${VEH_API}.confirm_visit`, { name: frm.doc.name, corrected_plate: v.plate }).then(() => frm.reload_doc()),
				__("Correct plate")), __("Actions"));
		frm.add_custom_button(__("Left - close visit"), () =>
			frappe.prompt({ fieldname: "notes", fieldtype: "Small Text", label: __("Notes") },
				(v) => frappe.xcall(`${VEH_API}.close_visit`, { name: frm.doc.name, notes: v.notes }).then(() => frm.reload_doc()),
				__("Close visit")), __("Actions"));
	},
});
