// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

frappe.listview_settings["Contractor Badge"] = {
	get_indicator(doc) {
		const colors = { Available: "green", Issued: "orange", Lost: "red" };
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},

	onload(listview) {
		if (!frappe.user.has_role(["Security Head", "System Manager"])) return;
		// Create a company's whole badge pool in one go - each badge gets its
		// QR; numbers that already exist are skipped. Print them afterwards
		// by selecting the badges and choosing the Contractor Badge Card.
		listview.page.add_inner_button(__("Create Badges"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Create Contractor Badges"),
				fields: [
					{ fieldname: "company", fieldtype: "Link", options: "Company", label: __("Company"), reqd: 1,
					  default: frappe.defaults.get_user_default("Company") },
					{ fieldname: "col", fieldtype: "Column Break" },
					{ fieldname: "from_number", fieldtype: "Int", label: __("From badge number"), reqd: 1, default: 1 },
					{ fieldname: "to_number", fieldtype: "Int", label: __("To badge number"), reqd: 1, default: 50 },
				],
				primary_action_label: __("Create"),
				primary_action(values) {
					d.disable_primary_action();
					frappe
						.call({
							method: "upande_security.api.contractor_badge.create_contractor_badges",
							args: values,
							freeze: true,
							freeze_message: __("Creating badges..."),
						})
						.then((r) => {
							const m = r.message || {};
							d.hide();
							frappe.show_alert({
								message: m.created
									? __("{0} badges created ({1}-{2}){3}", [m.created, m.first, m.last,
										m.skipped ? __(", {0} already existed", [m.skipped]) : ""])
									: __("All of those badges already exist."),
								indicator: m.created ? "green" : "orange",
							});
							listview.refresh();
						})
						.always(() => d.enable_primary_action());
				},
			});
			d.show();
		});
	},
};
