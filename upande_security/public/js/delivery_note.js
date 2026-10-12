// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

/**
 * Security check tab on Delivery Note.
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
 * Delivery Note belongs to ERPNext. Wired via `doctype_js`, which merges
 * with ERPNext's own Delivery Note JS rather than overriding it.
 */

// ---- was Client Script: delivery note security check tab ----
// Read-only "Security Check" tab for Delivery Note. Never writes anything
// back to Delivery Note's own record — this only renders whatever the
// gate already recorded in Gate Dispatch Verification (the sole owner of
// that data), same "read-only against the source" principle documented
// at the top of upande_security/api/gate_dispatch.py, just mirrored: here
// Delivery Note is the one reading, not the one being read.
frappe.ui.form.on('Delivery Note', {
	refresh: function (frm) {
		if (frm.is_new()) {
			return;
		}
		frm.set_df_property('security_check_tab', 'hidden', 1);
		frappe.call({
			method: 'upande_security.api.gate_dispatch.get_gate_dispatch_verification_summary',
			args: {
				reference_doctype: 'Delivery Note',
				reference_name: frm.doc.name,
			},
			callback: function (r) {
				var summary = r.message;
				if (!summary) {
					return;
				}
				frm.set_df_property('security_check_tab', 'hidden', 0);
				frm.set_df_property('security_check_html', 'options', render_security_check(summary));
				frm.refresh_field('security_check_html');
			},
		});
	},
});

function render_security_check(summary) {
	var status = summary.gate_verification_status || 'Not Checked';
	var status_color = status === 'Verified' ? 'green' : 'red';
	var guard = frappe.utils.escape_html(summary.gate_verified_by_name || summary.gate_verified_by || '');
	var exit_time = summary.gate_exit_time ? frappe.datetime.str_to_user(summary.gate_exit_time) : '';

	var html = '<div class="security-check-summary">';
	html += '<div style="margin-bottom: 10px;">';
	html += '<span class="indicator-pill ' + status_color + '">' + frappe.utils.escape_html(status) + '</span>';
	html += ' &nbsp; <b>' + __('Verified By') + ':</b> ' + guard;
	if (exit_time) {
		html += ' &nbsp; <b>' + __('Gate Exit Time') + ':</b> ' + exit_time;
	}
	html += '</div>';

	if (status === 'Rejected' && summary.remarks) {
		html += '<div style="margin-bottom: 10px; color: #c0392b;">';
		html += '<b>' + __('Remarks') + ':</b> ' + frappe.utils.escape_html(summary.remarks);
		html += '</div>';
	}

	var checks = summary.item_checks || [];
	if (checks.length) {
		html += '<table class="table table-bordered" style="margin-top: 6px;">';
		html += '<thead><tr>';
		html += '<th>' + __('Item Code') + '</th>';
		html += '<th>' + __('Item Name') + '</th>';
		html += '<th>' + __('UOM') + '</th>';
		html += '<th>' + __('Expected Qty') + '</th>';
		html += '<th>' + __('Actual Qty') + '</th>';
		html += '<th>' + __('Match Status') + '</th>';
		html += '</tr></thead><tbody>';
		checks.forEach(function (row) {
			html += '<tr>';
			html += '<td>' + frappe.utils.escape_html(row.item_code || '') + '</td>';
			html += '<td>' + frappe.utils.escape_html(row.item_name || '') + '</td>';
			html += '<td>' + frappe.utils.escape_html(row.uom || '') + '</td>';
			html += '<td>' + (row.expected_qty != null ? row.expected_qty : '') + '</td>';
			html += '<td>' + (row.actual_qty != null ? row.actual_qty : '') + '</td>';
			html += '<td><span class="indicator-pill ' + match_status_color(row.match_status) + '">' +
				frappe.utils.escape_html(row.match_status || 'Not Checked') + '</span></td>';
			html += '</tr>';
		});
		html += '</tbody></table>';
	}

	html += '</div>';
	return html;
}

function match_status_color(match_status) {
	if (match_status === 'Matches') {
		return 'green';
	}
	if (match_status === 'Short' || match_status === 'Over') {
		return match_status === 'Short' ? 'orange' : 'red';
	}
	return 'grey';
}

