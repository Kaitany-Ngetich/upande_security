frappe.ui.form.on("CCTV Camera", {
	refresh(frm) {
		if (!frm.is_new()) frm.add_custom_button(__("Live view"), () => window.open("/security-dashboard-v2#/cctv-live", "_blank"));
		frm.set_query("zone", () => ({ filters: { farm: frm.doc.farm } }));
	},
});
