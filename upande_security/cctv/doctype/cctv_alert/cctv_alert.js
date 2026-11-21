// Copyright (c) 2026, dev@upande.com and contributors
// The alert's actions. "Play footage" opens the Security Dashboard alert page,
// which plays the recorder's clip cued to the event.

const ALERT_API = "upande_security.cctv.alerts";

frappe.ui.form.on("CCTV Alert", {
	onload(frm) {
		if (!frm.is_new() && !frm.doc.first_viewed_by) frappe.xcall(`${ALERT_API}.mark_viewed`, { name: frm.doc.name });
	},
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Play footage"), () =>
			window.open(`/security-dashboard-v2#/cctv-alerts?alert=${encodeURIComponent(frm.doc.name)}`, "_blank"));
		const open = ["Open", "Escalated", "Acknowledged"].includes(frm.doc.status);
		if (!open || !frm.perm[0]?.write) return;
		const run = (method, args, msg) =>
			frappe.xcall(`${ALERT_API}.${method}`, { name: frm.doc.name, ...args }).then(() => {
				frappe.show_alert({ message: msg, indicator: "green" });
				frm.reload_doc();
			});
		if (frm.doc.status !== "Acknowledged") {
			frm.add_custom_button(__("Acknowledge"), () => run("acknowledge", {}, __("Acknowledged"))).addClass("btn-primary");
		}
		frm.add_custom_button(__("Resolve"), () =>
			frappe.prompt({ fieldname: "notes", fieldtype: "Small Text", label: __("What was found / done") },
				(v) => run("resolve", { notes: v.notes }, __("Resolved")), __("Resolve alert")), __("Actions"));
		frm.add_custom_button(__("False alarm"), () => {
			const reasons = (frappe.meta.get_docfield("CCTV Alert", "false_alarm_reason").options || "").split("\n").filter(Boolean);
			frappe.prompt([
				{ fieldname: "reason", fieldtype: "Select", label: __("Why"), options: reasons, reqd: 1 },
				{ fieldname: "notes", fieldtype: "Small Text", label: __("Notes") },
			], (v) => run("mark_false_alarm", v, __("Marked a false alarm")), __("False alarm"));
		}, __("Actions"));
		frm.add_custom_button(__("Escalate now"), () => run("escalate", {}, __("Escalated")), __("Actions"));
		if (!frm.doc.incident) {
			frm.add_custom_button(__("Create incident"), () =>
				frappe.xcall(`${ALERT_API}.create_incident`, { name: frm.doc.name }).then((r) => frappe.set_route("Form", "Incident Report", r.incident)),
			__("Actions"));
		}
	},
});
