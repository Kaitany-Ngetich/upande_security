// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

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

const UPDATE_STATUS_COLOURS = {
	"Up to date": "green",
	Outdated: "orange",
	"Needs New Install": "red",
	"Unknown (old app)": "gray",
};

frappe.listview_settings["Guard Device Token"] = {
	add_fields: ["update_status"],
	get_indicator(doc) {
		if (!doc.update_status) return;
		return [__(doc.update_status), UPDATE_STATUS_COLOURS[doc.update_status] || "gray", "update_status,=," + doc.update_status];
	},
	onload(listview) {
		listview.page.add_inner_button(__("Push Update to All Outdated"), () => {
			frappe.confirm(__("Send the update push to every phone that is not up to date?"), () => {
				frappe.call({
					method: "upande_security.api.app_devices.push_update_to_outdated",
					freeze: true,
					callback: (r) => {
						upande_security_show_push_result(r.message);
						listview.refresh();
					},
				});
			});
		});
		listview.page.add_actions_menu_item(__("Push Update"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) return;
			frappe.call({
				method: "upande_security.api.app_devices.push_app_update",
				args: { names },
				freeze: true,
				callback: (r) => {
					upande_security_show_push_result(r.message);
					listview.refresh();
				},
			});
		});
	},
};
