// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("Security Guard Rotation Plan", {
	refresh(frm) {
		set_block_queries(frm);

		// The whitelisted methods run against the saved DB copy of this doc
		// (see run_doc_method), so a dirty/new form has nothing meaningful
		// to generate or apply yet.
		if (frm.is_new() || frm.is_dirty() || frm.doc.status !== "Draft") {
			return;
		}

		if (frm.doc.mode === "Automatic") {
			frm.add_custom_button(__("Generate & Apply"), () => {
				frappe.confirm(
					__(
						"Automatic mode has no separate preview step - this generates the full rotation schedule and immediately creates real Shift Assignments for every non-off day. Continue?"
					),
					() => {
						frm.call("generate_and_apply").then((r) => {
							frm.reload_doc();
							if (r.message) {
								const p = r.message.preview;
								const a = r.message.apply;
								frappe.msgprint(
									__("Generated {0} day(s) ({1} off). Applied {2}, {3} failed.", [
										p.rows,
										p.off_days,
										a.applied,
										a.failed,
									])
								);
							}
						});
					}
				);
			}).addClass("btn-primary");
			return;
		}

		// Semi-Automatic: preview first, apply as a separate deliberate step
		// so the Security Head can edit a day's farm before committing it.
		frm.add_custom_button(__("Generate Preview"), () => {
			frm.call("generate_preview").then((r) => {
				frm.reload_doc();
				if (r.message) {
					frappe.show_alert({
						message: __("Generated {0} day(s), {1} marked off.", [r.message.rows, r.message.off_days]),
						indicator: "green",
					});
				}
			});
		});

		const has_pending = (frm.doc.preview_rows || []).some((row) => row.status === "Pending");
		if (has_pending) {
			frm.add_custom_button(__("Apply Rotation"), () => {
				frappe.confirm(
					__(
						"This creates real Shift Assignments for every Pending row in the preview below. Off-day rows are skipped. Continue?"
					),
					() => {
						frm.call("apply_rotation").then((r) => {
							frm.reload_doc();
							if (r.message) {
								frappe.msgprint(
									__("Applied {0}, {1} failed, {2} off-day row(s) skipped.", [
										r.message.applied,
										r.message.failed,
										r.message.skipped,
									])
								);
							}
						});
					}
				);
			}).addClass("btn-primary");
		}
	},
});

// Both rotation_farms and preview_rows pair a farm with an optional block —
// same farm-scopes-block relationship as Security Guard Shift Assignment's
// own set_block_query, just applied per-grid-row instead of to a single
// top-level field.
function set_block_queries(frm) {
	frm.set_query("block", "rotation_farms", (doc, cdt, cdn) => {
		const row = locals[cdt][cdn];
		return { filters: { farm: row.farm || "" } };
	});
	frm.set_query("block", "preview_rows", (doc, cdt, cdn) => {
		const row = locals[cdt][cdn];
		return { filters: { farm: row.farm || "" } };
	});
}

frappe.ui.form.on("Security Guard Rotation Farm", {
	farm(frm, cdt, cdn) {
		// Farm changed — a block picked for the old farm no longer applies.
		frappe.model.set_value(cdt, cdn, "block", null);
	},
});

frappe.ui.form.on("Security Guard Rotation Preview Row", {
	farm(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "block", null);
	},
	is_off_day(frm, cdt, cdn) {
		// Checking/unchecking this box is a real, immediate action - not
		// just editing a field to save later. It cancels or creates the
		// actual Shift Assignment for this guard/date right now (same
		// underlying call as the Shift Schedule grid's own off-day
		// checkbox), whether this plan is Draft or already Applied.
		//
		// A plain frappe.call on purpose, not frm.call - frm.call runs
		// Document methods through run_doc_method, which syncs the WHOLE
		// doc (every preview row) back from the server on every response,
		// visibly repainting the entire table for a single-row edit. This
		// only ever touches the one row that changed.
		if (frm.is_new()) return; // nothing real to toggle yet - no saved doc, no guard-scoped rows possible
		const row = locals[cdt][cdn];
		const mark_off = row.is_off_day ? 1 : 0;
		const grid_row = frm.fields_dict.preview_rows.grid.grid_rows_by_docname[cdn];
		if (grid_row) grid_row.wrapper.css("opacity", 0.5);

		frappe.call({
			method: "upande_security.upande_security.doctype.security_guard_rotation_plan.security_guard_rotation_plan.toggle_preview_row_off_day",
			args: { plan_name: frm.doc.name, row_name: cdn, mark_off },
		}).then((r) => {
			if (grid_row) grid_row.wrapper.css("opacity", "");
			const res = r.message;
			if (!res) return;
			frappe.model.set_value(cdt, cdn, "status", res.status);

			let msg;
			if (res.state === "on") msg = __("Marked back on duty.");
			else if (res.state === "off_covered") msg = __("Off day set - covered by {0}.", [res.covered_by_name || res.covered_by]);
			else if (res.state === "off_unfilled") msg = __("Off day set - {0}", [res.reason || __("reliever already covering someone else")]);
			else msg = __("Off day set - no reliever assigned to this guard.");
			frappe.show_alert({ message: msg, indicator: res.state === "on" ? "green" : "blue" });
		}).catch(() => {
			if (grid_row) grid_row.wrapper.css("opacity", "");
			// Revert the checkbox - the write didn't happen.
			frappe.model.set_value(cdt, cdn, "is_off_day", mark_off ? 0 : 1);
		});
	},
});
