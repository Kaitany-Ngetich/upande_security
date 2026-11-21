// Faces are switched off unless CCTV Settings records the legal approval.
const PRES = "upande_security.cctv.presence";

frappe.ui.form.on("CCTV Person Profile", {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role(["System Manager", "Security Head"])) return;
		if (frm.doc.status === "Active") {
			frm.add_custom_button(__("Enrol face at sites"), () =>
				frappe.confirm(__("Send {0}'s face images to the site agents? Only with recorded consent.", [frm.doc.full_name]), () =>
					frappe.xcall(`${PRES}.enroll`, { profile: frm.doc.name }).then((r) =>
						frappe.msgprint(__("Enrolment requested at {0} site(s). The profile updates when each site confirms.", [r.commands.length])))),
				__("Faces"));
		}
		if (frm.doc.face_enrolled) {
			frm.add_custom_button(__("Withdraw consent"), () =>
				frappe.prompt({ fieldname: "note", fieldtype: "Small Text", label: __("How was it withdrawn (form, email, in person)?") },
					(v) => frappe.xcall(`${PRES}.withdraw_consent`, { profile: frm.doc.name, note: v.note }).then(() => frm.reload_doc()),
					__("Withdraw consent")), __("Faces"));
		}
		frm.add_custom_button(__("Export personal data"), () =>
			frappe.xcall(`${PRES}.export_person_data`, { profile: frm.doc.name }).then((data) => {
				const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
				const a = document.createElement("a");
				a.href = URL.createObjectURL(blob);
				a.download = `${frm.doc.name}-personal-data.json`;
				a.click();
			}), __("Data request"));
		frm.add_custom_button(__("Erase person"), () =>
			frappe.confirm(__("Erase {0}? Faces are removed from every site, sightings deleted, the profile anonymised. This cannot be undone.", [frm.doc.full_name]), () =>
				frappe.xcall(`${PRES}.erase_person`, { profile: frm.doc.name }).then((r) => {
					frappe.msgprint(__("Erased: {0} sightings deleted; face removal requested at {1} site(s).", [r.sightings_deleted, r.commands.length]));
					frm.reload_doc();
				})), __("Data request"));
	},
});
