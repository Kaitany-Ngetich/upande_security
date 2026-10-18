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
					  default: frappe.defaults.get_user_default("Company"), onchange: () => show_range() },
					{ fieldname: "count", fieldtype: "Int", label: __("How many"), reqd: 1, default: 50,
					  onchange: () => show_range() },
					{ fieldname: "range", fieldtype: "HTML" },
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
								message: __("{0} badges created, numbered {1} to {2}", [m.created, m.first, m.last]),
								indicator: "green",
							});
							listview.refresh();
						})
						.always(() => d.enable_primary_action());
				},
			});
			// Numbers carry on from the company's highest badge - show where.
			const show_range = () => {
				const { company, count } = d.get_values(true) || {};
				const el = d.get_field("range").$wrapper;
				if (!company || !count) return el.html("");
				frappe
					.call("upande_security.api.contractor_badge.next_contractor_badge_number", { company })
					.then((r) => {
						const first = r.message || 1;
						el.html(`<p class="text-muted small">${__("They will be numbered {0} to {1}.", [first, first + count - 1])}</p>`);
					});
			};
			d.show();
			show_range();
		});
	},
};
