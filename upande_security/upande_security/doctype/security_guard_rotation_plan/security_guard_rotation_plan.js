// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("Security Guard Rotation Plan", {
	refresh(frm) {
		set_block_queries(frm);

		// The whitelisted methods run against the saved DB copy of this doc
		// (see run_doc_method), so a dirty/new form has nothing meaningful
		// to generate or apply yet.
		if (frm.is_new() || frm.is_dirty()) {
			return;
		}

		// Off days can be covered whether the plan is still Draft or applied.
		const has_off_days = (frm.doc.preview_rows || []).some((row) => row.is_off_day);
		if (has_off_days && frm.doc.status !== "Cancelled") {
			frm.add_custom_button(__("Fill Off Days"), () => show_fill_off_days(frm));
		}

		if (frm.doc.status !== "Draft") {
			return;
		}

		if (frm.doc.mode === "Automatic") {
			frm.add_custom_button(__("Generate & Apply"), () => {
				frappe.confirm(
					__(
						"Automatic mode has no separate preview step - this generates the full rotation schedule and immediately creates real Shift Assignments for every non-off day. Continue?"
					),
					() => {
						frm.call("generate_and_apply").then((r) => {
							frm.reload_doc();
							if (r.message) {
								const p = r.message.preview;
								const a = r.message.apply;
								report_apply(
									frm,
									__("Generated {0} day(s) ({1} off). Applied {2}, {3} failed.", [
										p.rows,
										p.off_days,
										a.applied,
										a.failed,
									]),
									a.uncovered_off_days
								);
							}
						});
					}
				);
			}).addClass("btn-primary");
			return;
		}

		// Semi-Automatic: preview first, apply as a separate deliberate step
		// so the Security Head can edit a day's farm before committing it.
		frm.add_custom_button(__("Generate Preview"), () => {
			frm.call("generate_preview").then((r) => {
				frm.reload_doc();
				if (r.message) {
					frappe.show_alert({
						message: __("Generated {0} day(s), {1} marked off.", [r.message.rows, r.message.off_days]),
						indicator: "green",
					});
				}
			});
		});

		const has_pending = (frm.doc.preview_rows || []).some((row) => row.status === "Pending");
		if (has_pending) {
			frm.add_custom_button(__("Apply Rotation"), () => {
				frappe.confirm(
					__(
						"This creates real Shift Assignments for every Pending row in the preview below. Off-day rows are skipped. Continue?"
					),
					() => {
						frm.call("apply_rotation").then((r) => {
							frm.reload_doc();
							if (r.message) {
								report_apply(
									frm,
									__("Applied {0}, {1} failed, {2} off-day row(s) skipped.", [
										r.message.applied,
										r.message.failed,
										r.message.skipped,
									]),
									r.message.uncovered_off_days
								);
							}
						});
					}
				);
			}).addClass("btn-primary");
		}
	},
});

// Both rotation_farms and preview_rows pair a farm with an optional block —
// same farm-scopes-block relationship as Security Guard Shift Assignment's
// own set_block_query, just applied per-grid-row instead of to a single
// top-level field.
function set_block_queries(frm) {
	frm.set_query("block", "rotation_farms", (doc, cdt, cdn) => {
		const row = locals[cdt][cdn];
		return { filters: { farm: row.farm || "" } };
	});
	frm.set_query("block", "preview_rows", (doc, cdt, cdn) => {
		const row = locals[cdt][cdn];
		return { filters: { farm: row.farm || "" } };
	});
}

frappe.ui.form.on("Security Guard Rotation Farm", {
	farm(frm, cdt, cdn) {
		// Farm changed — a block picked for the old farm no longer applies.
		frappe.model.set_value(cdt, cdn, "block", null);
	},
});

