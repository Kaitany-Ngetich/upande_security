frappe.listview_settings["CCTV Alert"] = {
	add_fields: ["status", "severity"],
	get_indicator(doc) {
		const sev = { Critical: "red", High: "orange", Medium: "yellow", Low: "blue", Info: "gray" };
		if (doc.status === "Resolved") return [__("Resolved"), "green", "status,=,Resolved"];
		if (doc.status === "False Alarm") return [__("False Alarm"), "gray", "status,=,False Alarm"];
		return [__(`${doc.status} · ${doc.severity}`), sev[doc.severity] || "gray", `status,=,${doc.status}`];
	},
};
