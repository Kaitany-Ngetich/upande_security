// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

/**
 * Appointment form behaviour at the gate.
 *
 * Migrated out of Client Script records, which lived in the database and so
 * were invisible to git, review and search. Behaviour is unchanged: each
 * block below is its Client Script verbatim.
 *
 * Unlike the Server Script migration, there is NO alias layer here and no
 * shadowing. A Client Script record and this file would BOTH load and both
 * register handlers, so buttons would appear twice and handlers fire twice.
 * The records are therefore deleted outright - that is why nothing is left
 * behind as a rollback.
 *
 * Appointment is a CRM doctype, so this cannot live in a doctype folder;
 * it is wired through the `doctype_js` hook, which MERGES with the
 * doctype's own JS rather than replacing it.
 */

// ---- was Client Script: appointment confirm receipt ----
// Adds a "Confirm Receipt" action button to the Appointment form for hosts
// once their visitor has been checked in and a badge issued — the only
// other way to confirm receipt is scanning the visitor badge's QR code,
// which isn't practical if the host is just looking at the record itself
// (e.g. checking their appointment list at their desk).
frappe.ui.form.on('Appointment', {
	refresh: function (frm) {
		if (
			frm.doc.workflow_state === 'Visitor Checked In' &&
			frm.doc.custom_visitor_badge &&
			!frm.doc.custom_host_received_time
		) {
			frm.add_custom_button('Confirm Receipt', function () {
				frappe.call({
					method: 'confirm_host_received_by_appointment',
					args: { name: frm.doc.name },
					freeze: true,
					freeze_message: __('Confirming...'),
					callback: function (r) {
						if (r.message && r.message.error) {
							frappe.msgprint(r.message.error);
							return;
						}
						frappe.show_alert({ message: __('Visitor receipt confirmed'), indicator: 'green' });
						frm.reload_doc();
					},
				});
			}).addClass('btn-primary');
		}

		if (frm.doc.custom_host_received_time) {
			frm.dashboard.set_headline_alert(
				'<span class="indicator-pill green">Visitor receipt confirmed at ' +
					frappe.datetime.str_to_user(frm.doc.custom_host_received_time) +
					'</span>',
			);
		}
	},
});

