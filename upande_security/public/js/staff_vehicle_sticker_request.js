// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

/**
 * Staff Vehicle Sticker Request review actions.
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
 * This doctype was built in the Desk (DocType.custom = 1) and ships via
 * the doctype.json fixture, so it has no app folder to hold a controller
 * file. Wired via `doctype_js`.
 */

// ---- was Client Script: staff vehicle sticker request approve reject ----
frappe.ui.form.on('Staff Vehicle Sticker Request', {
	refresh(frm) {
		if (frm.doc.status !== 'Pending' || frm.is_new()) {
			return;
		}

		frm.add_custom_button('Approve — Create Sticker', () => {
			frappe.confirm(
				'Create a Staff Vehicle Sticker for ' + (frm.doc.employee_name || frm.doc.employee) + '?',
				() => {
					frappe.call({
						method: 'approve_staff_sticker_request',
						args: { request_name: frm.doc.name },
						freeze: true,
						freeze_message: __('Creating sticker...'),
						callback: (r) => {
							if (r.message && r.message.error) {
								frappe.msgprint({
									title: __('Could not approve'),
									message: r.message.error,
									indicator: 'red',
								});
							} else if (r.message && r.message.success) {
								frappe.msgprint({
									title: __('Sticker created'),
									message:
										'Staff Vehicle Sticker <b>' +
										r.message.sticker +
										'</b> created and linked. Its QR code needs a manual backfill until the next deploy — ask for that to be run, or print the badge once it has one.',
									indicator: 'green',
								});
								frm.reload_doc();
							}
						},
					});
				}
			);
		}, __('Actions')).addClass('btn-primary');

		frm.add_custom_button('Reject', () => {
			frappe.prompt(
				[{ fieldname: 'review_notes', label: __('Reason (optional)'), fieldtype: 'Small Text' }],
				(values) => {
					frappe.call({
						method: 'reject_staff_sticker_request',
						args: { request_name: frm.doc.name, review_notes: values.review_notes },
						freeze: true,
						callback: (r) => {
							if (r.message && r.message.error) {
								frappe.msgprint({
									title: __('Could not reject'),
									message: r.message.error,
									indicator: 'red',
								});
							} else {
								frm.reload_doc();
							}
						},
					});
				},
				__('Reject Request'),
				__('Reject')
			);
		}, __('Actions'));
	},
});

// ---- was Client Script: staff vehicle sticker request gate picker ----
// Collection Point is a Select field whose options depend on which farm was
// picked as Collection Farm — driven from the same Security Gate Config
// rows (Security Ops Settings > Farm Gates) the rest of this app already
// uses for gate configuration, so there's one source of truth for "what
// gates does this farm have" rather than free-typed values drifting from
// whatever's actually configured.
//
// A Select field can't fall back to free text, so a farm with zero active
// gates configured still gets exactly one option ("Main Gate") instead of
// leaving the field with nothing pickable - a required field must never be
// unfillable just because nobody's configured that farm's gates yet.
//
// Goes through list_active_gates_for_farm (a whitelisted server method),
// not a direct frappe.db.get_list("Security Gate Config", ...) — that child
// table has an empty permissions array (relies on its parent Security Ops
// Settings' DocPerm when viewed through that form), so a direct query
// throws "Insufficient Permission" for any real user. Only worked in
// testing because that was done as Administrator, who bypasses permission
// checks entirely.
frappe.ui.form.on("Staff Vehicle Sticker Request", {
	collection_farm(frm) {
		frm.set_value("collection_point", "");
		if (!frm.doc.collection_farm) {
			frm.set_df_property("collection_point", "options", []);
			frm.refresh_field("collection_point");
			return;
		}

		frappe.call({
			method: "list_active_gates_for_farm",
			args: { farm: frm.doc.collection_farm },
		}).then((r) => {
			const names = ((r.message && r.message.gates) || []).filter(Boolean);
			const options = names.length ? names : ["Main Gate"];
			frm.set_df_property("collection_point", "options", options);
			frm.refresh_field("collection_point");
			if (options.length === 1) {
				frm.set_value("collection_point", options[0]);
			}
		});
	},
});

