frappe.ui.form.on("CCTV Camera", {
	refresh(frm) {
		if (!frm.is_new()) frm.add_custom_button(__("Live view"), () => window.open("/security-dashboard-v2#/cctv-live", "_blank"));
		if (!frm.is_new()) frm.add_custom_button(__("Place on site map"), () => window.open("/security-dashboard-v2#/cctv-map", "_blank"));
		if (frm.is_new() && !frm.doc.camera_code) frm.set_df_property("camera_code", "placeholder", __("made on save, e.g. KPK-GATE-01"));
		frm.set_query("zone", () => ({ filters: { farm: frm.doc.farm } }));
	},
});
