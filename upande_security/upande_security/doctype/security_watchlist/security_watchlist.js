// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

// Shows the watched person's transactions (Watchlist Activity) on the entry
// itself, newest first, with the time of each check-in, check-out, gate
// movement, vehicle check and incident.
frappe.ui.form.on('Security Watchlist', {
    refresh(frm) {
        const wrapper = frm.fields_dict.transactions_html && frm.fields_dict.transactions_html.$wrapper;
        if (!wrapper) return;
        if (frm.is_new()) {
            wrapper.html('');
            return;
        }
        wrapper.html('<p class="text-muted small">' + __('Loading transactions...') + '</p>');
        frappe.db.get_list('Watchlist Activity', {
            filters: { watchlist: frm.doc.name },
            fields: ['name', 'occurred_at', 'activity_type', 'farm', 'gate', 'reference_doctype',
                     'reference_name', 'handled_by', 'matched_on', 'details'],
            order_by: 'occurred_at desc',
            limit: 500,
        }).then((rows) => {
            if (!rows.length) {
                wrapper.html('<p class="text-muted small">' + __('No transactions logged yet.') + '</p>');
                return;
            }
            const esc = frappe.utils.escape_html;
            const body = rows.map((r) => `
                <tr>
                    <td style="white-space:nowrap">${esc(frappe.datetime.str_to_user(r.occurred_at) || '')}</td>
                    <td><a href="/app/watchlist-activity/${encodeURIComponent(r.name)}">${esc(r.activity_type || '')}</a></td>
                    <td>${esc(r.farm || '')}${r.gate ? ' <span class="text-muted">· ' + esc(r.gate) + '</span>' : ''}</td>
                    <td>${r.reference_name ? `<a href="/app/${frappe.router.slug(r.reference_doctype)}/${encodeURIComponent(r.reference_name)}">${esc(r.reference_doctype)} ${esc(r.reference_name)}</a>` : ''}</td>
                    <td>${esc(r.details || '')}</td>
                    <td>${esc(r.handled_by || '')}</td>
                    <td class="text-muted">${esc(r.matched_on || '')}</td>
                </tr>`).join('');
            wrapper.html(`
                <div class="table-responsive">
                <table class="table table-bordered table-sm" style="font-size:12px;margin:0">
                    <thead><tr>
                        <th>${__('When')}</th><th>${__('Activity')}</th><th>${__('Farm · Gate')}</th>
                        <th>${__('Record')}</th><th>${__('Details')}</th><th>${__('Handled By')}</th><th>${__('Matched On')}</th>
                    </tr></thead>
                    <tbody>${body}</tbody>
                </table>
                </div>`);
        });
    },
});
