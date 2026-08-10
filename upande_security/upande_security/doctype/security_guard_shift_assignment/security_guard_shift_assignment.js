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
});

function set_block_query(frm) {
	frm.set_query("block", () => {
		return { filters: { farm: frm.doc.farm || "" } };
	});
}
