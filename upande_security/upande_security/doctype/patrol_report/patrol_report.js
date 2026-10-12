// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("Patrol Report", {
	refresh(frm) {
		if (frm.doc.patrol && frm.doc.points_logged) {
			frm.add_custom_button(__("View GPS Trail"), () => {
				frappe.set_route("List", "Patrol GPS Log", { patrol: frm.doc.patrol });
			});
		}

		// The Incident Report is raised server-side on save, so there is nothing
		// to click for the guard — only somewhere to go once it exists.
		if (frm.doc.incident_report) {
			frm.add_custom_button(__("Open Incident Report"), () => {
				frappe.set_route("Form", "Incident Report", frm.doc.incident_report);
			}).addClass("btn-primary");
		}

		if (frm.is_new() && frm.doc.report_type === "Incident") {
			frm.set_intro(
				__("Saving this will raise an Incident Report automatically — you do not need to fill one in separately."),
				"orange"
			);
		}
	},

	report_type(frm) {
		// Severity and category only mean something on an incident; clear them
		// going the other way so a downgraded report keeps nothing stale.
		if (frm.doc.report_type !== "Incident") {
			frm.set_value("severity", null);
			frm.set_value("nature_of_incident", null);
			frm.set_intro("");
			return;
		}
		if (!frm.doc.severity) frm.set_value("severity", "Medium");
		if (frm.is_new()) {
			frm.set_intro(
				__("Saving this will raise an Incident Report automatically — you do not need to fill one in separately."),
				"orange"
			);
		}
	},
});


// ---------------------------------------------------------------------------
// Migrated out of a Client Script record (verbatim). Frappe accumulates
// multiple frappe.ui.form.on registrations for the same doctype, so this
// block's handlers run alongside the ones above rather than replacing them.
// ---------------------------------------------------------------------------

// ---- was Client Script: patrol report review actions ----
// Drives Patrol Report's existing "Supervisor Review" fields (status,
// reviewed_by, reviewed_on, supervisor_remarks) with real Desk buttons,
// same pattern as "Incident Report - Resolve Button" — those fields
// already existed on this doctype but had no UI to actually use them
// without hand-editing the raw form.
frappe.ui.form.on('Patrol Report', {
    refresh: function(frm) {
        frm.clear_custom_buttons();
        let status = frm.doc.status;

        if (!['Reviewed', 'Flagged'].includes(status)) {
            frm.add_custom_button('✅ Mark Reviewed', function() {
                let d = new frappe.ui.Dialog({
                    title: '✅ Mark Reviewed',
                    fields: [
                        { fieldname: 'remarks', fieldtype: 'Small Text', label: 'Remarks (optional)' }
                    ],
                    primary_action_label: 'Mark Reviewed',
                    primary_action: function(values) {
                        frappe.call({
                            method: 'frappe.client.set_value',
                            args: {
                                doctype: 'Patrol Report',
                                name: frm.docname,
                                fieldname: {
                                    status: 'Reviewed',
                                    reviewed_by: frappe.session.user,
                                    reviewed_on: frappe.datetime.now_datetime(),
                                    supervisor_remarks: values.remarks || frm.doc.supervisor_remarks
                                }
                            },
                            callback: function(r) {
                                if (!r.exc) {
                                    frappe.show_alert({ message: '✅ Patrol report marked reviewed', indicator: 'green' }, 5);
                                    d.hide();
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                });
                d.show();
            }, 'Review Actions').addClass('btn-success');

            frm.add_custom_button('🚩 Flag for Follow-up', function() {
                let d = new frappe.ui.Dialog({
                    title: '🚩 Flag for Follow-up',
                    fields: [
                        { fieldname: 'remarks', fieldtype: 'Small Text', label: 'Why is this being flagged?', reqd: 1 }
                    ],
                    primary_action_label: '🚩 Flag',
                    primary_action: function(values) {
                        frappe.call({
                            method: 'frappe.client.set_value',
                            args: {
                                doctype: 'Patrol Report',
                                name: frm.docname,
                                fieldname: {
                                    status: 'Flagged',
                                    reviewed_by: frappe.session.user,
                                    reviewed_on: frappe.datetime.now_datetime(),
                                    supervisor_remarks: values.remarks
                                }
                            },
                            callback: function(r) {
                                if (!r.exc) {
                                    frappe.show_alert({ message: '🚩 Patrol report flagged for follow-up', indicator: 'orange' }, 5);
                                    d.hide();
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                });
                d.show();
            }, 'Review Actions').addClass('btn-danger');
        }

        if (['Reviewed', 'Flagged'].includes(status)) {
            frm.add_custom_button('📝 Add Follow-up Note', function() {
                let d = new frappe.ui.Dialog({
                    title: '📝 Add Follow-up Note',
                    fields: [
                        { fieldname: 'note', fieldtype: 'Small Text', label: 'Note / Update', reqd: 1 }
                    ],
                    primary_action_label: 'Save Note',
                    primary_action: function(values) {
                        let existing = frm.doc.supervisor_remarks || '';
                        let timestamp = frappe.datetime.now_datetime();
                        let updated = existing + (existing ? '\n\n' : '') + '[' + timestamp + '] ' + values.note;
                        frappe.call({
                            method: 'frappe.client.set_value',
                            args: { doctype: 'Patrol Report', name: frm.docname, fieldname: 'supervisor_remarks', value: updated },
                            callback: function(r) {
                                if (!r.exc) {
                                    frappe.show_alert({ message: '✅ Note added', indicator: 'green' }, 4);
                                    d.hide();
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                });
                d.show();
            }, 'Review Actions');
        }

        if (status === 'Flagged') {
            frm.add_custom_button('✅ Clear Flag (Mark Reviewed)', function() {
                frappe.confirm('Clear the flag on this patrol report and mark it reviewed?', function() {
                    frappe.call({
                        method: 'frappe.client.set_value',
                        args: {
                            doctype: 'Patrol Report',
                            name: frm.docname,
                            fieldname: { status: 'Reviewed', reviewed_by: frappe.session.user, reviewed_on: frappe.datetime.now_datetime() }
                        },
                        callback: function(r) {
                            if (!r.exc) {
                                frappe.show_alert({ message: '✅ Flag cleared', indicator: 'green' }, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                });
            }, 'Review Actions');
        }

        if (status === 'Reviewed') {
            frm.dashboard.set_headline_alert(
                '<span class="indicator-pill green">Reviewed by ' + (frm.doc.reviewed_by || '') +
                    (frm.doc.reviewed_on ? ' on ' + frappe.datetime.str_to_user(frm.doc.reviewed_on) : '') + '</span>'
            );
        }
        if (status === 'Flagged') {
            frm.dashboard.set_headline_alert(
                '<span class="indicator-pill orange">🚩 Flagged by ' + (frm.doc.reviewed_by || '') +
                    (frm.doc.reviewed_on ? ' on ' + frappe.datetime.str_to_user(frm.doc.reviewed_on) : '') + '</span>'
            );
        }
    }
});

