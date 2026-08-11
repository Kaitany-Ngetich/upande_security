// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("Security Guard Shift Assignment", {
	refresh(frm) {
		set_block_query(frm);
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
