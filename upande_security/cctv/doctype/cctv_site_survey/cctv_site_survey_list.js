frappe.listview_settings["CCTV Site Survey"] = {
	add_fields: ["verdict"],
	get_indicator(doc) {
		const c = { Ready: "green", "Ready with fixes": "orange", "Not ready": "red" };
		return [__(doc.verdict || "-"), c[doc.verdict] || "gray", `verdict,=,${doc.verdict}`];
	},
	onload(listview) {
		if (!frappe.user.has_role(["System Manager", "Security Head"])) return;
		// A survey run on a technician's laptop (python -m cctv_agent.survey): upload its .json (and .html).
		listview.page.add_inner_button(__("Import survey from laptop"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Import a site survey"),
				fields: [
					{ fieldtype: "HTML", options: `<p class="text-muted">${__("Run <code>python -m cctv_agent.survey --brand … --host …</code> on a laptop at the site, then attach the two files it wrote.")}</p>` },
					{ fieldname: "json", fieldtype: "Attach", label: __("survey-….json"), reqd: 1 },
					{ fieldname: "html", fieldtype: "Attach", label: __("survey-….html (optional)") },
					{ fieldname: "server", fieldtype: "Link", options: "CCTV Server", label: __("Recorder (if already set up)") },
				],
				primary_action_label: __("Import"),
				primary_action(v) {
					frappe.xcall("upande_security.cctv.survey.import_survey", { file_url: v.json, html_file_url: v.html, server: v.server }).then((r) => {
						d.hide();
						frappe.set_route("Form", "CCTV Site Survey", r.survey);
					});
				},
			});
			d.show();
		});
	},
};
