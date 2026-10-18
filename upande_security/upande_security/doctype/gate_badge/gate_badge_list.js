// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

const BADGE_METHODS = "upande_security.upande_security.doctype.gate_badge.gate_badge";

frappe.listview_settings["Gate Badge"] = {
	add_fields: ["badge_type", "status"],

	get_indicator(doc) {
		const colors = { Available: "green", Issued: "orange", Lost: "red" };
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},

	onload(listview) {
		if (!frappe.user.has_role(["Security Head", "System Manager"])) return;
		// Create a pool of badges in one go, numbered on from the highest
		// there is - per farm for visitor badges, per company otherwise. Each
		// gets its QR. Print them afterwards by selecting them and choosing
		// the Gate Badge Card.
		listview.page.add_inner_button(__("Create Badges"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Create Badges"),
				fields: [
					{ fieldname: "badge_type", fieldtype: "Select", label: __("Badge Type"), reqd: 1,
					  options: "Visitor\nSupplier\nContractor",
					  default: listview.filters.find((f) => f[1] === "badge_type")?.[3] || "Visitor",
					  onchange: () => show_range() },
					{ fieldname: "company", fieldtype: "Link", options: "Company", label: __("Company"), reqd: 1,
					  default: frappe.defaults.get_user_default("Company"), onchange: () => show_range() },
					{ fieldname: "farm", fieldtype: "Link", options: "Farm", label: __("Farm"),
					  depends_on: "eval:doc.badge_type=='Visitor'", mandatory_depends_on: "eval:doc.badge_type=='Visitor'",
					  get_query: () => ({ filters: { company: d.get_value("company") } }),
					  onchange: () => show_range() },
					{ fieldname: "count", fieldtype: "Int", label: __("How many"), reqd: 1, default: 50,
					  onchange: () => show_range() },
					{ fieldname: "range", fieldtype: "HTML" },
				],
				primary_action_label: __("Create"),
				primary_action(values) {
					d.disable_primary_action();
					frappe
						.call({
							method: BADGE_METHODS + ".create_badges",
							args: values,
							freeze: true,
							freeze_message: __("Creating badges..."),
						})
						.then((r) => {
							const m = r.message || {};
							d.hide();
							frappe.show_alert({
								message: __("{0} {1} badges created, numbered {2} to {3}",
									[m.created, values.badge_type.toLowerCase(), m.first, m.last]),
								indicator: "green",
							});
							listview.refresh();
						})
						.always(() => d.enable_primary_action());
				},
			});
			// Numbers carry on from the highest in that pool - show where.
			const show_range = () => {
				const { badge_type, company, farm, count } = d.get_values(true) || {};
				const el = d.get_field("range").$wrapper;
				if (!badge_type || !company || !count || (badge_type === "Visitor" && !farm)) return el.html("");
				frappe
					.call(BADGE_METHODS + ".next_number", { badge_type, company, farm })
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
