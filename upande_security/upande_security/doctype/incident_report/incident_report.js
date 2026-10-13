// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

/**
 * Incident Report form behaviour.
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
 */

// ---- was Client Script: incident report resolution auto set ----
frappe.ui.form.on('Incident Report', {
    status: function(frm) {
        if (frm.doc.status === 'Resolved' || frm.doc.status === 'Closed') {
            if (!frm.doc.resolution_datetime) {
                frappe.model.set_value(frm.doctype, frm.docname, 'resolution_datetime', frappe.datetime.now_datetime());
            }
        } else {
            // Clear resolution time if status moved back
            frappe.model.set_value(frm.doctype, frm.docname, 'resolution_datetime', null);
        }
    },

    resolution: function(frm) {
        if (frm.doc.resolution && !frm.doc.status.match(/Resolved|Closed/)) {
            frappe.model.set_value(frm.doctype, frm.docname, 'status', 'Resolved');
        }
    }
});

// ---- was Client Script: incident report resolve button ----
frappe.ui.form.on('Incident Report', {
    refresh: function(frm) {
        frm.clear_custom_buttons();
        // Fixed vs. the real production version: that one checks
        // frm.doc.workflow_state, a field that does not exist on this
        // doctype anywhere (confirmed against production itself) - so its
        // Resolved/Closed-state buttons never actually behave as intended
        // there. This checks the real field, `status`, instead. Also drops
        // "Pending Closure Review" from the state list below since it was
        // never a real status option here (or on production).
        let state = frm.doc.status;

        // ─── OPEN / IN PROGRESS ───────────────────────────────────────────────
        if (!['Resolved', 'Closed'].includes(state)) {

            // Add Witnesses / Roll Call
            frm.add_custom_button('👥 Add Witnesses / Roll Call', function() {
                let d = new frappe.ui.Dialog({
                    title: '👥 Witnesses & Roll Call',
                    fields: [
                        { fieldtype: 'Section Break', label: 'Person Details' },
                        { fieldname: 'person_name', fieldtype: 'Data', label: 'Full Name', reqd: 1 },
                        { fieldname: 'role_in_incident', fieldtype: 'Select', label: 'Role',
                          options: 'Witness\nVictim\nFirst Responder\nResponsible Person', reqd: 1 },
                        { fieldname: 'contact', fieldtype: 'Data', label: 'Phone / ID (optional)' },
                        { fieldname: 'statement', fieldtype: 'Small Text', label: 'Statement / Notes' }
                    ],
                    primary_action_label: 'Add Person',
                    primary_action: function(values) {
                        let table_map = {
                            'Witness': 'witnesses',
                            'Victim': 'victims',
                            'First Responder': 'responsible_persons',
                            'Responsible Person': 'responsible_persons'
                        };
                        let table = table_map[values.role_in_incident];
                        let row = frappe.model.add_child(frm.doc, table);
                        row.person_name = values.person_name;
                        if (values.contact) row.contact = values.contact;
                        // Fixed: the real Incident Person child doctype's field
                        // is `notes`, not `statement` - the production script
                        // sets a field that doesn't exist on the row at all.
                        if (values.statement) row.notes = values.statement;
                        frappe.call({
                            method: 'frappe.client.save',
                            args: { doc: frm.doc },
                            callback: function(r) {
                                if (!r.exc) {
                                    frappe.show_alert({message: '✅ ' + values.person_name + ' added as ' + values.role_in_incident, indicator: 'green'}, 4);
                                    frm.reload_doc();
                                    d.hide();
                                }
                            }
                        });
                    }
                });
                d.show();
            }, 'Incident Actions');

            // Add Evidence
            frm.add_custom_button('📎 Add Photo / Evidence', function() {
                let slots = ['attachment_1','attachment_2','attachment_3','attachment_4'];
                let next_slot = slots.find(f => !frm.doc[f]);
                if (!next_slot) { frappe.msgprint('All 4 attachment slots are used.'); return; }
                let d = new frappe.ui.Dialog({
                    title: '📎 Add Evidence / Photo',
                    fields: [
                        { fieldname: 'file', fieldtype: 'Attach', label: 'Upload File', reqd: 1 }
                    ],
                    primary_action_label: 'Attach',
                    primary_action: function(values) {
                        frappe.call({
                            method: 'frappe.client.set_value',
                            args: { doctype: 'Incident Report', name: frm.docname, fieldname: next_slot, value: values.file },
                            callback: function(r) {
                                if (!r.exc) {
                                    frappe.show_alert({message: '✅ File attached', indicator: 'green'}, 4);
                                    frm.reload_doc(); d.hide();
                                }
                            }
                        });
                    }
                });
                d.show();
            }, 'Incident Actions');

            // Resolve Incident
            frm.add_custom_button('✅ Resolve Incident', function() {
                let d = new frappe.ui.Dialog({
                    title: '✅ Resolve Incident',
                    fields: [
                        { fieldtype: 'Section Break', label: 'Resolution' },
                        { fieldname: 'resolution', fieldtype: 'Long Text', label: 'How was the incident resolved?', reqd: 1 },
                        { fieldname: 'corrective_actions', fieldtype: 'Long Text', label: 'Corrective Actions (to prevent recurrence)', reqd: 1 },
                        { fieldtype: 'Column Break' },
                        { fieldname: 'resolution_datetime', fieldtype: 'Datetime', label: 'Resolved At', default: frappe.datetime.now_datetime(), reqd: 1 },
                        { fieldtype: 'Section Break', label: '🚑 Casualties' },
                        { fieldname: 'casualties_wounded', fieldtype: 'Int', label: 'Wounded', default: 0 },
                        { fieldname: 'casualties_deceased', fieldtype: 'Int', label: 'Deceased', default: 0 },
                        { fieldtype: 'Column Break' },
                        { fieldname: 'casualties_hospitalized', fieldtype: 'Int', label: 'Hospitalized', default: 0 },
                        { fieldname: 'casualties_unaccounted', fieldtype: 'Int', label: 'Unaccounted', default: 0 },
                        { fieldname: 'casualties_notes', fieldtype: 'Small Text', label: 'Casualty Notes (optional)' }
                    ],
                    primary_action_label: '✅ Mark Resolved',
                    primary_action: function(values) {
                        frappe.call({
                            method: 'frappe.client.set_value',
                            args: {
                                doctype: 'Incident Report',
                                name: frm.docname,
                                fieldname: {
                                    resolution: values.resolution,
                                    corrective_actions: values.corrective_actions,
                                    resolution_datetime: values.resolution_datetime,
                                    casualties_wounded: values.casualties_wounded,
                                    casualties_deceased: values.casualties_deceased,
                                    casualties_hospitalized: values.casualties_hospitalized,
                                    casualties_unaccounted: values.casualties_unaccounted,
                                    casualties_notes: values.casualties_notes,
                                    status: 'Resolved'
                                }
                            },
                            callback: function(r) {
                                if (!r.exc) {
                                    frappe.show_alert({message: '✅ Incident marked as Resolved!', indicator: 'green'}, 5);
                                } else {
                                    frappe.show_alert({message: '⚠️ Could not update status — resolution details saved', indicator: 'orange'}, 5);
                                }
                                d.hide();
                                frm.reload_doc();
                            }
                        });
                    }
                });
                d.show();
            }, 'Incident Actions').addClass('btn-success');
        }

        // ─── RESOLVED STATE ───────────────────────────────────────────────────
        if (state === 'Resolved') {
            frm.add_custom_button('📝 Add Follow-up Note', function() {
                let d = new frappe.ui.Dialog({
                    title: '📝 Add Follow-up Note',
                    fields: [
                        { fieldname: 'note', fieldtype: 'Long Text', label: 'Note / Update', reqd: 1 }
                    ],
                    primary_action_label: 'Save Note',
                    primary_action: function(values) {
                        let existing = frm.doc.remarks || '';
                        let timestamp = frappe.datetime.now_datetime();
                        let updated = existing + (existing ? '\n\n' : '') + '[' + timestamp + '] ' + values.note;
                        frappe.call({
                            method: 'frappe.client.set_value',
                            args: { doctype: 'Incident Report', name: frm.docname, fieldname: 'remarks', value: updated },
                            callback: function(r) {
                                if (!r.exc) {
                                    frappe.show_alert({message: '✅ Note added', indicator: 'green'}, 4);
                                    frm.reload_doc(); d.hide();
                                }
                            }
                        });
                    }
                });
                d.show();
            }, 'Incident Actions');

            frm.add_custom_button('🔒 Close Incident', function() {
                frappe.confirm('Close this incident? This marks it as fully complete and no further actions will be needed.', function() {
                    frappe.call({
                        method: 'frappe.client.set_value',
                        args: { doctype: 'Incident Report', name: frm.docname, fieldname: 'status', value: 'Closed' },
                        callback: function(r) {
                            if (!r.exc) {
                                frappe.show_alert({message: '🔒 Incident Closed', indicator: 'blue'}, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                });
            }, 'Incident Actions').addClass('btn-primary');
        }

        // ─── CLOSED STATE ─────────────────────────────────────────────────────
        if (state === 'Closed') {
            frm.dashboard.add_comment('🔒 This incident is closed. No further actions required.', 'blue', true);
        }
    }
});


// ---- covert watchlist: start watching a person named on this incident ----
// Registered after the handler above, which calls clear_custom_buttons() on
// refresh, so this button survives it. Shown only to Security Head / System
// Manager - guards must never see that anyone is being watched (see
// upande_security/api/watchlist.py).
frappe.ui.form.on('Incident Report', {
    refresh: function(frm) {
        if (frm.is_new()) return;
        if (!(frappe.user.has_role('Security Head') || frappe.user.has_role('System Manager'))) return;

        frm.add_custom_button(__('Watch a person'), function() {
            const people = [];
            [['responsible_persons', 'Responsible'], ['victims', 'Victim'], ['witnesses', 'Witness']].forEach(function([table, role]) {
                (frm.doc[table] || []).forEach(function(row) {
                    if (row.person_name) {
                        people.push({ value: row.name, label: row.person_name + ' (' + role + (row.id_number ? ', ID ' + row.id_number : '') + ')' });
                    }
                });
            });
            if (!people.length) {
                frappe.msgprint(__('Add the person to Responsible Persons, Victims or Witnesses first, with their ID number or phone if known - those are what the watch matches on.'));
                return;
            }
            const d = new frappe.ui.Dialog({
                title: __('Watch a person'),
                fields: [
                    { fieldname: 'row_name', fieldtype: 'Select', label: __('Person'), reqd: 1,
                      options: people.map(p => p.value), default: people[0].value },
                    { fieldname: 'reason', fieldtype: 'Small Text', label: __('Reason'),
                      default: (frm.doc.nature_of_incident || 'Incident') + ' - ' + frm.doc.name },
                    { fieldname: 'close_with_incident', fieldtype: 'Check', default: 1,
                      label: __('Stop watching when this incident is resolved or closed') },
                    { fieldtype: 'HTML', options: '<p class="text-muted small">' + __('Their visits, attendance, gate movements and vehicle checks will be logged for Security Heads only. Guards are not told.') + '</p>' },
                ],
                primary_action_label: __('Start watching'),
                primary_action: function(values) {
                    frappe.call({
                        method: 'upande_security.api.watchlist.watch_incident_person',
                        args: { incident: frm.doc.name, row_name: values.row_name, reason: values.reason, close_with_incident: values.close_with_incident },
                        callback: function(r) {
                            d.hide();
                            if (!r.message) return;
                            frappe.show_alert({ message: r.message.existing ? __('Already being watched') : __('Now watching'), indicator: 'blue' });
                            frappe.set_route('Form', 'Security Watchlist', r.message.name);
                        },
                    });
                },
            });
            // Show names, not row ids, in the picker.
            d.fields_dict.row_name.$input.find('option').each(function() {
                const p = people.find(x => x.value === this.value);
                if (p) this.textContent = p.label;
            });
            d.show();
        }, __('Investigation'));
    },
});
