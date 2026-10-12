// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

/**
 * Field pickers for the Dispatch Source and Vehicle Task Source tables.
 *
 * Both tables describe how to read some OTHER doctype at the gate: which of
 * its fields holds the vehicle, the driver, the status, and so on. Those were
 * free-text Data fields, so a typo in `vehicle_field` produced a config that
 * looked fine and silently failed at the gate - the lookup just found nothing.
 *
 * `source_doctype` is now a Link to DocType, and every "which field" box is an
 * Autocomplete populated from the fields that doctype actually has. Picking is
 * now the default; typing a wrong name takes deliberate effort.
 *
 * Autocomplete rather than Select on purpose: a Select would reject anything
 * not in its list, and existing rows may name a field this client cannot see
 * (a doctype from an app that is not installed here). Autocomplete suggests
 * without forbidding, so no saved configuration breaks.
 *
 * Options are set per row in `form_render`, not once per column. Each row can
 * point at a different doctype, and a grid column shares one docfield across
 * every row - setting options at column level would offer Delivery Note's
 * fields while editing the Dispatch Form row.
 */

// Which Autocomplete boxes name a field on the SOURCE doctype itself.
const PARENT_FIELD_PICKERS = {
	"Dispatch Source": [
		"reference_field",
		"vehicle_field",
		"driver_field",
		"date_field",
		"time_field",
		"farm_field",
		"items_summary_field",
		"status_field",
	],
	"Vehicle Task Source": [
		"reference_field",
		"vehicle_field",
		"description_field",
		"farm_field",
		"status_field",
	],
};

// Boxes that name a Table field on the source doctype.
const TABLE_PICKERS = { "Dispatch Source": ["items_child_table"] };

// Boxes that name a field on the CHILD table chosen in items_child_table -
// not on the source doctype. Offering the parent's fields here would be
// actively misleading.
const CHILD_FIELD_PICKERS = {
	"Dispatch Source": ["item_code_field", "item_name_field", "item_qty_field", "item_uom_field"],
};

// Layout and display-only fieldtypes can never be read as a value.
const NON_DATA_FIELDTYPES = new Set([
	"Section Break",
	"Column Break",
	"Tab Break",
	"HTML",
	"Heading",
	"Button",
	"Fold",
	"Image",
]);

function fieldChoices(meta, predicate) {
	if (!meta || !meta.fields) return [];
	return meta.fields
		.filter((df) => !NON_DATA_FIELDTYPES.has(df.fieldtype))
		.filter((df) => (predicate ? predicate(df) : true))
		.map((df) => ({
			value: df.fieldname,
			// The label is what makes this usable - nobody remembers that the
			// truck is in `custom_truck`.
			label: `${df.fieldname} — ${df.label || df.fieldtype} (${df.fieldtype})`,
		}));
}

function setOptions(grid_row, fieldname, choices) {
	const field = grid_row && grid_row.get_field && grid_row.get_field(fieldname);
	if (!field) return;
	field.df.options = choices;
	// get_data is what the Autocomplete control actually reads once rendered;
	// setting df.options alone only takes effect on first draw.
	field.df.get_data = () => choices;
	if (field.set_data) field.set_data(choices);
}

async function refreshRowPickers(frm, cdt, cdn) {
	const row = locals[cdt] && locals[cdt][cdn];
	const grid_row = frm.fields_dict[gridFieldFor(cdt)]
		&& frm.fields_dict[gridFieldFor(cdt)].grid.grid_rows_by_docname[cdn];
	if (!row || !grid_row) return;

	const parentPickers = PARENT_FIELD_PICKERS[cdt] || [];
	const tablePickers = TABLE_PICKERS[cdt] || [];
	const childPickers = CHILD_FIELD_PICKERS[cdt] || [];

	// No source doctype yet: clear the pickers rather than leaving the
	// previous doctype's fields on offer.
	if (!row.source_doctype) {
		[...parentPickers, ...tablePickers, ...childPickers].forEach((f) =>
			setOptions(grid_row, f, [])
		);
		return;
	}

	await frappe.model.with_doctype(row.source_doctype);
	const meta = frappe.get_meta(row.source_doctype);

	const allFields = fieldChoices(meta);
	parentPickers.forEach((f) => setOptions(grid_row, f, allFields));

	const tableFields = fieldChoices(meta, (df) => df.fieldtype === "Table");
	tablePickers.forEach((f) => setOptions(grid_row, f, tableFields));

	// Child-row fields come from whichever Table was picked, so they stay
	// empty until items_child_table is set.
	if (childPickers.length) {
		let childChoices = [];
		if (row.items_child_table) {
			const tableDf = (meta.fields || []).find(
				(df) => df.fieldname === row.items_child_table && df.fieldtype === "Table"
			);
			if (tableDf && tableDf.options) {
				await frappe.model.with_doctype(tableDf.options);
				childChoices = fieldChoices(frappe.get_meta(tableDf.options));
			}
		}
		childPickers.forEach((f) => setOptions(grid_row, f, childChoices));
	}
}

function gridFieldFor(cdt) {
	return cdt === "Dispatch Source" ? "dispatch_sources" : "vehicle_task_sources";
}

["Dispatch Source", "Vehicle Task Source"].forEach((cdt) => {
	frappe.ui.form.on(cdt, {
		// Fires when a grid row is expanded for editing - the only point at
		// which that row's controls exist and can be given options.
		form_render(frm, child_cdt, cdn) {
			refreshRowPickers(frm, cdt, cdn);
		},
		source_doctype(frm, child_cdt, cdn) {
			const row = locals[cdt][cdn];
			// Field names from the previous doctype are meaningless now, and
			// leaving them looks like working configuration.
			const stale = [
				...(PARENT_FIELD_PICKERS[cdt] || []),
				...(TABLE_PICKERS[cdt] || []),
				...(CHILD_FIELD_PICKERS[cdt] || []),
			];
			stale.forEach((f) => {
				if (row[f]) frappe.model.set_value(cdt, cdn, f, "");
			});
			refreshRowPickers(frm, cdt, cdn);
		},
		items_child_table(frm, child_cdt, cdn) {
			const row = locals[cdt][cdn];
			(CHILD_FIELD_PICKERS[cdt] || []).forEach((f) => {
				if (row[f]) frappe.model.set_value(cdt, cdn, f, "");
			});
			refreshRowPickers(frm, cdt, cdn);
		},
	});
});
