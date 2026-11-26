frappe.ui.form.on("CCTV Review Item", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.status !== "Resolved") {
			frm.add_custom_button(__("Review on the plate screen"), () => window.open("/security-dashboard-v2#/cctv-review", "_blank")).addClass("btn-primary");
		}
	},
});