frappe.ui.form.on("Security Guard Rotation Preview Row", {
	farm(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "block", null);
	},
	is_off_day(frm, cdt, cdn) {
		// Checking/unchecking this box is a real, immediate action - not
		// just editing a field to save later. It cancels or creates the
		// actual Shift Assignment for this guard/date right now (same
		// underlying call as the Shift Schedule grid's own off-day
		// checkbox), whether this plan is Draft or already Applied. Marking
		// a day off first asks who covers it (see pick_cover).
		//
		// A plain frappe.call on purpose, not frm.call - frm.call runs
		// Document methods through run_doc_method, which syncs the WHOLE
		// doc (every preview row) back from the server on every response,
		// visibly repainting the entire table for a single-row edit. This
		// only ever touches the one row that changed.
		if (frm.is_new()) return; // nothing real to toggle yet - no saved doc, no guard-scoped rows possible
		const row = locals[cdt][cdn];
		if (row.__reverting_off_day) return;
		const mark_off = row.is_off_day ? 1 : 0;
		const grid_row = frm.fields_dict.preview_rows.grid.grid_rows_by_docname[cdn];

		const revert = () => {
			if (grid_row) grid_row.wrapper.css("opacity", "");
			// Put the checkbox back without running this handler again.
			row.__reverting_off_day = true;
			frappe.model.set_value(cdt, cdn, "is_off_day", mark_off ? 0 : 1).then(() => {
				row.__reverting_off_day = false;
			});
		};

		const toggle = (cover_guard) => {
			if (grid_row) grid_row.wrapper.css("opacity", 0.5);
			const args = { plan_name: frm.doc.name, row_name: cdn, mark_off };
			if (cover_guard !== undefined) args.cover_guard = cover_guard;
			frappe
				.call({
					method: "upande_security.upande_security.doctype.security_guard_rotation_plan.security_guard_rotation_plan.toggle_preview_row_off_day",
					args,
				})
				.then((r) => {
					if (grid_row) grid_row.wrapper.css("opacity", "");
					const res = r.message;
					if (!res) return;
					frappe.model.set_value(cdt, cdn, "status", res.status);
					frappe.model.set_value(cdt, cdn, "cover_guard", res.cover_guard || null);
					frappe.model.set_value(cdt, cdn, "cover_guard_name", res.cover_guard_name || null);
					frappe.show_alert({ message: cover_message(res), indicator: res.state === "on" ? "green" : "blue" });
				})
				.catch(revert);
		};

		if (!mark_off) {
			toggle();
			return;
		}
		pick_cover(frm, row).then((choice) => {
			if (choice === null) revert();
			else toggle(choice);
		});
	},
});

function cover_message(res) {
	if (res.state === "on") return __("Marked back on duty.");
	if (res.state === "off_covered") {
		const who = res.covered_by_name || res.covered_by;
		return res.reason
			? __("Still covered by {0} - {1}", [who, res.reason])
			: __("Off day set - covered by {0}.", [who]);
	}
	if (res.state === "off_unfilled") return __("Off day set without cover - {0}", [res.reason || __("no reliever free")]);
	return __("Off day set without cover.");
}

const RELIEVER_METHOD = "upande_security.api.relievers.suggest_relievers";
const PLAN_METHOD = "upande_security.upande_security.doctype.security_guard_rotation_plan.security_guard_rotation_plan.";

// Asks who covers the guard on this row's day off. Resolves to the picked
// guard, "none" for no cover, or null when the planner cancels.
function pick_cover(frm, row) {
	return new Promise((resolve) => {
		frappe
			.call({
				method: RELIEVER_METHOD,
				args: {
					guard: frm.doc.external_guard,
					date: row.rotation_date,
					farm: row.farm,
					shift_type: row.shift_type || frm.doc.shift_type,
					start_time: row.start_time || frm.doc.start_time,
					end_time: row.end_time || frm.doc.end_time,
					limit: "all",
				},
			})
			.then((r) => {
				const data = r.message;
				let done = false;
				const d = new frappe.ui.Dialog({
					title: __("Who covers {0}?", [frappe.datetime.str_to_user(row.rotation_date)]),
					size: "large",
					fields: [{ fieldtype: "HTML", fieldname: "list" }],
					primary_action_label: __("Mark Off"),
					primary_action() {
						const picked = d.$wrapper.find("input[name=cover-pick]:checked").val();
						done = true;
						d.hide();
						resolve(picked || "none");
					},
				});
				d.onhide = () => {
					if (!done) resolve(null);
				};
				d.fields_dict.list.$wrapper.html(cover_list_html(data));
				wire_cover_search(d.fields_dict.list.$wrapper, data);
				d.show();
			})
			.catch(() => resolve(null));
	});
}