// ---- was Client Script: appointment gate workflow actions ----
frappe.ui.form.on('Appointment', {
    before_workflow_action: function(frm) {
        var action = frm.selected_workflow_action;

        if (action === 'Reschedule') {
            frappe.dom.unfreeze();
            return new Promise(function(resolve, reject) {
                var host_id = frm.doc.custom_meet_with || '';
                frappe.db.get_value('Employee', host_id, 'employee_name').then(function(r) {
                    var host_display = (r && r.message && r.message.employee_name) ? r.message.employee_name : host_id;
                    var d = new frappe.ui.Dialog({
                        title: 'Reschedule Visit',
                        fields: [
                            {
                                fieldname: 'visitor_info',
                                fieldtype: 'HTML',
                                options: '<div class="alert alert-info" style="margin-bottom:0"><b>' + (frm.doc.customer_name || '') + '</b> is waiting to see <b>' + host_display + '</b></div>'
                            },
                            {
                                label: 'New Date and Time',
                                fieldname: 'new_scheduled_time',
                                fieldtype: 'Datetime',
                                reqd: 1,
                                default: frappe.datetime.now_datetime()
                            },
                            {
                                label: 'Reason for Rescheduling',
                                fieldname: 'reschedule_reason',
                                fieldtype: 'Small Text',
                                reqd: 1
                            }
                        ],
                        size: 'large',
                        primary_action_label: 'Confirm Reschedule',
                        primary_action: function(values) {
                            d.disable_primary_action();
                            frappe.call({
                                method: 'frappe.client.set_value',
                                args: {
                                    doctype: 'Appointment',
                                    name: frm.doc.name,
                                    fieldname: 'scheduled_time',
                                    value: values.new_scheduled_time
                                },
                                async: false
                            });
                            frappe.call({
                                method: 'frappe.client.insert',
                                args: {
                                    doc: {
                                        doctype: 'Comment',
                                        comment_type: 'Comment',
                                        reference_doctype: 'Appointment',
                                        reference_name: frm.doc.name,
                                        content: '<b>Rescheduled by ' + frappe.session.user_fullname + ':</b> ' + values.reschedule_reason + '<br><b>New time:</b> ' + values.new_scheduled_time,
                                        comment_email: frappe.session.user,
                                        comment_by: frappe.session.user_fullname
                                    }
                                },
                                async: false
                            });
                            frm.reload_doc();
                            d.hide();
                            resolve();
                        }
                    });
                    d.show();
                    d.$wrapper.find('.modal-dialog').css('z-index', 1100);
                    d.$wrapper.find('.modal-backdrop').css('z-index', 1099);
                });
            });
        }

        if (action === 'Redirect to Another Host') {
            frappe.dom.unfreeze();
            return new Promise(function(resolve, reject) {
                var host_id = frm.doc.custom_meet_with || '';
                frappe.db.get_value('Employee', host_id, 'employee_name').then(function(r) {
                    var old_host_display = (r && r.message && r.message.employee_name) ? r.message.employee_name : host_id;
                    var d = new frappe.ui.Dialog({
                        title: 'Redirect Visitor to Another Host',
                        fields: [
                            {
                                fieldname: 'visitor_info',
                                fieldtype: 'HTML',
                                options: '<div class="alert alert-warning" style="margin-bottom:0"><b>' + (frm.doc.customer_name || '') + '</b> was scheduled to see <b>' + old_host_display + '</b> who is unavailable.</div>'
                            },
                            {
                                label: 'Redirect to (New Host)',
                                fieldname: 'new_host',
                                fieldtype: 'Link',
                                options: 'Employee',
                                reqd: 1
                            },
                            {
                                label: 'Reason for Redirect',
                                fieldname: 'redirect_reason',
                                fieldtype: 'Small Text',
                                reqd: 1
                            }
                        ],
                        size: 'large',
                        primary_action_label: 'Confirm Redirect',
                        primary_action: function(values) {
                            d.disable_primary_action();
                            // IMPORTANT: do NOT reassign custom_meet_with here. The
                            // "Redirect to Another Host" workflow transition's own
                            // permission condition checks whether the CURRENT
                            // custom_meet_with resolves to the acting user (the
                            // original host). apply_workflow() always re-reads the
                            // doc fresh from the database at the moment the
                            // transition is applied, so if we rewrote
                            // custom_meet_with to the new host here (before the
                            // transition runs), the original host would fail their
                            // own permission check a few hundred milliseconds
                            // later. Stash the new host on frm and do the actual
                            // field/comment update in after_workflow_action,
                            // once the transition has already gone through.
                            frm._pending_redirect = {
                                new_host: values.new_host,
                                redirect_reason: values.redirect_reason,
                                old_host_display: old_host_display
                            };
                            d.hide();
                            resolve();
                        }
                    });
                    d.show();
                    d.$wrapper.find('.modal-dialog').css('z-index', 1100);
                    d.$wrapper.find('.modal-backdrop').css('z-index', 1099);
                });
            });
        }

        if (action === 'Reject Visit') {
            frappe.dom.unfreeze();
            return new Promise(function(resolve, reject) {
                var host_id = frm.doc.custom_meet_with || '';
                frappe.db.get_value('Employee', host_id, 'employee_name').then(function(r) {
                    var host_display = (r && r.message && r.message.employee_name) ? r.message.employee_name : host_id;
                    var d = new frappe.ui.Dialog({
                        title: 'Reject Visit',
                        fields: [
                            {
                                fieldname: 'visitor_info',
                                fieldtype: 'HTML',
                                options: '<div class="alert alert-danger" style="margin-bottom:0"><b>' + (frm.doc.customer_name || '') + '</b> wants to see <b>' + host_display + '</b></div>'
                            },
                            {
                                label: 'Reason for Rejection',
                                fieldname: 'reject_reason',
                                fieldtype: 'Small Text',
                                reqd: 1
                            }
                        ],
                        size: 'large',
                        primary_action_label: 'Confirm Rejection',
                        primary_action: function(values) {
                            d.disable_primary_action();
                            frappe.call({
                                method: 'frappe.client.insert',
                                args: {
                                    doc: {
                                        doctype: 'Comment',
                                        comment_type: 'Comment',
                                        reference_doctype: 'Appointment',
                                        reference_name: frm.doc.name,
                                        content: '<b>Rejected by ' + frappe.session.user_fullname + ':</b> ' + values.reject_reason,
                                        comment_email: frappe.session.user,
                                        comment_by: frappe.session.user_fullname
                                    }
                                },
                                async: false
                            });
                            d.hide();
                            resolve();
                        }
                    });
                    d.show();
                    d.$wrapper.find('.modal-dialog').css('z-index', 1100);
                    d.$wrapper.find('.modal-backdrop').css('z-index', 1099);
                });
            });
        }

        if (action === 'Approve Visit') {
            frm.doc.custom_reporting_status = 'Scheduled';
            frm.dirty();
        }

        if (action === 'Confirm Check In') {
            frm.doc.custom_check_in_time = frappe.datetime.now_datetime();
            frm.doc.custom_reporting_status = 'Checked in';
            frm.dirty();
        }

        if (action === 'Confirm Check Out') {
            frm.doc.custom_check_out_time = frappe.datetime.now_datetime();
            frm.doc.custom_reporting_status = 'Checked out';
            frm.dirty();
        }
    },

    after_workflow_action: function(frm) {
        // Runs once a workflow transition has actually been applied. The
        // "Redirect to Another Host" reassignment is deferred to here (see
        // before_workflow_action) so the transition's own host-permission
        // condition is evaluated against the ORIGINAL host, not the new one.
        if (frm._pending_redirect) {
            var pending = frm._pending_redirect;
            frm._pending_redirect = null;
            frappe.call({
                method: 'frappe.client.set_value',
                args: {
                    doctype: 'Appointment',
                    name: frm.doc.name,
                    fieldname: 'custom_meet_with',
                    value: pending.new_host
                },
                async: false
            });
            frappe.db.get_value('Employee', pending.new_host, 'employee_name').then(function(r2) {
                var new_host_display = (r2 && r2.message && r2.message.employee_name) ? r2.message.employee_name : pending.new_host;
                frappe.call({
                    method: 'frappe.client.insert',
                    args: {
                        doc: {
                            doctype: 'Comment',
                            comment_type: 'Comment',
                            reference_doctype: 'Appointment',
                            reference_name: frm.doc.name,
                            content: '<b>Redirected by ' + frappe.session.user_fullname + ':</b> ' + pending.redirect_reason + '<br><b>From:</b> ' + pending.old_host_display + ' <b>To:</b> ' + new_host_display,
                            comment_email: frappe.session.user,
                            comment_by: frappe.session.user_fullname
                        }
                    },
                    async: false
                });
                frm.reload_doc();
            });
        }
    },

    refresh: function(frm) {
        var state = frm.doc.workflow_state;
        var is_gate_guard = frappe.user_roles.includes('Gate Guard');
        var is_secretary = frappe.user_roles.includes('Visit Approver');

        if (is_gate_guard && !is_secretary && !frm.is_new()) {
            var gate_editable = ['custom_mode_of_transport', 'custom_vehicles_number_plate', 'custom_vehicles_colour'];
            frm.fields.forEach(function(f) {
                if (!gate_editable.includes(f.df.fieldname) && f.df.fieldtype !== 'Section Break' && f.df.fieldtype !== 'Column Break') {
                    frm.set_df_property(f.df.fieldname, 'read_only', 1);
                }
            });
        }

        if (is_secretary && state === 'Pending Host Review') {
            var secretary_editable = ['custom_meet_with', 'scheduled_time', 'customer_details', 'custom_visitor_type', 'custom_customer'];
            frm.fields.forEach(function(f) {
                if (secretary_editable.includes(f.df.fieldname)) {
                    frm.set_df_property(f.df.fieldname, 'read_only', 0);
                } else if (f.df.fieldtype !== 'Section Break' && f.df.fieldtype !== 'Column Break') {
                    frm.set_df_property(f.df.fieldname, 'read_only', 1);
                }
            });
        }

        if (state === 'Visitor Checked Out') {
            frm.disable_form();
        }

        if (state === 'Visitor Checked In' && frm.doc.custom_check_in_time) {
            var checkin = moment(frm.doc.custom_check_in_time);
            var duration = moment.duration(moment().diff(checkin));
            var hrs = Math.floor(duration.asHours());
            var mins = duration.minutes();
            frm.dashboard.add_indicator('On premises: ' + hrs + 'h ' + mins + 'm', 'blue');
        }

    }
});

// ---- was Client Script: clear appointment party defaults ----
// party/appointment_with are core CRM fields this app never uses
// (locked read-only for Gate Guard/Secretary, never touched by the
// mobile app, custom_customer is the real customer-tracking field).
// Both are hardcoded Link fields to Customer in this ERPNext version
// (not a generic party-type selector, despite the label/filter
// implying otherwise) - so any non-blank value that isn't a real
// Customer record name fails link validation on save.
//
// The crash this fixes: opening "New Appointment" from an
// Appointment list view that has (or ever had) an appointment_with
// filter active lets Frappe carry that filter value into the new
// document as a default - e.g. "Customer" or "Lead" (not an actual
// customer name) - which then fails with "Could not find Appointment
// With: Customer" the moment you try to save, before this doctype's
// own Before Save script ever gets a chance to clear it (link
// validation runs before before_insert/before_save in Frappe's
// document lifecycle, so a server-side clear alone can't prevent
// this on a brand new document - it has to happen client-side).
frappe.ui.form.on("Appointment", {
	onload: function (frm) {
		if (frm.is_new()) {
			frm.set_value("appointment_with", null);
			frm.set_value("party", null);
		}
	},
});

