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
});
