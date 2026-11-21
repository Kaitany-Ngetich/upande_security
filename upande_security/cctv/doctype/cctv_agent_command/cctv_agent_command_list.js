frappe.listview_settings["CCTV Agent Command"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const c = { Queued: "gray", Sent: "blue", Done: "green", Failed: "red", Expired: "orange" };
		return [__(doc.status), c[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
