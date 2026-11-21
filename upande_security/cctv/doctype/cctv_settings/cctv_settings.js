const SETUP_API = "upande_security.cctv.admin";

frappe.ui.form.on("CCTV Settings", {
	refresh(frm) {
		frm.set_intro(frm.doc.enabled ? "" : __("CCTV is switched off: no events are accepted and no CCTV pages show. Switch on only after the legal review."), "orange");
		if (!frappe.user.has_role("System Manager")) return;
		frm.add_custom_button(__("New gateway token secret"), () =>
			frappe.confirm(__("Replace the secret the media gateways check viewing tokens with? Agents pick it up within a minute."), () =>
				frappe.xcall(`${SETUP_API}.generate_gateway_secret`).then(() => frm.reload_doc())), __("Setup"));
		frm.add_custom_button(__("Load demo data"), () =>
			frappe.prompt({ fieldname: "farm", fieldtype: "Link", options: "Farm", label: __("Site"), reqd: 1 },
				(v) => frappe.xcall(`${SETUP_API}.load_demo`, { farm: v.farm }).then((r) =>
					frappe.msgprint(__("Demo cameras and {0} simulated events added at {1}. Open the Security Dashboard's CCTV pages.", [r.events, v.farm]))),
				__("Demo data (names start with DEMO)")), __("Setup"));
		frm.add_custom_button(__("Clear demo data"), () =>
			frappe.confirm(__("Delete the DEMO cameras and everything they produced?"), () =>
				frappe.xcall(`${SETUP_API}.clear_demo`).then(() => frappe.show_alert({ message: __("Demo data removed"), indicator: "green" }))), __("Setup"));
	},
});
