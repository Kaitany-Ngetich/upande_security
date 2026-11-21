frappe.listview_settings["CCTV Vehicle Visit"] = {
	add_fields: ["status", "guard_confirmed"],
	get_indicator(doc) {
		const c = { "On Premises": "blue", Overstayed: "orange", Departed: "green", "Exit Not Recorded": "red", "Closed Manually": "gray", Expected: "gray", Cancelled: "gray" };
		return [__(doc.status), c[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