// One guard as a radio row in the single-day picker.
function cover_item_html(s, checked) {
	const esc = frappe.utils.escape_html;
	const tags = [];
	if (s.previous) tags.push(`<span class="indicator-pill green">${__("Covered last {0}", [frappe.datetime.str_to_user(s.previous)])}</span>`);
	if (s.designated) tags.push(`<span class="indicator-pill blue">${__("Reliever")}</span>`);
	if (s.on_off_day) tags.push(`<span class="indicator-pill orange">${__("Own day off")}</span>`);
	if (!s.available) tags.push(`<span class="indicator-pill red">${__("Busy")}</span>`);
	return `<label class="d-flex align-items-start" style="gap:10px;padding:8px 4px;border-bottom:1px solid var(--border-color);margin:0;${
		s.available ? "cursor:pointer" : "opacity:.6"
	}">
		<input type="radio" name="cover-pick" value="${esc(s.guard)}" ${checked ? "checked" : ""} ${s.available ? "" : "disabled"} style="margin-top:4px">
		<span><b>${esc(s.full_name)}</b> <span class="text-muted small">${esc(s.home_farm || "")}</span> ${tags.join(" ")}
		<br><span class="small">${esc(s.available ? s.reason : s.busy_reason)}</span></span>
	</label>`;
}

// The short list (previous relievers, the designated one, the best free
// guard) with the best free one picked, a search over every other
// candidate, and No cover.
function cover_list_html(data) {
	const esc = frappe.utils.escape_html;
	const all = data.suggestions || [];
	const first = all.find((s) => s.available);
	const short = all.filter((s) => s.shortlist);
	const others = all.length - short.length;
	const head = `<p class="text-muted">${esc(
		__("{0} shift at {1}, {2}-{3}. {4} of {5} guards free.", [
			data.shift_type,
			data.farm || "",
			data.start_time,
			data.end_time,
			data.counts.available,
			data.counts.candidates,
		])
	)}</p>`;
	const rows = short.map((s) => cover_item_html(s, first && s.guard === first.guard)).join("");
	const search = others
		? `<div style="padding:10px 4px 4px"><input type="text" class="form-control input-sm cover-search" placeholder="${esc(
				__("Search {0} other guards by name or farm", [others])
		  )}"></div><div class="cover-results"></div>`
		: "";
	const none = `<label class="d-flex align-items-start" style="gap:10px;padding:8px 4px;margin:0;cursor:pointer">
		<input type="radio" name="cover-pick" value="none" ${first ? "" : "checked"} style="margin-top:4px">
		<span><b>${__("No cover")}</b><br><span class="small text-muted">${__("Leave this day off uncovered")}</span></span>
	</label>`;
	return head + `<div style="max-height:420px;overflow-y:auto">${rows}${search}${none}</div>`;
}

function wire_cover_search($wrapper, data) {
	const others = (data.suggestions || []).filter((s) => !s.shortlist);
	$wrapper.on("input", ".cover-search", function () {
		const q = ($(this).val() || "").trim().toLowerCase();
		const hits = q
			? others.filter((s) => (s.full_name + " " + (s.home_farm || "")).toLowerCase().includes(q)).slice(0, 30)
			: [];
		$wrapper
			.find(".cover-results")
			.html(
				hits.map((s) => cover_item_html(s, false)).join("") ||
					(q ? `<p class="small text-muted" style="padding:6px 4px">${__("No guard matches")}</p>` : "")
			);
	});
}

