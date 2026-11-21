// Camera setup wizard: test the recorder, discover its channels through the
// site agent, then create the cameras you tick.
const CMD = "upande_security.cctv.commands";

function waitFor(name, label) {
	return new Promise((resolve, reject) => {
		const d = frappe.show_progress(label, 10, 100, __("Waiting for the site agent…"));
		let n = 0;
		const tick = () =>
			frappe.xcall(`${CMD}.command_status`, { name }).then((r) => {
				n += 1;
				frappe.show_progress(label, Math.min(10 + n * 3, 95), 100, __("Waiting for the site agent…"));
				if (r.status === "Done") { frappe.hide_progress(); resolve(r); }
				else if (["Failed", "Expired"].includes(r.status)) { frappe.hide_progress(); reject(r.error || r.status); }
				else if (n > 100) { frappe.hide_progress(); reject(__("No answer yet - the agent may be offline. Check Camera health.")); }
				else setTimeout(tick, 3000);
			});
		tick();
	});
}

frappe.ui.form.on("CCTV Server", {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role(["System Manager", "Security Head"])) return;
		frm.add_custom_button(__("Test connection"), () =>
			frappe.xcall(`${CMD}.test_connection`, { server: frm.doc.name })
				.then((r) => waitFor(r.command, __("Testing {0}", [frm.doc.server_name])))
				.then((r) => { frappe.msgprint(__("Reached: {0} {1}, clock offset {2}s", [r.result.model || "", r.result.firmware || "", r.result.time_offset_seconds ?? "?"])); frm.reload_doc(); })
				.catch((e) => frappe.msgprint({ title: __("Could not reach the recorder"), message: String(e), indicator: "red" })),
			__("Setup"));
		frm.add_custom_button(__("Discover cameras"), () =>
			frappe.xcall(`${CMD}.discover`, { server: frm.doc.name })
				.then((r) => waitFor(r.command, __("Discovering cameras")))
				.then((r) => pick(frm, (r.result && r.result.channels) || []))
				.catch((e) => frappe.msgprint({ title: __("Discovery failed"), message: String(e), indicator: "red" })),
			__("Setup")).addClass("btn-primary");
	},
});

function pick(frm, channels) {
	if (!channels.length) return frappe.msgprint(__("The recorder reported no channels."));
	const roles = ["Overview", "Gate", "Entry", "Exit", "Parking", "Dock", "Door", "Corridor", "Perimeter", "Cold Room", "Other"];
	const d = new frappe.ui.Dialog({
		title: __("Cameras found on {0}", [frm.doc.server_name]),
		size: "extra-large",
		fields: [
			{ fieldtype: "HTML", options: `<p class="text-muted">${__("Tick the cameras to add, set each one's role and zone. Plate (ANPR) and face cameras need the calibration step afterwards (regions, direction).")}</p>` },
			{
				fieldname: "rows", fieldtype: "Table", cannot_add_rows: true, in_place_edit: true,
				data: channels.map((c) => ({ ...c, add: c.already ? 0 : 1, camera_name: c.name || `Channel ${c.channel_no}`, role: c.anpr ? "Gate" : "Overview" })),
				fields: [
					{ fieldname: "add", fieldtype: "Check", label: __("Add"), in_list_view: 1, columns: 1 },
					{ fieldname: "channel_no", fieldtype: "Int", label: __("Ch"), in_list_view: 1, read_only: 1, columns: 1 },
					{ fieldname: "camera_name", fieldtype: "Data", label: __("Name"), in_list_view: 1, columns: 3 },
					{ fieldname: "role", fieldtype: "Select", options: roles.join("\n"), label: __("Role"), in_list_view: 1, columns: 2 },
					{ fieldname: "zone", fieldtype: "Link", options: "Security Zone", label: __("Zone"), in_list_view: 1, columns: 2 },
					{ fieldname: "resolution", fieldtype: "Data", label: __("Stream"), in_list_view: 1, read_only: 1, columns: 1 },
					{ fieldname: "main_stream", fieldtype: "Data", hidden: 1 }, { fieldname: "sub_stream", fieldtype: "Data", hidden: 1 },
					{ fieldname: "codec", fieldtype: "Data", hidden: 1 }, { fieldname: "anpr", fieldtype: "Check", hidden: 1 }, { fieldname: "face", fieldtype: "Check", hidden: 1 },
				],
			},
		],
		primary_action_label: __("Add cameras"),
		primary_action(v) {
			const chosen = (v.rows || []).filter((r) => r.add);
			frappe.xcall(`${CMD}.create_cameras`, { server: frm.doc.name, channels: chosen }).then((r) => {
				d.hide();
				frappe.show_alert({ message: __("{0} cameras added", [r.created.length]), indicator: "green" });
				frappe.set_route("List", "CCTV Camera", { server: frm.doc.name });
			});
		},
	});
	d.show();
}
