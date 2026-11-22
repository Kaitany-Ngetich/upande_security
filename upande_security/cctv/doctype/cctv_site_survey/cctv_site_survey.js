frappe.ui.form.on("CCTV Site Survey", {
	refresh(frm) {
		const colour = { Ready: "green", "Ready with fixes": "orange", "Not ready": "red" }[frm.doc.verdict];
		if (frm.doc.verdict) frm.set_intro(__("Verdict: {0}. See Findings below; the full report has every camera, disk, log entry and API call.", [frm.doc.verdict]), colour);
		if (frm.doc.report_file) {
			frm.add_custom_button(__("Open full report"), () => window.open(frm.doc.report_file, "_blank")).addClass("btn-primary");
		}
		if (frm.doc.server) frm.add_custom_button(__("Recorder"), () => frappe.set_route("Form", "CCTV Server", frm.doc.server));
	},
});