// A searchable list of every free guard for one off day; calls onPick with
// the chosen option.
function search_cover(row, onPick) {
	const esc = frappe.utils.escape_html;
	const free = row.options.filter((o) => o.available);
	const d = new frappe.ui.Dialog({
		title: __("Find a guard for {0}", [frappe.datetime.str_to_user(row.date)]),
		fields: [
			{ fieldtype: "Data", fieldname: "q", label: __("Search by name or farm") },
			{ fieldtype: "HTML", fieldname: "results" },
		],
	});
	const render = () => {
		const q = (d.get_value("q") || "").trim().toLowerCase();
		const hits = free.filter((o) => !q || (o.full_name + " " + (o.home_farm || "")).toLowerCase().includes(q)).slice(0, 40);
		d.fields_dict.results.$wrapper.html(
			hits
				.map(
					(o) => `<div class="cover-hit" data-guard="${esc(o.guard)}" style="padding:8px 4px;border-bottom:1px solid var(--border-color);cursor:pointer">
						<b>${esc(o.full_name)}</b> <span class="text-muted small">${esc(o.home_farm || "")}</span>
						${o.on_off_day ? `<span class="indicator-pill orange">${__("Own day off")}</span>` : ""}
						<br><span class="small">${esc(o.reason || "")}</span></div>`
				)
				.join("") || `<p class="small text-muted">${__("No free guard matches")}</p>`
		);
	};
	d.fields_dict.q.$input.on("input", render);
	d.fields_dict.results.$wrapper.on("click", ".cover-hit", function () {
		const o = free.find((x) => x.guard === $(this).attr("data-guard"));
		d.hide();
		onPick(o);
	});
	render();
	d.show();
	setTimeout(() => d.fields_dict.q.$input.focus(), 200);
}

function cover_option_label(o, row) {
	return (
		o.full_name +
		(o.guard === row.current_cover ? " - " + __("current") : "") +
		(o.previous ? " - " + __("covered last {0}", [frappe.datetime.str_to_user(o.previous)]) : "") +
		(o.designated ? " - " + __("reliever") : "") +
		(o.on_off_day ? " - " + __("own day off") : "")
	);
}

function report_apply(frm, message, uncovered) {
	if (!uncovered || !uncovered.length) {
		frappe.msgprint(message);
		return;
	}
	const days = uncovered.map((u) => frappe.datetime.str_to_user(u.date)).join(", ");
	const d = frappe.msgprint({
		title: __("Off days without cover"),
		message: `${frappe.utils.escape_html(message)}<br><br>${__("{0} off day(s) have no cover: {1}", [
			uncovered.length,
			frappe.utils.escape_html(days),
		])}`,
		primary_action: {
			label: __("Fill Off Days"),
			action() {
				d.hide();
				show_fill_off_days(frm);
			},
		},
	});
}

