// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("Guard Device Token", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.expo_push_token) return;
		frm.add_custom_button(__("Push Update"), () => {
			frappe.call({
				method: "upande_security.api.app_devices.push_app_update",
				args: { names: [frm.doc.name] },
				freeze: true,
				callback: (r) => {
					upande_security_show_push_result(r.message);
					frm.reload_doc();
				},
			});
		});
	},
});

window.upande_security_show_push_result =
	window.upande_security_show_push_result ||
	function (res) {
	if (!res) return;
	if (res.error) {
		frappe.msgprint({ title: __("Push failed"), indicator: "red", message: res.error });
		return;
	}
	let msg = __("Update push sent to {0} phone(s).", [res.pushed]);
	if (res.no_push_token) msg += "<br>" + __("{0} without a push token (notifications off) were skipped.", [res.no_push_token]);
	if (res.needs_new_install)
		msg += "<br>" + __("{0} need a new install - an update push cannot reach their app version.", [res.needs_new_install]);
	frappe.msgprint({ title: __("App update"), indicator: "green", message: msg });
};
