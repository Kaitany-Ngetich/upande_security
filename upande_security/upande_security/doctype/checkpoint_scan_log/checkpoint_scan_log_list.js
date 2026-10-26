// Result as the row's status indicator (beside the checkpoint name) rather
// than a list column - a Select column renders as a pill floating above the
// row and stretches every row.
const CHECKPOINT_SCAN_COLOURS = {
	Valid: "green",
	"Too Far": "red",
	"Fake GPS": "red",
	"Unknown Code": "red",
	"Poor GPS": "orange",
	"Position Not Set": "gray",
	"Inactive Checkpoint": "gray",
};

frappe.listview_settings["Checkpoint Scan Log"] = {
	add_fields: ["result"],
	hide_name_column: true,
	get_indicator(doc) {
		return [__(doc.result), CHECKPOINT_SCAN_COLOURS[doc.result] || "gray", "result,=," + doc.result];
	},
};
