const ADMIN_API = "upande_security.cctv.admin";

frappe.ui.form.on("CCTV Site Agent", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("New signing secret"), () =>
			frappe.confirm(__("Make a new signing secret? The agent stops being accepted until the new one is on the site box."), () =>
				frappe.xcall(`${ADMIN_API}.generate_agent_secret`, { agent: frm.doc.name }).then((r) => {
					frappe.msgprint({
						title: __("Signing secret - shown once"),
						message: `<p>${__("Save this as <code>secrets/agent_hmac</code> on the site box:")}</p><pre style="user-select:all">${frappe.utils.escape_html(r.secret)}</pre>`,
					});
					frm.reload_doc();
				})), __("Setup"));
		frm.add_custom_button(__("Agent config file"), () =>
			frappe.xcall(`${ADMIN_API}.agent_config`, { agent: frm.doc.name }).then((r) => {
				frappe.msgprint({
					title: __("agent.yml for {0}", [frm.doc.name]),
					wide: true,
					message: `<p>${__("Put this next to docker-compose.yml on the site box. The API key/secret of {0} (CCTV Agent role only) go in <code>secrets/</code>.", [r.api_user || __("the agent's API user")])}</p><pre style="user-select:all">${frappe.utils.escape_html(r.yaml)}</pre>`,
				});
			}), __("Setup"));
		frm.add_custom_button(__("Camera health"), () => window.open("/security-dashboard-v2#/cctv-health", "_blank"));
	},
});