// One dialog for every off day on the plan: a pre-picked reliever per day
// (never the same guard on two overlapping covers), confirmed in one call.
function show_fill_off_days(frm) {
	frappe
		.call({ method: PLAN_METHOD + "get_off_day_cover_options", args: { plan_name: frm.doc.name }, freeze: true })
		.then((r) => {
			const data = r.message;
			if (!data || !data.rows.length) {
				frappe.msgprint(__("This plan has no off days."));
				return;
			}
			const esc = frappe.utils.escape_html;
			const by_row = {};
			const option_html = (o, row) =>
				`<option value="${esc(o.guard)}" title="${esc(o.reason || "")}" ${o.guard === row.selected ? "selected" : ""}>${esc(
					cover_option_label(o, row)
				)}</option>`;
			const body = data.rows
				.map((row) => {
					by_row[row.row] = row;
					const short = row.options.filter((o) => o.shortlist);
					const more = row.options.filter((o) => o.available && !o.shortlist).length;
					const opts =
						short.map((o) => option_html(o, row)).join("") +
						(more ? `<option value="__search">${esc(__("Search {0} other guards...", [more]))}</option>` : "");
					const reason = (row.options.find((o) => o.guard === row.selected) || {}).reason || __("Nobody free for this shift");
					return `<tr data-row="${esc(row.row)}">
						<td style="white-space:nowrap">${esc(frappe.datetime.str_to_user(row.date))}</td>
						<td>${esc(row.farm || "")}<br><span class="small text-muted">${esc(row.shift_type || "")} ${esc(row.times)}</span></td>
						<td><select class="form-control input-sm cover-select">
							<option value="" ${row.selected ? "" : "selected"}>${__("No cover")}</option>${opts}
						</select><div class="small text-muted cover-reason" style="margin-top:4px">${esc(reason)}</div></td>
					</tr>`;
				})
				.join("");
			const d = new frappe.ui.Dialog({
				title: __("Fill Off Days"),
				size: "large",
				fields: [{ fieldtype: "HTML", fieldname: "table" }],
				primary_action_label: __("Create Covers"),
				primary_action() {
					const choices = {};
					d.$wrapper.find("tr[data-row]").each(function () {
						choices[$(this).attr("data-row")] = $(this).find(".cover-select").val() || "none";
					});
					d.hide();
					frappe
						.call({ method: PLAN_METHOD + "fill_off_day_covers", args: { plan_name: frm.doc.name, choices }, freeze: true })
						.then((res) => {
							frm.reload_doc();
							const out = res.message || { covered: [], uncovered: [] };
							let msg = __("{0} off day(s) covered.", [out.covered.length]);
							if (out.uncovered.length) {
								msg +=
									"<br><br>" +
									__("Without cover:") +
									"<ul>" +
									out.uncovered
										.map(
											(u) =>
												`<li>${esc(frappe.datetime.str_to_user(u.date))}: ${esc(u.reason)}${
													u.still_covered_by ? " (" + esc(__("still covered by {0}", [u.still_covered_by])) + ")" : ""
												}</li>`
										)
										.join("") +
									"</ul>";
							}
							frappe.msgprint({ title: __("Off Day Cover"), message: msg });
						});
				},
			});
			d.fields_dict.table.$wrapper.html(
				`<p class="text-muted">${__("Each off day has its previous reliever picked when they are free, else the best free guard. Change any of them, search for someone else, or pick No cover.")}</p>
				<table class="table table-bordered"><thead><tr><th>${__("Date")}</th><th>${__("Farm / Shift")}</th><th>${__("Cover")}</th></tr></thead><tbody>${body}</tbody></table>`
			);
			const show_reason = ($select) => {
				$select.closest("td").find(".cover-reason").text($select.find("option:selected").attr("title") || "");
				$select.data("prev", $select.val());
			};
			d.$wrapper.find(".cover-select").each(function () {
				$(this).data("prev", $(this).val());
			});
			d.$wrapper.on("change", ".cover-select", function () {
				const $select = $(this);
				if ($select.val() !== "__search") {
					show_reason($select);
					return;
				}
				// Back to the last pick until a guard is chosen in the search.
				$select.val($select.data("prev") || "");
				const row = by_row[$select.closest("tr").attr("data-row")];
				search_cover(row, (o) => {
					if (!$select.find(`option[value="${CSS.escape(o.guard)}"]`).length) {
						$select.find('option[value="__search"]').before(option_html(o, row));
					}
					$select.val(o.guard);
					show_reason($select);
				});
			});
			d.show();
		});
}

// Shift times come from Security Ops Settings > Standard Shift Times, never
// typed by hand. A rotating plan's own shift is the first in its sequence.
frappe.ui.form.on("Security Guard Rotation Plan", {
	shift_type(frm) {
		fill_standard_times(frm);
	},
	rotate_shifts(frm) {
		follow_first_shift(frm);
	},
});

frappe.ui.form.on("Security Guard Rotation Shift", {
	shift_type(frm) {
		follow_first_shift(frm);
	},
	shift_sequence_remove(frm) {
		follow_first_shift(frm);
	},
});

function follow_first_shift(frm) {
	if (!frm.doc.rotate_shifts) return;
	const first = (frm.doc.shift_sequence || []).find((row) => row.shift_type);
	if (first && first.shift_type !== frm.doc.shift_type) frm.set_value("shift_type", first.shift_type);
}

function fill_standard_times(frm) {
	if (!frm.doc.shift_type) return;
	frappe
		.call("upande_security.api.shift_times.get_standard_shift_times", { shift_type: frm.doc.shift_type })
		.then((r) => {
			const t = r.message;
			if (t && t.start_time && t.end_time) {
				frm.set_value("start_time", t.start_time);
				frm.set_value("end_time", t.end_time);
			}
		});
}
