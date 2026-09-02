// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("Security Guard Shift Assignment", {
	refresh(frm) {
		set_block_query(frm);
		render_rotation_plans(frm);
		render_off_days(frm);
	},
	external_guard(frm) {
		// Guard changed — both the off-days list and the rotation-plans list
		// below it were queried for the old guard.
		render_rotation_plans(frm);
		render_off_days(frm);
	},
	new_rotation_plan_btn(frm) {
		if (!frm.doc.external_guard) {
			frappe.msgprint(__("Pick an External Guard first."));
			return;
		}
		frappe.new_doc("Security Guard Rotation Plan", {
			external_guard: frm.doc.external_guard,
		});
	},
	farm(frm) {
		// Farm changed — clear a block that no longer belongs to it, and
		// re-scope the picker to the new farm.
		if (frm.doc.block) {
			frm.set_value("block", null);
		}
		set_block_query(frm);
	},
	security_guard(frm) {
		// Internal Guard shifts are mirrored in automatically from HR's own
		// Shift Type / Shift Assignment (see sync_shifts_from_hr_roster) —
		// nobody plans them by hand here. The server rejects this too
		// (validate_internal_guard_shift_is_hr_owned), but catch it up front
		// so a Security Head isn't left guessing after a failed save.
		if (frm.is_new() && frm.doc.security_guard === "Internal Guard") {
			frappe.show_alert(
				{
					message: __(
						"Internal Guard shifts aren't planned here — they're mirrored in from HR's Shift Type / Shift Assignment. Set up the guard's shift in HR instead."
					),
					indicator: "orange",
				},
				7,
			);
			frm.set_value("security_guard", "External Guard");
		}
	},
});

function set_block_query(frm) {
	frm.set_query("block", () => {
		return { filters: { farm: frm.doc.farm || "" } };
	});
}

function render_rotation_plans(frm) {
	// Only meaningful for a saved External Guard row — a new/unsaved
	// document has nothing to look up yet, and rotation planning is an
	// External Guard concept (Internal Guard shifts stay HR-owned).
	const field = frm.get_field("rotation_plans_html");
	if (!field) return;

	if (frm.doc.security_guard !== "External Guard" || !frm.doc.external_guard) {
		field.$wrapper.html("");
		return;
	}

	field.$wrapper.html(`<div class="text-muted">${__("Loading rotation plans…")}</div>`);

	frappe.db
		.get_list("Security Guard Rotation Plan", {
			filters: { external_guard: frm.doc.external_guard },
			fields: ["name", "start_date", "end_date", "mode", "status", "rotation_interval_days"],
			order_by: "modified desc",
			limit: 10,
		})
		.then((plans) => {
			if (!plans.length) {
				field.$wrapper.html(
					`<div class="text-muted">${__("No rotation plans yet for this guard.")}</div>`
				);
				return;
			}

			const status_indicator = { Draft: "orange", Applied: "green", Cancelled: "gray" };
			const rows = plans
				.map((p) => {
					const color = status_indicator[p.status] || "gray";
					return `
						<tr class="rotation-plan-row" data-name="${frappe.utils.escape_html(p.name)}" style="cursor:pointer">
							<td>${frappe.utils.escape_html(p.name)}</td>
							<td>${frappe.datetime.str_to_user(p.start_date)} → ${frappe.datetime.str_to_user(p.end_date)}</td>
							<td>${frappe.utils.escape_html(p.mode)} (${p.rotation_interval_days}d)</td>
							<td><span class="indicator-pill ${color}">${frappe.utils.escape_html(p.status)}</span></td>
						</tr>`;
				})
				.join("");

			field.$wrapper.html(`
				<table class="table table-bordered" style="margin-bottom:0">
					<thead>
						<tr>
							<th>${__("Plan")}</th>
							<th>${__("Window")}</th>
							<th>${__("Mode")}</th>
							<th>${__("Status")}</th>
						</tr>
					</thead>
					<tbody>${rows}</tbody>
				</table>
			`);

			field.$wrapper.find(".rotation-plan-row").on("click", function () {
				frappe.set_route("Form", "Security Guard Rotation Plan", $(this).data("name"));
			});
		});
}

function render_off_days(frm) {
	// Inline off-day manager for the current External Guard — replaces the
	// old read-only "fetched Holiday List" field with a genuinely editable
	// list scoped to this guard and reused across all their Shift
	// Assignment / Rotation Plan records (see api/guard_off_days.py).
	const field = frm.get_field("off_days_html");
	if (!field) return;

	if (frm.doc.security_guard !== "External Guard" || !frm.doc.external_guard) {
		field.$wrapper.html("");
		return;
	}

	field.$wrapper.html(`<div class="text-muted">${__("Loading off days…")}</div>`);

	frappe.db
		.get_list("Security Guard Off Days", {
			filters: { external_guard: frm.doc.external_guard },
			fields: ["name"],
			limit: 1,
		})
		.then((records) => {
			if (!records.length) {
				return { off_days: [] };
			}
			return frappe.db.get_doc("Security Guard Off Days", records[0].name).then((doc) => ({
				off_days: (doc.off_days || []).slice().sort((a, b) => (a.off_date > b.off_date ? 1 : -1)),
			}));
		})
		.then(({ off_days }) => {
			draw_off_days(frm, field, off_days);
		});
}

function draw_off_days(frm, field, off_days) {
	const rows = off_days.length
		? off_days
				.map(
					(row) => `
						<tr>
							<td>${frappe.datetime.str_to_user(row.off_date)}</td>
							<td>${frappe.utils.escape_html(row.remarks || "")}</td>
							<td class="text-right">
								<a href="#" class="off-day-remove text-danger" data-date="${frappe.utils.escape_html(row.off_date)}" title="${__("Remove")}">&times;</a>
							</td>
						</tr>`
				)
				.join("")
		: `<tr><td colspan="3" class="text-muted">${__("No off days configured for this guard yet.")}</td></tr>`;

	field.$wrapper.html(`
		<div class="off-days-manager">
			<button class="btn btn-xs btn-default off-day-add" style="margin-bottom: 8px">
				${__("+ Add Off-Day")}
			</button>
			<table class="table table-bordered" style="margin-bottom:0">
				<thead>
					<tr>
						<th>${__("Date")}</th>
						<th>${__("Remarks")}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`);

	field.$wrapper.find(".off-day-add").on("click", (e) => {
		e.preventDefault();
		frappe.prompt(
			[
				{
					fieldname: "off_date",
					fieldtype: "Date",
					label: __("Off Date"),
					reqd: 1,
				},
				{
					fieldname: "remarks",
					fieldtype: "Small Text",
					label: __("Remarks"),
				},
			],
			(values) => {
				frappe.call({
					method: "upande_security.api.guard_off_days.add_guard_off_day",
					args: {
						external_guard: frm.doc.external_guard,
						off_date: values.off_date,
						remarks: values.remarks,
					},
					freeze: true,
				}).then((r) => {
					draw_off_days(frm, field, (r.message && r.message.off_days) || []);
				});
			},
			__("Add Off-Day"),
			__("Add")
		);
	});

	field.$wrapper.find(".off-day-remove").on("click", function (e) {
		e.preventDefault();
		const off_date = $(this).data("date");
		frappe.call({
			method: "upande_security.api.guard_off_days.remove_guard_off_day",
			args: {
				external_guard: frm.doc.external_guard,
				off_date: off_date,
			},
			freeze: true,
		}).then((r) => {
			draw_off_days(frm, field, (r.message && r.message.off_days) || []);
		});
	});
}
