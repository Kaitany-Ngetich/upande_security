frappe.pages["security-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Security Command Centre"),
		single_column: true,
	});

	wrapper.security_dashboard_page = page;

	setup_filters(page);
	render_dashboard(page);
	render_security_sidebar(page);
	bind_security_view_navigation(page);
	bind_dashboard_events(page);

	render_clean_security_overview(page);
	update_dashboard_time(page);

	page.set_primary_action(
		__("Refresh"),
		() => {
			update_dashboard_time(page);

			frappe.show_alert({
				message: __("Security dashboard refreshed"),
				indicator: "green",
			});
		},
		"refresh"
	);
};

frappe.pages["security-dashboard"].on_page_show = function (wrapper) {
	if (wrapper.security_dashboard_page) {
		update_dashboard_time(wrapper.security_dashboard_page);
	}
};

function setup_filters(page) {
	page.add_field({
		label: __("Company"),
		fieldname: "company",
		fieldtype: "Link",
		options: "Company",
		default: frappe.defaults.get_default("company"),
		change: () => update_dashboard_time(page),
	});

	page.add_field({
		label: __("Site / Farm"),
		fieldname: "site",
		fieldtype: "Select",
		options: [
			__("All Sites"),
			__("Karen Roses"),
			__("Kisumu Farm"),
		],
		default: __("All Sites"),
		change: () => update_dashboard_time(page),
	});

	page.add_field({
		label: __("Gate"),
		fieldname: "gate",
		fieldtype: "Select",
		options: [
			__("All Gates"),
			__("Main Gate"),
			__("North Gate"),
			__("Service Gate"),
		],
		default: __("All Gates"),
	});

	page.add_field({
		label: __("Shift"),
		fieldname: "shift",
		fieldtype: "Select",
		options: [
			__("Day Shift"),
			__("Night Shift"),
			__("All Shifts"),
		],
		default: __("Day Shift"),
	});

	page.add_field({
		label: __("Date"),
		fieldname: "date",
		fieldtype: "Date",
		default: frappe.datetime.get_today(),
	});
}

function render_dashboard(page) {
	$(page.main).html(`
		<div class="security-command-centre">

			<section class="sd-intro">
				<div>
					<h2>${__("Security Command Centre")}</h2>
					<p>
						${__(
							"Real-time overview of security operations and site activity"
						)}
					</p>
				</div>

				<div class="sd-live-status">
					<span class="sd-live-dot"></span>
					<span>${__("Auto-refresh")}: 30s</span>
					<span class="sd-updated-time"></span>
				</div>
			</section>

			<section class="sd-kpi-grid">
				${make_kpi_card(
					"🛡",
					__("Guards On Duty"),
					"48",
					__("52 scheduled"),
					"blue",
					"Security Guard"
				)}

				${make_kpi_card(
					"♟",
					__("Visitors On Site"),
					"23",
					__("Currently checked in"),
					"green",
					"Appointment"
				)}

				${make_kpi_card(
					"▣",
					__("Contractors On Site"),
					"17",
					__("Approved entries"),
					"purple",
					"Contractor"
				)}

				${make_kpi_card(
					"🚙",
					__("Vehicles On Site"),
					"31",
					__("Inside the perimeter"),
					"blue",
					"Appointment"
				)}

				${make_kpi_card(
					"!",
					__("Open Incidents"),
					"6",
					__("Require attention"),
					"red",
					"Incident"
				)}

				${make_kpi_card(
					"✓",
					__("Patrol Compliance"),
					"86%",
					__("Today's completion"),
					"green",
					"Patrol GPS Log"
				)}
			</section>

			<section class="sd-main-grid">

				<div class="sd-panel sd-map-panel">
					<div class="sd-panel-header">
						<div>
							<h3>${__("Live Site Map")}</h3>
							<p>${__(
								"Gates, checkpoints, guards and patrol routes"
							)}</p>
						</div>

						<button
							type="button"
							class="btn btn-sm btn-default"
							data-page-route="patrol-map"
						>
							${__("Open Full Map")}
						</button>
					</div>

					<div class="sd-map">
						<div class="sd-map-road sd-road-one"></div>
						<div class="sd-map-road sd-road-two"></div>

						<div class="sd-map-marker sd-gate-a">
							<strong>Gate A</strong>
							<span>Main Entrance</span>
						</div>

						<div class="sd-map-marker sd-gate-b">
							<strong>Gate B</strong>
							<span>North Gate</span>
						</div>

						<div class="sd-map-marker sd-checkpoint-one">
							<strong>Checkpoint</strong>
							<span>North Perimeter</span>
						</div>

						<div class="sd-map-marker sd-checkpoint-two">
							<strong>Checkpoint</strong>
							<span>Central Zone</span>
						</div>

						<div class="sd-restricted-zone">
							<strong>${__("Restricted Area")}</strong>
							<span>${__("Authorised access only")}</span>
						</div>

						<div class="sd-map-footer">
							<span class="sd-live-dot"></span>
							${__("Map awaiting live GPS integration")}
						</div>
					</div>
				</div>

				<div class="sd-panel">
					<div class="sd-panel-header">
						<div>
							<h3>${__("Live Alerts")}</h3>
							<p>${__("Items needing immediate attention")}</p>
						</div>

						<button
							type="button"
							class="btn btn-sm btn-default"
							data-doctype="Incident"
						>
							${__("View All")}
						</button>
					</div>

					<div class="sd-alert-list">
						${make_alert(
							__("Missed Patrol – North Perimeter"),
							__("Checkpoint NP-04"),
							"10:18",
							__("High"),
							"high"
						)}

						${make_alert(
							__("Visitor Overstayed"),
							"John Kamau",
							"10:12",
							__("Medium"),
							"medium"
						)}

						${make_alert(
							__("Contractor Approval Pending"),
							"BuildCo – 3 persons",
							"09:58",
							__("Medium"),
							"medium"
						)}

						${make_alert(
							__("Vehicle Awaiting Verification"),
							"KDL 123A",
							"09:45",
							__("Low"),
							"low"
						)}
					</div>
				</div>

				<div class="sd-panel">
					<div class="sd-panel-header">
						<div>
							<h3>${__("Patrol Performance")}</h3>
							<p>${__("Completed, late and missed patrols")}</p>
						</div>
					</div>

					<div class="sd-patrol-chart">
						${make_bar(36, 8, 4, "00:00")}
						${make_bar(45, 12, 6, "04:00")}
						${make_bar(73, 15, 7, "08:00")}
						${make_bar(62, 18, 9, "12:00")}
						${make_bar(82, 11, 5, "16:00")}
						${make_bar(67, 17, 8, "20:00")}
					</div>

					<div class="sd-chart-legend">
						<span><i class="sd-legend-completed"></i>${__("Completed")}</span>
						<span><i class="sd-legend-late"></i>${__("Late")}</span>
						<span><i class="sd-legend-missed"></i>${__("Missed")}</span>
					</div>

					<div class="sd-patrol-summary">
						<div><strong>86</strong><span>${__("Completed")}</span></div>
						<div><strong>16</strong><span>${__("Late")}</span></div>
						<div><strong>12</strong><span>${__("Missed")}</span></div>
						<div class="sd-compliance-ring">86%</div>
					</div>
				</div>

			</section>

			<section class="sd-bottom-grid">

				<div class="sd-panel">
					<div class="sd-panel-header">
						<div>
							<h3>${__("Current Site Occupancy")}</h3>
							<p>${__("People and vehicles currently inside")}</p>
						</div>
					</div>

					<div class="sd-occupancy">
						<div class="sd-donut">
							<div>
								<strong>119</strong>
								<span>${__("Total On Site")}</span>
							</div>
						</div>

						<div class="sd-occupancy-list">
							<div><i class="sd-dot-blue"></i><span>${__("Employees")}</span><strong>64</strong></div>
							<div><i class="sd-dot-green"></i><span>${__("Visitors")}</span><strong>23</strong></div>
							<div><i class="sd-dot-purple"></i><span>${__("Contractors")}</span><strong>17</strong></div>
							<div><i class="sd-dot-orange"></i><span>${__("Vehicles")}</span><strong>15</strong></div>
						</div>
					</div>
				</div>

				<div class="sd-panel sd-actions-panel">
					<div class="sd-panel-header">
						<div>
							<h3>${__("Items Requiring Action")}</h3>
							<p>${__("Pending security decisions")}</p>
						</div>
					</div>

					<div class="sd-table-wrapper">
						<table class="table table-hover sd-actions-table">
							<thead>
								<tr>
									<th>${__("Priority")}</th>
									<th>${__("Type")}</th>
									<th>${__("Name / Vehicle")}</th>
									<th>${__("Location")}</th>
									<th>${__("Status")}</th>
									<th>${__("Action")}</th>
								</tr>
							</thead>

							<tbody>
								${make_action_row(
									__("High"),
									__("Incident"),
									__("Unauthorised Access"),
									__("North Fence"),
									__("Open"),
									__("Resolve"),
									"high",
									"Incident"
								)}

								${make_action_row(
									__("Medium"),
									__("Visitor"),
									"John Kamau",
									__("Reception"),
									__("Overstayed"),
									__("Check Out"),
									"medium",
									"Appointment"
								)}

								${make_action_row(
									__("Medium"),
									__("Contractor"),
									"BuildCo – 3 persons",
									__("Gate B"),
									__("Pending Approval"),
									__("Approve"),
									"medium",
									"Contractor"
								)}

								${make_action_row(
									__("Low"),
									__("Vehicle"),
									"KDL 123A",
									__("Main Gate"),
									__("Verification"),
									__("Verify"),
									"low",
									"Appointment"
								)}
							</tbody>
						</table>
					</div>
				</div>

				<div class="sd-panel">
					<div class="sd-panel-header">
						<div>
							<h3>${__("Recent Security Activity")}</h3>
							<p>${__("Latest site events")}</p>
						</div>
					</div>

					<div class="sd-activity-list">
						${make_activity("10:24", __("Patrol completed"), __("South Perimeter"))}
						${make_activity("10:18", __("Missed patrol detected"), __("North Perimeter"))}
						${make_activity("10:12", __("Visitor checked in"), "John Kamau")}
						${make_activity("09:58", __("Contractor approval requested"), "BuildCo")}
						${make_activity("09:45", __("Vehicle entered site"), "KDL 123A")}
					</div>
				</div>

			</section>
		</div>
	`);
}

function make_kpi_card(icon, label, value, subtitle, colour, doctype) {
	return `
		<button type="button" class="sd-kpi-card" data-doctype="${doctype}">
			<span class="sd-kpi-icon sd-icon-${colour}">${icon}</span>

			<span class="sd-kpi-body">
				<span class="sd-kpi-label">${label}</span>
				<strong>${value}</strong>
				<small>${subtitle}</small>
			</span>
		</button>
	`;
}

function make_alert(title, description, time, priority, level) {
	return `
		<div class="sd-alert sd-alert-${level}">
			<div>
				<strong>${title}</strong>
				<span>${description}</span>
			</div>

			<div class="sd-alert-meta">
				<time>${time}</time>
				<span>${priority}</span>
			</div>
		</div>
	`;
}

function make_bar(completed, late, missed, label) {
	return `
		<div class="sd-bar-column">
			<div class="sd-bar-stack">
				<div class="sd-bar-missed" style="height:${missed}%"></div>
				<div class="sd-bar-late" style="height:${late}%"></div>
				<div class="sd-bar-completed" style="height:${completed}%"></div>
			</div>
			<span>${label}</span>
		</div>
	`;
}

function make_action_row(
	priority,
	type,
	name,
	location,
	status,
	action,
	level,
	doctype
) {
	return `
		<tr>
			<td><span class="sd-badge sd-badge-${level}">${priority}</span></td>
			<td>${type}</td>
			<td><strong>${name}</strong></td>
			<td>${location}</td>
			<td><span class="sd-status">${status}</span></td>
			<td>
				<button
					type="button"
					class="btn btn-xs btn-default"
					data-doctype="${doctype}"
				>
					${action}
				</button>
			</td>
		</tr>
	`;
}

function make_activity(time, title, description) {
	return `
		<div class="sd-activity">
			<time>${time}</time>
			<i></i>
			<div>
				<strong>${title}</strong>
				<span>${description}</span>
			</div>
		</div>
	`;
}

function bind_dashboard_events(page) {
	const $main = $(page.main);

	$main.off(".security-dashboard");

	$main.on(
		"click.security-dashboard",
		"[data-doctype]",
		function () {
			const doctype = $(this).attr("data-doctype");

			if (doctype) {
				frappe.set_route("List", doctype);
			}
		}
	);

	$main.on(
		"click.security-dashboard",
		"[data-page-route]",
		function () {
			const route = $(this).attr("data-page-route");

			if (route) {
				frappe.set_route(route);
			}
		}
	);
}

function update_dashboard_time(page) {
	const currentTime = new Date().toLocaleTimeString([], {
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	});

	$(page.main)
		.find(".sd-updated-time")
		.text(`${__("Updated")} ${currentTime}`);
}

function render_security_sidebar(page) {
	const $root = $(page.main);
	const $dashboard = $root.find(".security-command-centre");

	if (!$dashboard.length) {
		console.warn("Security dashboard content was not found.");
		return;
	}

	if ($root.find(".security-app-sidebar").length) {
		return;
	}

	$dashboard.attr("id", "security-overview");

	$dashboard.wrap(
		'<main class="security-app-content"></main>'
	);

	$root
		.find(".security-app-content")
		.wrap('<div class="security-app-layout"></div>');

	$root.find(".security-app-layout").prepend(`
		<aside class="security-app-sidebar">

			<div class="security-sidebar-brand">
				<div class="security-sidebar-logo">
					<svg
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						width="23"
						height="23"
					>
						<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
					</svg>
				</div>

				<div>
					<strong>${__("Upande Security")}</strong>
					<span>${__("Command Centre")}</span>
				</div>
			</div>

			<nav class="security-sidebar-nav">

				<div class="security-sidebar-section">
					<div class="security-sidebar-heading">
						${__("Main")}
					</div>

					<a
						href="#"
						class="security-sidebar-link active"
						data-security-view="overview"
					>
						<span class="security-sidebar-icon">◔</span>
						<span>${__("Overview")}</span>
					</a>

					<a
						href="#"
						class="security-sidebar-link"
						data-scroll-target="recent-security-activity"
					>
						<span class="security-sidebar-icon">⌁</span>
						<span>${__("Live Activity")}</span>
					</a>
				</div>

				<div class="security-sidebar-section">
					<div class="security-sidebar-heading">
						${__("Access Control")}
					</div>

					<a
                        href="#"
                        class="security-sidebar-link"
                        data-security-view="visitors"
                    >
						<span class="security-sidebar-icon">♙</span>
						<span>${__("Visitors")}</span>
					</a>

					<a
						href="/app/contractor"
						class="security-sidebar-link"
					>
						<span class="security-sidebar-icon">▣</span>
						<span>${__("Contractors")}</span>
					</a>

					<a
						href="/app/vehicle"
						class="security-sidebar-link"
					>
						<span class="security-sidebar-icon">▰</span>
						<span>${__("Vehicles")}</span>
					</a>

					<a
						href="/app/movement-log"
						class="security-sidebar-link"
					>
						<span class="security-sidebar-icon">⇄</span>
						<span>${__("Movement Log")}</span>
					</a>
				</div>

				<div class="security-sidebar-section">
					<div class="security-sidebar-heading">
						${__("Operations")}
					</div>

					<a
						href="/app/security-guard-shift-assignment"
						class="security-sidebar-link"
					>
						<span class="security-sidebar-icon">♜</span>
						<span>${__("Guards & Shifts")}</span>
					</a>

					<a
                        href="#"
                        class="security-sidebar-link"
                        data-security-view="patrols"
                    >
						<span class="security-sidebar-icon">⚑</span>
						<span>${__("Patrols")}</span>
					</a>

					<a
						href="#"
						class="security-sidebar-link"
					 data-security-view="incidents">
						<span class="security-sidebar-icon">⚠</span>
						<span>${__("Incidents")}</span>
					</a>

					<a
						href="/security-patrol-map"
						class="security-sidebar-link"
					>
						<span class="security-sidebar-icon">⌖</span>
						<span>${__("Site Map")}</span>
					</a>
				</div>

				<div class="security-sidebar-section">
					<div class="security-sidebar-heading">
						${__("Reports")}
					</div>

					<a
						href="#"
						class="security-sidebar-link"
						data-coming-soon="Security Reports"
					>
						<span class="security-sidebar-icon">▥</span>
						<span>${__("Security Reports")}</span>
					</a>
				</div>

				<div class="security-sidebar-section">
					<div class="security-sidebar-heading">
						${__("System")}
					</div>

					<a
						href="#"
						class="security-sidebar-link"
						data-coming-soon="Security Settings"
					>
						<span class="security-sidebar-icon">⚙</span>
						<span>${__("Settings")}</span>
					</a>
				</div>

			</nav>
		</aside>
	`);

	$root
		.find(".sd-activity-list")
		.closest(".sd-panel")
		.attr("id", "recent-security-activity");

	$root.off("click.securitySidebar");

	$root.on(
		"click.securitySidebar",
		".security-sidebar-link[data-scroll-target]",
		function (event) {
			event.preventDefault();

			const targetId = $(this).attr("data-scroll-target");
			const target = document.getElementById(targetId);

			if (!target) {
				return;
			}

			$root
				.find(".security-sidebar-link")
				.removeClass("active");

			$(this).addClass("active");

			target.scrollIntoView({
				behavior: "smooth",
				block: "start",
			});
		}
	);

	$root.on(
		"click.securitySidebar",
		".security-sidebar-link[data-coming-soon]",
		function (event) {
			event.preventDefault();

			const itemName = $(this).attr("data-coming-soon");

			frappe.show_alert({
				message: __(`${itemName} will be connected next.`),
				indicator: "blue",
			});
		}
	);
}



/* =========================================================
   SECURITY DASHBOARD VIEW NAVIGATION
   ========================================================= */

function bind_security_view_navigation(page) {
	const $root = $(page.main);
	const $content = $root.find(".security-app-content");

	if (!$content.length) {
		console.warn("Security application content area was not found.");
		return;
	}

	if (!page.security_overview_html) {
		page.security_overview_html = $content.html();
	}

	page.security_current_view = "overview";

	$root.off("click.securityViews");

	$root.on(
		"click.securityViews",
		"[data-security-view]",
		function (event) {
			event.preventDefault();

			const view = $(this).attr("data-security-view");

			show_security_view(page, view);
		}
	);
}


function show_security_view(page, view) {
	const $root = $(page.main);
	const $content = $root.find(".security-app-content");

	$root
		.find(".security-sidebar-link")
		.removeClass("active");

	$root
		.find(
			`.security-sidebar-link[data-security-view="${view}"]`
		)
		.addClass("active");

	page.security_current_view = view;

	$root.off(".securityVisitors");
        $root.off(".securityPatrols");

        if (page.security_patrol_refresh_timer) {
                window.clearInterval(
                        page.security_patrol_refresh_timer
                );
                page.security_patrol_refresh_timer = null;
        }

	if (view === "visitors") {
		render_visitors_view(page);
		return;
	}

        if (view === "patrols") {
                render_patrols_view(page);
                return;
        }

        if (view === "incidents") {
                render_incidents_view(page);
                return;
        }



	$content.html(page.security_overview_html);

	bind_dashboard_events(page);
	update_dashboard_time(page);

	window.scrollTo({
		top: 0,
		behavior: "smooth",
	});
}


/* =========================================================
   VISITORS VIEW
   ========================================================= */

function render_visitors_view(page) {
	const $root = $(page.main);
	const $content = $root.find(".security-app-content");

	$content.html(`
		<div class="security-visitors-view">

			<div class="sv-page-heading">
				<div>
					<h2>${__("Visitors")}</h2>
					<p>${__("Security")} › ${__("Visitor Log")}</p>
				</div>

				<div class="sv-heading-actions">
					<button
						type="button"
						class="btn btn-default"
						id="sv-refresh"
					>
						${__("Refresh")}
					</button>

					<button
						type="button"
						class="btn btn-primary"
						id="sv-new-visitor"
					>
						${__("New Visitor")}
					</button>
				</div>
			</div>

			<div class="sv-kpi-grid">

				<div class="sv-kpi-card">
					<div class="sv-kpi-icon sv-blue">♟</div>
					<div>
						<strong id="sv-total">—</strong>
						<span>${__("Total")}</span>
					</div>
				</div>

				<div class="sv-kpi-card">
					<div class="sv-kpi-icon sv-green">↪</div>
					<div>
						<strong id="sv-checked-in">—</strong>
						<span>${__("Checked in")}</span>
					</div>
				</div>

				<div class="sv-kpi-card">
					<div class="sv-kpi-icon sv-slate">↩</div>
					<div>
						<strong id="sv-checked-out">—</strong>
						<span>${__("Checked out")}</span>
					</div>
				</div>

				<div class="sv-kpi-card">
					<div class="sv-kpi-icon sv-light-blue">◷</div>
					<div>
						<strong id="sv-scheduled">—</strong>
						<span>${__("Scheduled")}</span>
					</div>
				</div>

			</div>

			<div class="sv-list-panel">

				<div class="sv-filter-bar">

					<select
						id="sv-status-filter"
						class="form-control"
					>
						<option value="">
							${__("All statuses")}
						</option>
					</select>

					<select
						id="sv-transport-filter"
						class="form-control"
					>
						<option value="">
							${__("All transport")}
						</option>
					</select>

					<input
						id="sv-search"
						type="search"
						class="form-control"
						placeholder="${__(
							"Search name, host, phone, email or plate..."
						)}"
					/>

					<span id="sv-result-count" class="sv-result-count"></span>
				</div>

				<div class="sv-table-wrapper">
					<table class="table table-hover sv-table">
						<thead>
							<tr>
								<th>${__("Name")}</th>
								<th>${__("Meet With")}</th>
								<th>${__("Transport")}</th>
								<th>${__("Plate")}</th>
								<th>${__("Check In")}</th>
								<th>${__("Check Out")}</th>
								<th>${__("Duration")}</th>
								<th>${__("Status")}</th>
							</tr>
						</thead>

						<tbody id="sv-table-body">
							<tr>
								<td colspan="8" class="sv-loading">
									${__("Loading visitors...")}
								</td>
							</tr>
						</tbody>
					</table>
				</div>

			</div>

		</div>
	`);

	bind_visitors_events(page);
	load_visitors_data(page);
}


function bind_visitors_events(page) {
	const $root = $(page.main);

	$root.off(".securityVisitors");

	$root.on(
		"click.securityVisitors",
		"#sv-refresh",
		() => load_visitors_data(page, true)
	);

	$root.on(
		"click.securityVisitors",
		"#sv-new-visitor",
		() => frappe.new_doc("Appointment")
	);

	$root.on(
		"change.securityVisitors",
		"#sv-status-filter, #sv-transport-filter",
		() => load_visitors_data(page)
	);

	$root.on(
		"input.securityVisitors",
		"#sv-search",
		() => {
			window.clearTimeout(page.security_visitor_search_timer);

			page.security_visitor_search_timer =
				window.setTimeout(
					() => load_visitors_data(page),
					350
				);
		}
	);

	$root.on(
		"click.securityVisitors",
		".sv-visitor-row",
		function () {
			const appointment = $(this).attr(
				"data-appointment"
			);

			if (appointment) {
				frappe.set_route(
					"Form",
					"Appointment",
					appointment
				);
			}
		}
	);
}


async function load_visitors_data(page, showMessage = false) {
	const $root = $(page.main);
	const $body = $root.find("#sv-table-body");

	$body.html(`
		<tr>
			<td colspan="8" class="sv-loading">
				${__("Loading visitors...")}
			</td>
		</tr>
	`);

	try {
		const response = await frappe.call({
			method:
				"upande_security.api.security_dashboard.get_visitors_dashboard",
			args: {
				company:
					page.company_filter?.get_value?.() || "",
				farm:
					page.farm_filter?.get_value?.() ||
					page.site_filter?.get_value?.() ||
					"",
				status:
					$root.find("#sv-status-filter").val() ||
					"",
				transport:
					$root
						.find("#sv-transport-filter")
						.val() || "",
				search:
					$root.find("#sv-search").val() || "",
				start: 0,
				page_length: 100,
			},
			freeze: false,
		});

		const data = response.message || {};

		render_visitors_summary(
			$root,
			data.summary || {}
		);

		render_visitors_filter_options(
			$root,
			data
		);

		render_visitors_rows(
			$root,
			data.rows || []
		);

		$root
			.find("#sv-result-count")
			.text(
				__(
					"{0} record(s)",
					[data.filtered_total || 0]
				)
			);

		if (showMessage) {
			frappe.show_alert({
				message: __("Visitor data refreshed"),
				indicator: "green",
			});
		}
	} catch (error) {
		console.error(
			"Unable to load visitor dashboard",
			error
		);

		$body.html(`
			<tr>
				<td colspan="8" class="sv-error">
					${__(
						"Unable to load Appointment records. Check the browser console and server logs."
					)}
				</td>
			</tr>
		`);

		frappe.show_alert({
			message: __("Unable to load visitors"),
			indicator: "red",
		});
	}
}


function render_visitors_summary($root, summary) {
	$root.find("#sv-total").text(
		summary.total ?? 0
	);

	$root.find("#sv-checked-in").text(
		summary.checked_in ?? 0
	);

	$root.find("#sv-checked-out").text(
		summary.checked_out ?? 0
	);

	$root.find("#sv-scheduled").text(
		summary.scheduled ?? 0
	);
}


function render_visitors_filter_options($root, data) {
	set_security_select_options(
		$root.find("#sv-status-filter"),
		data.status_options || [],
		__("All statuses")
	);

	set_security_select_options(
		$root.find("#sv-transport-filter"),
		data.transport_options || [],
		__("All transport")
	);
}


function set_security_select_options(
	$select,
	options,
	emptyLabel
) {
	const currentValue = $select.val() || "";

	const optionHtml = [
		`<option value="">${escape_security_html(
			emptyLabel
		)}</option>`,
		...options.map((option) => `
			<option value="${escape_security_html(option)}">
				${escape_security_html(
					clean_security_status(option)
				)}
			</option>
		`),
	].join("");

	$select.html(optionHtml);

	if (
		currentValue &&
		options.includes(currentValue)
	) {
		$select.val(currentValue);
	}
}


function render_visitors_rows($root, rows) {
	const $body = $root.find("#sv-table-body");

	if (!rows.length) {
		$body.html(`
			<tr>
				<td colspan="8" class="sv-empty">
					${__("No visitor records match the filters.")}
				</td>
			</tr>
		`);
		return;
	}

	$body.html(
		rows.map((row) => {
			const visitorName =
				row.visitor_name || row.name;

			const initials = get_security_initials(
				visitorName
			);

			return `
				<tr
					class="sv-visitor-row"
					data-appointment="${escape_security_html(
						row.name
					)}"
				>
					<td>
						<div class="sv-person">
							<span class="sv-avatar">
								${escape_security_html(initials)}
							</span>

							<strong>
								${escape_security_html(
									visitorName
								)}
							</strong>
						</div>
					</td>

					<td>
						${display_security_value(
							row.meet_with
						)}
					</td>

					<td>
						${make_transport_badge(
							row.transport
						)}
					</td>

					<td>
						${display_security_value(
							row.plate
						)}
					</td>

					<td>
						${display_security_value(
							row.check_in
						)}
					</td>

					<td>
						${display_security_value(
							row.check_out
						)}
					</td>

					<td>
						${display_security_value(
							row.duration
						)}
					</td>

					<td>
						<span class="sv-status-badge">
							${escape_security_html(
								row.status || "Not Set"
							)}
						</span>
					</td>
				</tr>
			`;
		}).join("")
	);
}


function make_transport_badge(value) {
	if (!value) {
		return "—";
	}

	const normalised = String(value).toLowerCase();
	let icon = "♟";

	if (normalised.includes("vehicle")) {
		icon = "🚙";
	} else if (
		normalised.includes("bike") ||
		normalised.includes("motor")
	) {
		icon = "🏍";
	} else if (normalised.includes("foot")) {
		icon = "♟";
	}

	return `
		<span class="sv-transport-badge">
			${icon}
			${escape_security_html(value)}
		</span>
	`;
}


function display_security_value(value) {
	if (
		value === null ||
		value === undefined ||
		value === ""
	) {
		return "—";
	}

	return escape_security_html(value);
}


function escape_security_html(value) {
	return $("<div>")
		.text(
			value === null ||
			value === undefined
				? ""
				: String(value)
		)
		.html();
}


function get_security_initials(value) {
	const words = String(value || "")
		.trim()
		.split(/\s+/)
		.filter(Boolean);

	if (!words.length) {
		return "?";
	}

	return words
		.slice(0, 2)
		.map((word) => word.charAt(0))
		.join("")
		.toUpperCase();
}


function clean_security_status(value) {
	return String(value || "")
		.replace(/^Visitor\s+/i, "");
}


/* =========================================================
   PATROLS DASHBOARD VIEW
   ========================================================= */

function render_patrols_view(page) {
        const $root = $(page.main);
        const $content = $root.find(".security-app-content");

        $content.html(`
                <div class="security-patrols-view">

                        <div class="pv-page-heading">
                                <div>
                                        <h2>${__("Patrols")}</h2>
                                        <p>
                                                ${__("Security")}
                                                ›
                                                ${__("GPS Patrol Tracking")}
                                        </p>
                                </div>

                                <div class="pv-heading-actions">
                                        <button
                                                type="button"
                                                class="btn btn-default"
                                                id="pv-open-logs"
                                        >
                                                ${__("Open GPS Logs")}
                                        </button>

                                        <button
                                                type="button"
                                                class="btn btn-default"
                                                id="pv-refresh"
                                        >
                                                ${__("Refresh")}
                                        </button>

                                        <button
                                                type="button"
                                                class="btn btn-primary"
                                                id="pv-new-log"
                                        >
                                                ${__("New GPS Log")}
                                        </button>
                                </div>
                        </div>

                        <div class="pv-live-strip">
                                <span class="pv-live-dot"></span>

                                <span>
                                        ${__(
                                                "Active when the latest GPS point is within 15 minutes"
                                        )}
                                </span>

                                <span
                                        id="pv-last-updated"
                                        class="pv-last-updated"
                                ></span>
                        </div>

                        <div class="pv-kpi-grid">

                                ${make_patrol_kpi(
                                        "pv-total-patrols",
                                        __("Total Patrols"),
                                        "⚑",
                                        "blue"
                                )}

                                ${make_patrol_kpi(
                                        "pv-active-patrols",
                                        __("Active Patrols"),
                                        "●",
                                        "green"
                                )}

                                ${make_patrol_kpi(
                                        "pv-stale-patrols",
                                        __("Stale Patrols"),
                                        "◷",
                                        "amber"
                                )}

                                ${make_patrol_kpi(
                                        "pv-guards-tracked",
                                        __("Guards Tracked"),
                                        "♟",
                                        "purple"
                                )}

                                ${make_patrol_kpi(
                                        "pv-gps-points",
                                        __("GPS Points"),
                                        "⌖",
                                        "blue"
                                )}

                                ${make_patrol_kpi(
                                        "pv-tracking-alerts",
                                        __("Tracking Alerts"),
                                        "!",
                                        "red"
                                )}

                        </div>

                        <div class="pv-main-grid">

                                <section class="pv-panel pv-position-panel">

                                        <div class="pv-panel-header">
                                                <div>
                                                        <h3>
                                                                ${__(
                                                                        "Latest Patrol Positions"
                                                                )}
                                                        </h3>

                                                        <p>
                                                                ${__(
                                                                        "Most recent GPS point for each patrol"
                                                                )}
                                                        </p>
                                                </div>
                                        </div>

                                        <div
                                                id="pv-position-list"
                                                class="pv-position-list"
                                        >
                                                <div class="pv-loading">
                                                        ${__(
                                                                "Loading patrol positions..."
                                                        )}
                                                </div>
                                        </div>

                                </section>

                                <section class="pv-panel pv-log-panel">

                                        <div class="pv-filter-bar">

                                                <input
                                                        id="pv-date-filter"
                                                        type="date"
                                                        class="form-control"
                                                        value="${frappe.datetime.get_today()}"
                                                />

                                                <select
                                                        id="pv-personnel-filter"
                                                        class="form-control"
                                                >
                                                        <option value="">
                                                                ${__(
                                                                        "All Personnel"
                                                                )}
                                                        </option>

                                                        <option value="Internal Guard">
                                                                ${__(
                                                                        "Internal Guard"
                                                                )}
                                                        </option>

                                                        <option value="External Guard">
                                                                ${__(
                                                                        "External Guard"
                                                                )}
                                                        </option>
                                                </select>

                                                <input
                                                        id="pv-search"
                                                        type="search"
                                                        class="form-control"
                                                        placeholder="${__(
                                                                "Search patrol or guard..."
                                                        )}"
                                                />

                                                <span
                                                        id="pv-result-count"
                                                        class="pv-result-count"
                                                ></span>

                                        </div>

                                        <div class="pv-table-wrapper">
                                                <table
                                                        class="table table-hover pv-table"
                                                >
                                                        <thead>
                                                                <tr>
                                                                        <th>${__("Patrol")}</th>
                                                                        <th>${__("Guard")}</th>
                                                                        <th>${__("Personnel")}</th>
                                                                        <th>${__("Last Capture")}</th>
                                                                        <th>${__("Last Seen")}</th>
                                                                        <th>${__("Points")}</th>
                                                                        <th>${__("Latitude")}</th>
                                                                        <th>${__("Longitude")}</th>
                                                                        <th>${__("Accuracy")}</th>
                                                                        <th>${__("Status")}</th>
                                                                </tr>
                                                        </thead>

                                                        <tbody id="pv-table-body">
                                                                <tr>
                                                                        <td
                                                                                colspan="10"
                                                                                class="pv-loading"
                                                                        >
                                                                                ${__(
                                                                                        "Loading patrol data..."
                                                                                )}
                                                                        </td>
                                                                </tr>
                                                        </tbody>
                                                </table>
                                        </div>

                                </section>

                        </div>

                </div>
        `);

        bind_patrol_events(page);
        load_patrols_data(page);

        if (page.security_patrol_refresh_timer) {
                window.clearInterval(
                        page.security_patrol_refresh_timer
                );
        }

        page.security_patrol_refresh_timer =
                window.setInterval(() => {
                        if (
                                page.security_current_view ===
                                "patrols"
                        ) {
                                load_patrols_data(
                                        page,
                                        false,
                                        true
                                );
                        }
                }, 30000);
}


function make_patrol_kpi(
        elementId,
        label,
        icon,
        colour
) {
        return `
                <div class="pv-kpi-card">
                        <span
                                class="pv-kpi-icon pv-${colour}"
                        >
                                ${icon}
                        </span>

                        <div>
                                <strong id="${elementId}">—</strong>
                                <span>${label}</span>
                        </div>
                </div>
        `;
}


function bind_patrol_events(page) {
        const $root = $(page.main);

        $root.off(".securityPatrols");

        $root.on(
                "click.securityPatrols",
                "#pv-refresh",
                () => load_patrols_data(page, true)
        );

        $root.on(
                "click.securityPatrols",
                "#pv-open-logs",
                () => {
                        frappe.set_route(
                                "List",
                                "Patrol GPS Log"
                        );
                }
        );

        $root.on(
                "click.securityPatrols",
                "#pv-new-log",
                () => frappe.new_doc("Patrol GPS Log")
        );

        $root.on(
                "change.securityPatrols",
                "#pv-date-filter, #pv-personnel-filter",
                () => load_patrols_data(page)
        );

        $root.on(
                "input.securityPatrols",
                "#pv-search",
                () => {
                        window.clearTimeout(
                                page.security_patrol_search_timer
                        );

                        page.security_patrol_search_timer =
                                window.setTimeout(
                                        () => load_patrols_data(page),
                                        350
                                );
                }
        );

        $root.on(
                "click.securityPatrols",
                ".pv-patrol-row, .pv-position-card",
                function () {
                        const logName = $(this).attr(
                                "data-log-name"
                        );

                        if (logName) {
                                frappe.set_route(
                                        "Form",
                                        "Patrol GPS Log",
                                        logName
                                );
                        }
                }
        );
}


async function load_patrols_data(
        page,
        showMessage = false,
        silent = false
) {
        const $root = $(page.main);
        const $body = $root.find("#pv-table-body");

        if (!silent) {
                $body.html(`
                        <tr>
                                <td
                                        colspan="10"
                                        class="pv-loading"
                                >
                                        ${__(
                                                "Loading patrol data..."
                                        )}
                                </td>
                        </tr>
                `);
        }

        try {
                const response = await frappe.call({
                        method:
                                "upande_security.api.security_dashboard.get_patrols_dashboard",
                        args: {
                                date:
                                        $root
                                                .find("#pv-date-filter")
                                                .val() ||
                                        frappe.datetime.get_today(),

                                personnel:
                                        $root
                                                .find("#pv-personnel-filter")
                                                .val() || "",

                                search:
                                        $root
                                                .find("#pv-search")
                                                .val() || "",

                                active_window_minutes: 15,
                        },
                        freeze: false,
                });

                const data = response.message || {};

                render_patrol_summary(
                        $root,
                        data.summary || {}
                );

                render_patrol_rows(
                        $root,
                        data.rows || []
                );

                render_patrol_positions(
                        $root,
                        data.rows || []
                );

                $root
                        .find("#pv-result-count")
                        .text(
                                __(
                                        "{0} patrol(s)",
                                        [
                                                (
                                                        data.rows ||
                                                        []
                                                ).length,
                                        ]
                                )
                        );

                $root
                        .find("#pv-last-updated")
                        .text(
                                `${__("Updated")}: ${
                                        new Date().toLocaleTimeString()
                                }`
                        );

                if (showMessage) {
                        frappe.show_alert({
                                message:
                                        __(
                                                "Patrol data refreshed"
                                        ),
                                indicator: "green",
                        });
                }
        } catch (error) {
                console.error(
                        "Unable to load patrol dashboard",
                        error
                );

                $body.html(`
                        <tr>
                                <td
                                        colspan="10"
                                        class="pv-error"
                                >
                                        ${__(
                                                "Unable to load Patrol GPS Log records. Check the browser console and server logs."
                                        )}
                                </td>
                        </tr>
                `);

                if (!silent) {
                        frappe.show_alert({
                                message:
                                        __(
                                                "Unable to load patrol data"
                                        ),
                                indicator: "red",
                        });
                }
        }
}


function render_patrol_summary($root, summary) {
        const values = {
                "pv-total-patrols":
                        summary.total_patrols ?? 0,

                "pv-active-patrols":
                        summary.active_patrols ?? 0,

                "pv-stale-patrols":
                        summary.stale_patrols ?? 0,

                "pv-guards-tracked":
                        summary.guards_tracked ?? 0,

                "pv-gps-points":
                        summary.gps_points ?? 0,

                "pv-tracking-alerts":
                        summary.tracking_alerts ?? 0,
        };

        Object.entries(values).forEach(
                ([elementId, value]) => {
                        $root
                                .find(`#${elementId}`)
                                .text(value);
                }
        );
}


function render_patrol_rows($root, rows) {
        const $body = $root.find("#pv-table-body");

        if (!rows.length) {
                $body.html(`
                        <tr>
                                <td
                                        colspan="10"
                                        class="pv-empty"
                                >
                                        ${__(
                                                "No patrol GPS records match the selected filters."
                                        )}
                                </td>
                        </tr>
                `);

                return;
        }

        $body.html(
                rows.map((row) => {
                        return `
                                <tr
                                        class="pv-patrol-row"
                                        data-log-name="${escape_security_html(
                                                row.latest_log
                                        )}"
                                >
                                        <td>
                                                <strong>
                                                        ${display_security_value(
                                                                row.patrol
                                                        )}
                                                </strong>
                                        </td>

                                        <td>
                                                ${display_security_value(
                                                        row.guard
                                                )}
                                        </td>

                                        <td>
                                                ${display_security_value(
                                                        row.personnel_type
                                                )}
                                        </td>

                                        <td>
                                                ${display_security_value(
                                                        row.latest_captured_at
                                                )}
                                        </td>

                                        <td>
                                                ${display_security_value(
                                                        row.last_seen
                                                )}
                                        </td>

                                        <td>
                                                ${display_security_value(
                                                        row.point_count
                                                )}
                                        </td>

                                        <td>
                                                ${format_patrol_coordinate(
                                                        row.latitude
                                                )}
                                        </td>

                                        <td>
                                                ${format_patrol_coordinate(
                                                        row.longitude
                                                )}
                                        </td>

                                        <td>
                                                ${format_patrol_accuracy(
                                                        row.gps_accuracy
                                                )}
                                        </td>

                                        <td>
                                                ${make_patrol_status_badge(
                                                        row.tracking_status
                                                )}
                                        </td>
                                </tr>
                        `;
                }).join("")
        );
}


function render_patrol_positions($root, rows) {
        const $container = $root.find(
                "#pv-position-list"
        );

        const validRows = rows.filter(
                (row) => row.coordinate_valid
        );

        if (!validRows.length) {
                $container.html(`
                        <div class="pv-empty">
                                ${__(
                                        "No valid GPS positions are available."
                                )}
                        </div>
                `);

                return;
        }

        $container.html(
                validRows.slice(0, 12).map((row) => `
                        <button
                                type="button"
                                class="pv-position-card"
                                data-log-name="${escape_security_html(
                                        row.latest_log
                                )}"
                        >
                                <div>
                                        <strong>
                                                ${escape_security_html(
                                                        row.patrol
                                                )}
                                        </strong>

                                        <span>
                                                ${display_security_value(
                                                        row.guard
                                                )}
                                        </span>
                                </div>

                                <div class="pv-position-coordinates">
                                        <span>
                                                ${format_patrol_coordinate(
                                                        row.latitude
                                                )}
                                        </span>

                                        <span>
                                                ${format_patrol_coordinate(
                                                        row.longitude
                                                )}
                                        </span>
                                </div>

                                ${make_patrol_status_badge(
                                        row.tracking_status
                                )}
                        </button>
                `).join("")
        );
}


function format_patrol_coordinate(value) {
        if (
                value === null ||
                value === undefined ||
                value === ""
        ) {
                return "—";
        }

        const number = Number(value);

        if (!Number.isFinite(number)) {
                return escape_security_html(value);
        }

        return number.toFixed(6);
}


function format_patrol_accuracy(value) {
        if (
                value === null ||
                value === undefined ||
                value === ""
        ) {
                return "—";
        }

        const number = Number(value);

        if (!Number.isFinite(number)) {
                return escape_security_html(value);
        }

        return `${number.toFixed(1)} m`;
}


function make_patrol_status_badge(status) {
        const normalised = String(
                status || "Historical"
        ).toLowerCase();

        let className = "historical";

        if (normalised === "active") {
                className = "active";
        } else if (normalised === "stale") {
                className = "stale";
        }

        return `
                <span
                        class="pv-status-badge pv-status-${className}"
                >
                        ${escape_security_html(
                                status || "Historical"
                        )}
                </span>
        `;
}

/* BEGIN INCIDENTS DASHBOARD VIEW */

function render_incidents_view(page) {
        const $root = $(page.main);
        const $content = $root.find(
                ".security-app-content"
        );

        page.security_incident_range =
                page.security_incident_range || "1y";

        const range = get_incident_date_range(
                page.security_incident_range
        );

        $content.html(`
                <div class="security-incidents-view">

                        <div class="iv-header">
                                <div>
                                        <h2>${__("Incidents")}</h2>
                                        <p>
                                                ${__("Security")}
                                                ›
                                                ${__("Reported incidents")}
                                        </p>
                                </div>

                                <div class="iv-header-controls">

                                        <select
                                                class="form-control"
                                                disabled
                                                title="${__(
                                                        "Company mapping will be connected through Location"
                                                )}"
                                        >
                                                <option>
                                                        ${__(
                                                                "All companies"
                                                        )}
                                                </option>
                                        </select>

                                        <select
                                                class="form-control"
                                                disabled
                                                title="${__(
                                                        "Farm or unit mapping will be connected through Location"
                                                )}"
                                        >
                                                <option>
                                                        ${__(
                                                                "All farms/units"
                                                        )}
                                                </option>
                                        </select>

                                        <span class="iv-updated">
                                                <span class="iv-online-dot"></span>
                                                <span id="iv-updated-time">
                                                        ${__("Loading...")}
                                                </span>
                                        </span>

                                        <span
                                                id="iv-date-chip"
                                                class="iv-date-chip"
                                        >
                                                ${escape_incident_html(
                                                        range.to
                                                )}
                                        </span>

                                        <button
                                                type="button"
                                                class="btn btn-default"
                                                id="iv-export-csv"
                                        >
                                                ${__("CSV")}
                                        </button>

                                        <button
                                                type="button"
                                                class="btn btn-default"
                                                id="iv-export-excel"
                                        >
                                                ${__("Excel")}
                                        </button>

                                        <button
                                                type="button"
                                                class="btn btn-success"
                                                id="iv-print-report"
                                        >
                                                ${__("Send PDF Report")}
                                        </button>
                                </div>
                        </div>

                        <div class="iv-toolbar">

                                <div class="iv-range-buttons">

                                        ${make_incident_range_button(
                                                "today",
                                                __("Today"),
                                                page.security_incident_range
                                        )}

                                        ${make_incident_range_button(
                                                "7d",
                                                __("7d"),
                                                page.security_incident_range
                                        )}

                                        ${make_incident_range_button(
                                                "30d",
                                                __("30d"),
                                                page.security_incident_range
                                        )}

                                        ${make_incident_range_button(
                                                "1y",
                                                __("1y"),
                                                page.security_incident_range
                                        )}

                                        ${make_incident_range_button(
                                                "custom",
                                                __("Custom"),
                                                page.security_incident_range
                                        )}

                                </div>

                                <span
                                        id="iv-range-label"
                                        class="iv-range-label"
                                >
                                        ${escape_incident_html(
                                                range.from
                                        )}
                                        →
                                        ${escape_incident_html(
                                                range.to
                                        )}
                                </span>

                                <button
                                        type="button"
                                        class="btn btn-default"
                                        id="iv-refresh"
                                >
                                        ${__("Refresh")}
                                </button>

                                <button
                                        type="button"
                                        class="btn btn-primary"
                                        id="iv-new-incident"
                                >
                                        + ${__("File New Incident")}
                                </button>

                        </div>

                        <div
                                id="iv-custom-range"
                                class="iv-custom-range"
                                style="display: none;"
                        >
                                <input
                                        type="date"
                                        id="iv-date-from"
                                        class="form-control"
                                        value="${escape_incident_html(
                                                range.from
                                        )}"
                                />

                                <span>→</span>

                                <input
                                        type="date"
                                        id="iv-date-to"
                                        class="form-control"
                                        value="${escape_incident_html(
                                                range.to
                                        )}"
                                />

                                <button
                                        type="button"
                                        class="btn btn-primary"
                                        id="iv-apply-custom-range"
                                >
                                        ${__("Apply")}
                                </button>
                        </div>

                        <div class="iv-kpi-grid">

                                ${make_incident_kpi(
                                        "iv-total",
                                        __("Total in range"),
                                        "▣",
                                        "blue"
                                )}

                                ${make_incident_kpi(
                                        "iv-open",
                                        __("Open"),
                                        "!",
                                        "red",
                                        "iv-open-subtitle"
                                )}

                                ${make_incident_kpi(
                                        "iv-investigation",
                                        __("Under investigation"),
                                        "⌕",
                                        "purple"
                                )}

                                ${make_incident_kpi(
                                        "iv-resolved",
                                        __("Resolved + Closed"),
                                        "✓",
                                        "green"
                                )}

                                ${make_incident_kpi(
                                        "iv-average-resolution",
                                        __("Avg resolution"),
                                        "◷",
                                        "amber",
                                        "iv-average-subtitle"
                                )}

                        </div>

                        <div class="iv-two-column-grid">

                                <section class="iv-panel">
                                        <div class="iv-panel-heading">
                                                <h3>
                                                        ${__(
                                                                "Severity distribution"
                                                        )}
                                                </h3>

                                                <span id="iv-severity-total">
                                                        —
                                                </span>
                                        </div>

                                        <div
                                                id="iv-severity-distribution"
                                                class="iv-severity-grid"
                                        ></div>

                                        <div class="iv-workflow-title">
                                                ${__("Workflow state")}
                                        </div>

                                        <div
                                                id="iv-workflow-distribution"
                                                class="iv-workflow-list"
                                        ></div>
                                </section>

                                <section class="iv-panel">
                                        <div class="iv-panel-heading">
                                                <h3>
                                                        ${__("By category")}
                                                </h3>

                                                <span id="iv-category-total">
                                                        —
                                                </span>
                                        </div>

                                        <div
                                                id="iv-category-distribution"
                                                class="iv-category-grid"
                                        ></div>
                                </section>

                        </div>

                        <div class="iv-two-column-grid">

                                <section class="iv-panel">
                                        <div class="iv-panel-heading">
                                                <h3>
                                                        ${__(
                                                                "Who reported"
                                                        )}
                                                </h3>
                                        </div>

                                        <div
                                                id="iv-reporter-chart"
                                                class="iv-bar-chart"
                                        ></div>
                                </section>

                                <section class="iv-panel">
                                        <div class="iv-panel-heading">
                                                <h3>
                                                        ${__(
                                                                "Where"
                                                        )}
                                                </h3>
                                        </div>

                                        <div
                                                id="iv-location-chart"
                                                class="iv-bar-chart iv-location-bars"
                                        ></div>
                                </section>

                        </div>

                        <section class="iv-panel">
                                <div class="iv-panel-heading">
                                        <h3>
                                                ${__(
                                                        "Incidents over time"
                                                )}
                                        </h3>
                                </div>

                                <div
                                        id="iv-time-chart"
                                        class="iv-time-chart"
                                ></div>
                        </section>

                        <section class="iv-panel">
                                <div class="iv-panel-heading">
                                        <h3>
                                                ${__(
                                                        "Incident photos"
                                                )}
                                        </h3>

                                        <span id="iv-photo-count">
                                                —
                                        </span>
                                </div>

                                <div
                                        id="iv-photo-gallery"
                                        class="iv-photo-gallery"
                                ></div>
                        </section>

                        <section class="iv-panel">
                                <div class="iv-panel-heading">
                                        <h3>
                                                ${__(
                                                        "Recent incidents"
                                                )}
                                        </h3>

                                        <span id="iv-recent-count">
                                                —
                                        </span>
                                </div>

                                <div class="iv-table-wrapper">
                                        <table class="table iv-table">
                                                <thead>
                                                        <tr>
                                                                <th>
                                                                        ${__(
                                                                                "Incident"
                                                                        )}
                                                                </th>
                                                                <th>
                                                                        ${__(
                                                                                "Category"
                                                                        )}
                                                                </th>
                                                                <th>
                                                                        ${__(
                                                                                "Severity"
                                                                        )}
                                                                </th>
                                                                <th>
                                                                        ${__(
                                                                                "Status"
                                                                        )}
                                                                </th>
                                                                <th>
                                                                        ${__(
                                                                                "Location"
                                                                        )}
                                                                </th>
                                                                <th>
                                                                        ${__(
                                                                                "Reporter"
                                                                        )}
                                                                </th>
                                                                <th>
                                                                        ${__(
                                                                                "When"
                                                                        )}
                                                                </th>
                                                                <th>
                                                                        ${__(
                                                                                "Photo"
                                                                        )}
                                                                </th>
                                                        </tr>
                                                </thead>

                                                <tbody id="iv-table-body">
                                                        <tr>
                                                                <td
                                                                        colspan="8"
                                                                        class="iv-loading"
                                                                >
                                                                        ${__(
                                                                                "Loading incidents..."
                                                                        )}
                                                                </td>
                                                        </tr>
                                                </tbody>
                                        </table>
                                </div>
                        </section>

                </div>
        `);

        bind_incident_events(page);
        load_incidents_data(page);

        if (page.security_incident_refresh_timer) {
                window.clearInterval(
                        page.security_incident_refresh_timer
                );
        }

        page.security_incident_refresh_timer =
                window.setInterval(() => {
                        if (
                                $(page.main)
                                        .find(
                                                ".security-incidents-view"
                                        )
                                        .length
                        ) {
                                load_incidents_data(
                                        page,
                                        true
                                );
                        }
                }, 60000);
}


function make_incident_range_button(
        range,
        label,
        selectedRange
) {
        const activeClass =
                range === selectedRange
                        ? "active"
                        : "";

        return `
                <button
                        type="button"
                        class="iv-range-button ${activeClass}"
                        data-range="${range}"
                >
                        ${label}
                </button>
        `;
}


function make_incident_kpi(
        elementId,
        label,
        icon,
        colour,
        subtitleId = ""
) {
        return `
                <div class="iv-kpi-card">
                        <span
                                class="iv-kpi-icon iv-${colour}"
                        >
                                ${icon}
                        </span>

                        <div>
                                <strong id="${elementId}">
                                        —
                                </strong>

                                <span>${label}</span>

                                ${
                                        subtitleId
                                                ? `
                                                        <small id="${subtitleId}">
                                                                &nbsp;
                                                        </small>
                                                `
                                                : ""
                                }
                        </div>
                </div>
        `;
}


function bind_incident_events(page) {
        const $root = $(page.main);

        $root.off(".securityIncidents");

        $root.on(
                "click.securityIncidents",
                ".iv-range-button",
                function () {
                        const range = $(this).attr(
                                "data-range"
                        );

                        page.security_incident_range = range;

                        $root
                                .find(".iv-range-button")
                                .removeClass("active");

                        $(this).addClass("active");

                        if (range === "custom") {
                                $root
                                        .find("#iv-custom-range")
                                        .slideDown(150);

                                return;
                        }

                        $root
                                .find("#iv-custom-range")
                                .slideUp(150);

                        load_incidents_data(page);
                }
        );

        $root.on(
                "click.securityIncidents",
                "#iv-apply-custom-range",
                () => load_incidents_data(page)
        );

        $root.on(
                "click.securityIncidents",
                "#iv-refresh",
                () => load_incidents_data(
                        page,
                        false,
                        true
                )
        );

        $root.on(
                "click.securityIncidents",
                "#iv-new-incident",
                () => frappe.new_doc("Incident Report")
        );

        $root.on(
                "click.securityIncidents",
                ".iv-incident-row, .iv-photo-card",
                function () {
                        const incident = $(this).attr(
                                "data-incident"
                        );

                        if (incident) {
                                frappe.set_route(
                                        "Form",
                                        "Incident Report",
                                        incident
                                );
                        }
                }
        );

        $root.on(
                "click.securityIncidents",
                "#iv-export-csv",
                () => export_incidents_csv(page)
        );

        $root.on(
                "click.securityIncidents",
                "#iv-export-excel",
                () => export_incidents_excel(page)
        );

        $root.on(
                "click.securityIncidents",
                "#iv-print-report",
                () => window.print()
        );
}


async function load_incidents_data(
        page,
        silent = false,
        showMessage = false
) {
        const $root = $(page.main);
        const $body = $root.find("#iv-table-body");

        if (!silent) {
                $body.html(`
                        <tr>
                                <td
                                        colspan="8"
                                        class="iv-loading"
                                >
                                        ${__(
                                                "Loading incidents..."
                                        )}
                                </td>
                        </tr>
                `);
        }

        const range = get_incident_date_range(
                page.security_incident_range,
                $root
        );

        $root
                .find("#iv-range-label")
                .text(
                        `${range.from} → ${range.to}`
                );

        $root
                .find("#iv-date-chip")
                .text(range.to);

        try {
                const response = await frappe.call({
                        method:
                                "upande_security.api.security_dashboard.get_incidents_dashboard",
                        args: {
                                date_from: range.from,
                                date_to: range.to,
                                limit: 1000,
                        },
                        freeze: false,
                });

                const data = response.message || {};

                page.security_incident_data = data;

                render_incident_dashboard(
                        $root,
                        data
                );

                $root
                        .find("#iv-updated-time")
                        .text(
                                `${__("Updated")} ${
                                        new Date()
                                                .toLocaleTimeString(
                                                        [],
                                                        {
                                                                hour:
                                                                        "2-digit",
                                                                minute:
                                                                        "2-digit",
                                                        }
                                                )
                                }`
                        );

                if (showMessage) {
                        frappe.show_alert({
                                message:
                                        __(
                                                "Incident data refreshed"
                                        ),
                                indicator: "green",
                        });
                }
        } catch (error) {
                console.error(
                        "Unable to load Incident Report dashboard",
                        error
                );

                $body.html(`
                        <tr>
                                <td
                                        colspan="8"
                                        class="iv-error"
                                >
                                        ${__(
                                                "Unable to load Incident Report records."
                                        )}
                                </td>
                        </tr>
                `);

                if (!silent) {
                        frappe.show_alert({
                                message:
                                        __(
                                                "Unable to load incidents"
                                        ),
                                indicator: "red",
                        });
                }
        }
}


function render_incident_dashboard(
        $root,
        data
) {
        const rows = data.rows || [];
        const summary = data.summary || {};

        const openCritical = rows.filter(
                (row) =>
                        row.status === "Open"
                        && row.severity === "Critical"
        ).length;

        const resolvedClosed =
                Number(
                        summary.resolved_incidents || 0
                )
                + Number(
                        summary.closed_incidents || 0
                );

        $root
                .find("#iv-total")
                .text(
                        summary.total_incidents || 0
                );

        $root
                .find("#iv-open")
                .text(
                        summary.open_incidents || 0
                );

        $root
                .find("#iv-open-subtitle")
                .text(
                        __(
                                "{0} critical",
                                [openCritical]
                        )
                );

        $root
                .find("#iv-investigation")
                .text(
                        summary.in_progress_incidents
                        || 0
                );

        $root
                .find("#iv-resolved")
                .text(resolvedClosed);

        $root
                .find("#iv-average-resolution")
                .text(
                        get_average_incident_resolution(
                                rows
                        )
                );

        $root
                .find("#iv-average-subtitle")
                .text(__("Per incident"));

        render_incident_severity(
                $root,
                rows
        );

        render_incident_categories(
                $root,
                data.category_summary || []
        );

        render_incident_bar_chart(
                $root.find("#iv-reporter-chart"),
                count_incident_values(
                        rows,
                        (row) =>
                                row.reporter_name
                                || row.reported_by
                                || __("Unknown")
                ),
                10
        );

        render_incident_bar_chart(
                $root.find("#iv-location-chart"),
                count_incident_values(
                        rows,
                        (row) =>
                                row.location
                                || __(
                                        "Location unavailable"
                                )
                ),
                10
        );

        render_incident_time_chart(
                $root,
                rows
        );

        render_incident_photos(
                $root,
                rows
        );

        render_recent_incidents(
                $root,
                rows
        );

        update_incident_sidebar_badge(
                $root,
                summary.open_incidents || 0
        );
}


function render_incident_severity(
        $root,
        rows
) {
        const severities = [
                "Critical",
                "High",
                "Medium",
                "Low",
        ];

        const severityCounts = count_incident_values(
                rows,
                (row) => row.severity || "Not Set"
        );

        $root
                .find("#iv-severity-total")
                .text(
                        __(
                                "{0} total",
                                [rows.length]
                        )
                );

        $root
                .find("#iv-severity-distribution")
                .html(
                        severities.map(
                                (severity) => `
                                        <div
                                                class="iv-severity-box iv-severity-${severity.toLowerCase()}"
                                        >
                                                <span>
                                                        ${escape_incident_html(
                                                                severity
                                                        )}
                                                </span>

                                                <strong>
                                                        ${
                                                                severityCounts[
                                                                        severity
                                                                ]
                                                                || 0
                                                        }
                                                </strong>
                                        </div>
                                `
                        ).join("")
                );

        const statuses = [
                "Closed",
                "Resolved",
                "In Progress",
                "Open",
                "Not Set",
        ];

        const statusCounts = count_incident_values(
                rows,
                (row) => row.status || "Not Set"
        );

        const workflowRows = statuses
                .filter(
                        (status) =>
                                Number(
                                        statusCounts[status]
                                        || 0
                                ) > 0
                )
                .map(
                        (status) => `
                                <div class="iv-workflow-row">
                                        ${make_incident_status_badge(
                                                status
                                        )}

                                        <span class="iv-workflow-line"></span>

                                        <strong>
                                                ${
                                                        statusCounts[
                                                                status
                                                        ]
                                                        || 0
                                                }
                                        </strong>
                                </div>
                        `
                )
                .join("");

        $root
                .find("#iv-workflow-distribution")
                .html(
                        workflowRows
                        || `
                                <div class="iv-empty">
                                        ${__(
                                                "No workflow data"
                                        )}
                                </div>
                        `
                );
}


function render_incident_categories(
        $root,
        categories
) {
        const total = categories.reduce(
                (sum, category) =>
                        sum
                        + Number(
                                category.count || 0
                        ),
                0
        );

        $root
                .find("#iv-category-total")
                .text(
                        __(
                                "{0} categories",
                                [categories.length]
                        )
                );

        if (!categories.length) {
                $root
                        .find(
                                "#iv-category-distribution"
                        )
                        .html(`
                                <div class="iv-empty">
                                        ${__(
                                                "No category data"
                                        )}
                                </div>
                        `);

                return;
        }

        $root
                .find(
                        "#iv-category-distribution"
                )
                .html(
                        categories.slice(0, 12).map(
                                (category) => {
                                        const percentage =
                                                total
                                                        ? Math.round(
                                                                (
                                                                        Number(
                                                                                category.count
                                                                                || 0
                                                                        )
                                                                        / total
                                                                )
                                                                * 100
                                                        )
                                                        : 0;

                                        return `
                                                <div class="iv-category-card">
                                                        <span>
                                                                ${escape_incident_html(
                                                                        category.category
                                                                )}
                                                        </span>

                                                        <strong>
                                                                ${
                                                                        category.count
                                                                        || 0
                                                                }
                                                        </strong>

                                                        <small>
                                                                ${percentage}%
                                                                ${__(
                                                                        "of total"
                                                                )}
                                                        </small>
                                                </div>
                                        `;
                                }
                        ).join("")
                );
}


function render_incident_bar_chart(
        $container,
        counts,
        maximumRows
) {
        const entries = Object.entries(counts)
                .sort(
                        (first, second) =>
                                second[1] - first[1]
                )
                .slice(0, maximumRows);

        if (!entries.length) {
                $container.html(`
                        <div class="iv-empty">
                                ${__("No data available")}
                        </div>
                `);

                return;
        }

        const maximum = Math.max(
                ...entries.map(
                        (entry) => entry[1]
                ),
                1
        );

        $container.html(
                entries.map(
                        ([label, count]) => {
                                const percentage =
                                        Math.max(
                                                (
                                                        count
                                                        / maximum
                                                )
                                                * 100,
                                                2
                                        );

                                return `
                                        <div class="iv-bar-row">
                                                <span
                                                        title="${escape_incident_html(
                                                                label
                                                        )}"
                                                >
                                                        ${escape_incident_html(
                                                                label
                                                        )}
                                                </span>

                                                <div class="iv-bar-track">
                                                        <i
                                                                style="width: ${percentage}%;"
                                                        ></i>
                                                </div>

                                                <strong>
                                                        ${count}
                                                </strong>
                                        </div>
                                `;
                        }
                ).join("")
        );
}


function render_incident_time_chart(
        $root,
        rows
) {
        const $container = $root.find(
                "#iv-time-chart"
        );

        const dailyCounts = count_incident_values(
                rows,
                (row) => {
                        const raw =
                                row.incident_datetime_raw;

                        if (!raw) {
                                return "";
                        }

                        return String(raw).slice(0, 10);
                }
        );

        const entries = Object.entries(
                dailyCounts
        )
                .filter(
                        ([label]) => label
                )
                .sort(
                        (first, second) =>
                                first[0].localeCompare(
                                        second[0]
                                )
                );

        if (!entries.length) {
                $container.html(`
                        <div class="iv-empty">
                                ${__(
                                        "No incident timeline data"
                                )}
                        </div>
                `);

                return;
        }

        const width = 1100;
        const height = 225;
        const left = 50;
        const right = 20;
        const top = 18;
        const bottom = 48;

        const plotWidth =
                width - left - right;

        const plotHeight =
                height - top - bottom;

        const maximum = Math.max(
                ...entries.map(
                        (entry) => entry[1]
                ),
                1
        );

        const points = entries.map(
                (entry, index) => {
                        const x =
                                entries.length === 1
                                        ? left
                                                + plotWidth
                                                / 2
                                        : left
                                                + (
                                                        index
                                                        / (
                                                                entries.length
                                                                - 1
                                                        )
                                                )
                                                * plotWidth;

                        const y =
                                top
                                + plotHeight
                                - (
                                        entry[1]
                                        / maximum
                                )
                                * plotHeight;

                        return {
                                label: entry[0],
                                count: entry[1],
                                x,
                                y,
                        };
                }
        );

        const polyline = points
                .map(
                        (point) =>
                                `${point.x},${point.y}`
                )
                .join(" ");

        const areaPoints = [
                `${points[0].x},${top + plotHeight}`,
                ...points.map(
                        (point) =>
                                `${point.x},${point.y}`
                ),
                `${
                        points[
                                points.length - 1
                        ].x
                },${top + plotHeight}`,
        ].join(" ");

        const horizontalGrid = [0, 1, 2, 3, 4]
                .map((step) => {
                        const y =
                                top
                                + (
                                        step / 4
                                )
                                * plotHeight;

                        const value = Math.round(
                                maximum
                                - (
                                        step / 4
                                )
                                * maximum
                        );

                        return `
                                <line
                                        x1="${left}"
                                        y1="${y}"
                                        x2="${width - right}"
                                        y2="${y}"
                                        class="iv-chart-grid"
                                />

                                <text
                                        x="${left - 10}"
                                        y="${y + 4}"
                                        class="iv-chart-axis"
                                        text-anchor="end"
                                >
                                        ${value}
                                </text>
                        `;
                })
                .join("");

        const labelStep = Math.max(
                Math.ceil(entries.length / 10),
                1
        );

        const labels = points
                .filter(
                        (_, index) =>
                                index % labelStep === 0
                                || index
                                        === points.length
                                        - 1
                )
                .map(
                        (point) => `
                                <text
                                        x="${point.x}"
                                        y="${height - 15}"
                                        class="iv-chart-axis"
                                        text-anchor="middle"
                                >
                                        ${escape_incident_html(
                                                point.label.slice(
                                                        5
                                                )
                                        )}
                                </text>
                        `
                )
                .join("");

        const circles = points
                .map(
                        (point) => `
                                <circle
                                        cx="${point.x}"
                                        cy="${point.y}"
                                        r="3"
                                        class="iv-chart-point"
                                >
                                        <title>
                                                ${escape_incident_html(
                                                        point.label
                                                )}: ${point.count}
                                        </title>
                                </circle>
                        `
                )
                .join("");

        $container.html(`
                <svg
                        viewBox="0 0 ${width} ${height}"
                        role="img"
                        aria-label="${__(
                                "Incidents over time"
                        )}"
                >
                        ${horizontalGrid}

                        <polygon
                                points="${areaPoints}"
                                class="iv-chart-area"
                        ></polygon>

                        <polyline
                                points="${polyline}"
                                class="iv-chart-line"
                        ></polyline>

                        ${circles}
                        ${labels}
                </svg>
        `);
}


function render_incident_photos(
        $root,
        rows
) {
        const photos = [];

        rows.forEach((row) => {
                (row.attachments || []).forEach(
                        (attachment) => {
                                photos.push({
                                        incident: row.name,
                                        severity:
                                                row.severity,
                                        attachment,
                                });
                        }
                );
        });

        $root
                .find("#iv-photo-count")
                .text(
                        __(
                                "{0} photos",
                                [photos.length]
                        )
                );

        if (!photos.length) {
                $root
                        .find("#iv-photo-gallery")
                        .html(`
                                <div class="iv-empty">
                                        ${__(
                                                "No incident photographs"
                                        )}
                                </div>
                        `);

                return;
        }

        $root
                .find("#iv-photo-gallery")
                .html(
                        photos.slice(0, 12).map(
                                (photo) => `
                                        <button
                                                type="button"
                                                class="iv-photo-card"
                                                data-incident="${escape_incident_html(
                                                        photo.incident
                                                )}"
                                        >
                                                <img
                                                        src="${escape_incident_html(
                                                                photo.attachment
                                                        )}"
                                                        alt="${__(
                                                                "Incident photograph"
                                                        )}"
                                                        loading="lazy"
                                                />

                                                ${make_incident_severity_badge(
                                                        photo.severity
                                                )}
                                        </button>
                                `
                        ).join("")
                );
}


function render_recent_incidents(
        $root,
        rows
) {
        const recentRows = rows.slice(0, 20);

        $root
                .find("#iv-recent-count")
                .text(recentRows.length);

        if (!recentRows.length) {
                $root
                        .find("#iv-table-body")
                        .html(`
                                <tr>
                                        <td
                                                colspan="8"
                                                class="iv-empty"
                                        >
                                                ${__(
                                                        "No incidents found for this period."
                                                )}
                                        </td>
                                </tr>
                        `);

                return;
        }

        $root
                .find("#iv-table-body")
                .html(
                        recentRows.map(
                                (row) => {
                                        const attachments =
                                                row.attachments
                                                || [];

                                        const firstPhoto =
                                                attachments[0];

                                        const additional =
                                                Math.max(
                                                        attachments.length
                                                        - 1,
                                                        0
                                                );

                                        return `
                                                <tr
                                                        class="iv-incident-row"
                                                        data-incident="${escape_incident_html(
                                                                row.name
                                                        )}"
                                                >
                                                        <td>
                                                                <a href="#">
                                                                        ${escape_incident_html(
                                                                                row.name
                                                                        )}
                                                                </a>
                                                        </td>

                                                        <td>
                                                                ${display_incident_value(
                                                                        row.nature_of_incident
                                                                )}
                                                        </td>

                                                        <td>
                                                                ${make_incident_severity_badge(
                                                                        row.severity
                                                                )}
                                                        </td>

                                                        <td>
                                                                ${make_incident_status_badge(
                                                                        row.status
                                                                )}
                                                        </td>

                                                        <td>
                                                                ${display_incident_value(
                                                                        row.location
                                                                )}
                                                        </td>

                                                        <td>
                                                                ${display_incident_value(
                                                                        row.reporter_name
                                                                        || row.reported_by
                                                                )}
                                                        </td>

                                                        <td>
                                                                ${format_incident_time(
                                                                        row.incident_datetime_raw
                                                                )}
                                                        </td>

                                                        <td>
                                                                ${
                                                                        firstPhoto
                                                                                ? `
                                                                                        <span class="iv-table-photo">
                                                                                                <img
                                                                                                        src="${escape_incident_html(
                                                                                                                firstPhoto
                                                                                                        )}"
                                                                                                        alt=""
                                                                                                        loading="lazy"
                                                                                                />

                                                                                                ${
                                                                                                        additional
                                                                                                                ? `<small>+${additional}</small>`
                                                                                                                : ""
                                                                                                }
                                                                                        </span>
                                                                                `
                                                                                : "—"
                                                                }
                                                        </td>
                                                </tr>
                                        `;
                                }
                        ).join("")
                );
}


function get_average_incident_resolution(
        rows
) {
        const durations = [];

        rows.forEach((row) => {
                if (
                        !row.incident_datetime_raw
                        || !row.resolution_datetime_raw
                ) {
                        return;
                }

                const start = new Date(
                        String(
                                row.incident_datetime_raw
                        ).replace(" ", "T")
                );

                const end = new Date(
                        String(
                                row.resolution_datetime_raw
                        ).replace(" ", "T")
                );

                const milliseconds =
                        end.getTime()
                        - start.getTime();

                if (
                        Number.isFinite(milliseconds)
                        && milliseconds >= 0
                ) {
                        durations.push(milliseconds);
                }
        });

        if (!durations.length) {
                return "—";
        }

        const average =
                durations.reduce(
                        (sum, duration) =>
                                sum + duration,
                        0
                )
                / durations.length;

        const totalMinutes = Math.round(
                average / 60000
        );

        const days = Math.floor(
                totalMinutes / 1440
        );

        const hours = Math.floor(
                (
                        totalMinutes % 1440
                )
                / 60
        );

        const minutes =
                totalMinutes % 60;

        if (days) {
                return `${days}d ${hours}h`;
        }

        if (hours) {
                return `${hours}h ${minutes}m`;
        }

        return `${minutes}m`;
}


function count_incident_values(
        rows,
        resolver
) {
        return rows.reduce(
                (counts, row) => {
                        const value =
                                resolver(row)
                                || __("Unknown");

                        counts[value] =
                                (
                                        counts[value]
                                        || 0
                                )
                                + 1;

                        return counts;
                },
                {}
        );
}


function get_incident_date_range(
        range,
        $root = null
) {
        const today = new Date();

        const to = format_incident_date(today);

        if (
                range === "custom"
                && $root
                && $root.length
        ) {
                return {
                        from:
                                $root
                                        .find(
                                                "#iv-date-from"
                                        )
                                        .val()
                                || to,

                        to:
                                $root
                                        .find(
                                                "#iv-date-to"
                                        )
                                        .val()
                                || to,
                };
        }

        let daysBack = 365;

        if (range === "today") {
                daysBack = 0;
        } else if (range === "7d") {
                daysBack = 6;
        } else if (range === "30d") {
                daysBack = 29;
        }

        const fromDate = new Date(today);

        fromDate.setDate(
                fromDate.getDate() - daysBack
        );

        return {
                from: format_incident_date(fromDate),
                to,
        };
}


function format_incident_date(date) {
        const year = date.getFullYear();

        const month = String(
                date.getMonth() + 1
        ).padStart(2, "0");

        const day = String(
                date.getDate()
        ).padStart(2, "0");

        return `${year}-${month}-${day}`;
}


function format_incident_time(value) {
        if (!value) {
                return "—";
        }

        const date = new Date(
                String(value).replace(" ", "T")
        );

        if (!Number.isFinite(date.getTime())) {
                return escape_incident_html(value);
        }

        return date.toLocaleTimeString(
                [],
                {
                        hour: "2-digit",
                        minute: "2-digit",
                }
        );
}


function make_incident_severity_badge(
        severity
) {
        const value = severity || "Not Set";

        const className = String(value)
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, "-");

        return `
                <span
                        class="iv-severity-badge iv-badge-${className}"
                >
                        ${escape_incident_html(value)}
                </span>
        `;
}


function make_incident_status_badge(
        status
) {
        const value = status || "Not Set";

        const className = String(value)
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, "-");

        return `
                <span
                        class="iv-status-badge iv-status-${className}"
                >
                        ${escape_incident_html(value)}
                </span>
        `;
}


function display_incident_value(value) {
        if (
                value === null
                || value === undefined
                || value === ""
        ) {
                return "—";
        }

        return escape_incident_html(value);
}


function escape_incident_html(value) {
        return String(
                value === null
                || value === undefined
                        ? ""
                        : value
        )
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
}


function update_incident_sidebar_badge(
        $root,
        count
) {
        const $link = $root.find(
                '[data-security-view="incidents"]'
        );

        const $badge = $link.find(
                ".security-sidebar-count"
        );

        if ($badge.length) {
                $badge.text(count);
        }
}


function export_incidents_csv(page) {
        const rows =
                page.security_incident_data
                ?.rows
                || [];

        const columns = [
                "Incident",
                "Date and Time",
                "Category",
                "Severity",
                "Status",
                "Location",
                "Reporter",
                "Assigned To",
                "Responsible Persons",
                "Victims",
                "Witnesses",
                "Evidence",
        ];

        const values = rows.map(
                (row) => [
                        row.name,
                        row.incident_datetime_raw,
                        row.nature_of_incident,
                        row.severity,
                        row.status,
                        row.location,
                        row.reporter_name
                                || row.reported_by,
                        row.assigned_to,
                        row.responsible_persons,
                        row.victims,
                        row.witnesses,
                        row.evidence_count,
                ]
        );

        const csv = [
                columns,
                ...values,
        ]
                .map(
                        (record) =>
                                record.map(
                                        csv_incident_value
                                ).join(",")
                )
                .join("\n");

        download_incident_file(
                csv,
                "incident-report.csv",
                "text/csv;charset=utf-8"
        );
}


function export_incidents_excel(page) {
        const rows =
                page.security_incident_data
                ?.rows
                || [];

        const body = rows.map(
                (row) => `
                        <tr>
                                <td>${escape_incident_html(
                                        row.name
                                )}</td>
                                <td>${escape_incident_html(
                                        row.incident_datetime_raw
                                        || ""
                                )}</td>
                                <td>${escape_incident_html(
                                        row.nature_of_incident
                                        || ""
                                )}</td>
                                <td>${escape_incident_html(
                                        row.severity || ""
                                )}</td>
                                <td>${escape_incident_html(
                                        row.status || ""
                                )}</td>
                                <td>${escape_incident_html(
                                        row.location || ""
                                )}</td>
                                <td>${escape_incident_html(
                                        row.reporter_name
                                        || row.reported_by
                                        || ""
                                )}</td>
                                <td>${escape_incident_html(
                                        row.assigned_to || ""
                                )}</td>
                        </tr>
                `
        ).join("");

        const workbook = `
                <html>
                        <head>
                                <meta charset="utf-8">
                        </head>

                        <body>
                                <table border="1">
                                        <thead>
                                                <tr>
                                                        <th>Incident</th>
                                                        <th>Date and Time</th>
                                                        <th>Category</th>
                                                        <th>Severity</th>
                                                        <th>Status</th>
                                                        <th>Location</th>
                                                        <th>Reporter</th>
                                                        <th>Assigned To</th>
                                                </tr>
                                        </thead>

                                        <tbody>
                                                ${body}
                                        </tbody>
                                </table>
                        </body>
                </html>
        `;

        download_incident_file(
                workbook,
                "incident-report.xls",
                "application/vnd.ms-excel"
        );
}


function csv_incident_value(value) {
        const text = String(
                value === null
                || value === undefined
                        ? ""
                        : value
        );

        return `"${text.replace(/"/g, '""')}"`;
}


function download_incident_file(
        content,
        filename,
        contentType
) {
        const blob = new Blob(
                [content],
                {
                        type: contentType,
                }
        );

        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");

        anchor.href = url;
        anchor.download = filename;

        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();

        URL.revokeObjectURL(url);
}


/* END INCIDENTS DASHBOARD VIEW */

/* BEGIN CLEAN SECURITY OVERVIEW */

function render_clean_security_overview(page) {
        const $root = $(page.main);
        const $content = $root.find(
                ".security-app-content"
        );

        if (!$content.length) {
                console.warn(
                        "Security dashboard content container was not found."
                );
                return;
        }

        page.security_overview_date =
                page.security_overview_date
                || get_security_overview_today();

        $content.html(`
                <div class="security-clean-overview usd-dash-v2">

                        <div class="usd-tabs">
                                <button
                                        type="button"
                                        class="usd-tab-btn active"
                                        data-tab="today"
                                >
                                        <svg
                                                viewBox="0 0 24 24"
                                                fill="none"
                                                stroke="currentColor"
                                                stroke-width="2"
                                                width="16"
                                                height="16"
                                        >
                                                <circle
                                                        cx="12"
                                                        cy="12"
                                                        r="10"
                                                ></circle>

                                                <polyline
                                                        points="12 6 12 12 16 14"
                                                ></polyline>
                                        </svg>

                                        ${__("Today")}
                                </button>

                                <button
                                        type="button"
                                        class="usd-tab-btn"
                                        data-tab="operations"
                                >
                                        <svg
                                                viewBox="0 0 24 24"
                                                fill="none"
                                                stroke="currentColor"
                                                stroke-width="2"
                                                width="16"
                                                height="16"
                                        >
                                                <polygon
                                                        points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"
                                                ></polygon>

                                                <line
                                                        x1="8"
                                                        y1="2"
                                                        x2="8"
                                                        y2="18"
                                                ></line>

                                                <line
                                                        x1="16"
                                                        y1="6"
                                                        x2="16"
                                                        y2="22"
                                                ></line>
                                        </svg>

                                        ${__("Operations")}
                                </button>
                        </div>

                        <div
                                class="usd-tab-content active"
                                id="usd-tab-today"
                        >
                                <div class="usd-header">
                                        <div class="usd-header-left">
                                                <h3 class="usd-title">
                                                        ${__(
                                                                "Security Operations"
                                                        )}
                                                </h3>

                                                <span
                                                        class="usd-subtitle"
                                                        id="usd-date-display"
                                                >
                                                        ${escape_security_overview_html(
                                                                format_security_overview_long_date(
                                                                        page.security_overview_date
                                                                )
                                                        )}
                                                </span>
                                        </div>

                                        <div class="usd-header-right">
                                                <input
                                                        type="date"
                                                        id="usd-date-input"
                                                        class="usd-filter-input"
                                                        value="${escape_security_overview_html(
                                                                page.security_overview_date
                                                        )}"
                                                />

                                                <button
                                                        type="button"
                                                        class="usd-refresh-btn"
                                                        id="usd-refresh-btn"
                                                >
                                                        <svg
                                                                viewBox="0 0 24 24"
                                                                fill="none"
                                                                stroke="currentColor"
                                                                stroke-width="2"
                                                                width="16"
                                                                height="16"
                                                        >
                                                                <polyline
                                                                        points="23 4 23 10 17 10"
                                                                ></polyline>

                                                                <polyline
                                                                        points="1 20 1 14 7 14"
                                                                ></polyline>

                                                                <path
                                                                        d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10"
                                                                ></path>

                                                                <path
                                                                        d="M20.49 15a9 9 0 0 1-14.85 3.36L1 14"
                                                                ></path>
                                                        </svg>

                                                        ${__("Refresh")}
                                                </button>
                                        </div>
                                </div>

                                <div class="usd-stats-grid">

                                        ${make_security_overview_stat(
                                                "usd-kpi-guards",
                                                __("Guards Assigned"),
                                                __("active assignments"),
                                                "guards"
                                        )}

                                        ${make_security_overview_stat(
                                                "usd-kpi-visitors",
                                                __("Visitors On Site"),
                                                __("currently checked in"),
                                                "visitors"
                                        )}

                                        ${make_security_overview_stat(
                                                "usd-kpi-contractors",
                                                __("Contractors On Site"),
                                                __("currently checked in"),
                                                "contractors"
                                        )}

                                        ${make_security_overview_stat(
                                                "usd-kpi-vehicles",
                                                __("Vehicles On Site"),
                                                __("vehicles and motorcycles"),
                                                "vehicles"
                                        )}

                                        ${make_security_overview_stat(
                                                "usd-kpi-incidents",
                                                __("Open Incidents"),
                                                __("requiring attention"),
                                                "incidents"
                                        )}

                                        ${make_security_overview_stat(
                                                "usd-kpi-patrols",
                                                __("Active Patrols"),
                                                __("recent GPS activity"),
                                                "patrols"
                                        )}

                                </div>

                                <div
                                        class="usd-insights-bar"
                                        id="usd-insights"
                                >
                                        ${make_security_overview_insight(
                                                "usd-insight-scheduled",
                                                __("Scheduled Visitors")
                                        )}

                                        ${make_security_overview_insight(
                                                "usd-insight-pending",
                                                __("Pending Host Review")
                                        )}

                                        ${make_security_overview_insight(
                                                "usd-insight-stale",
                                                __("Stale Patrols")
                                        )}

                                        ${make_security_overview_insight(
                                                "usd-insight-critical",
                                                __("Critical Incidents")
                                        )}

                                        ${make_security_overview_insight(
                                                "usd-insight-motorcycles",
                                                __("Motorcycles On Site")
                                        )}

                                        <span
                                                class="usd-last-updated"
                                                id="usd-last-updated"
                                        >
                                                ${__(
                                                        "Awaiting live data"
                                                )}
                                        </span>
                                </div>
                        </div>

                        <div
                                class="usd-tab-content"
                                id="usd-tab-operations"
                        >
                                <div class="usd-nav-grid">

                                        ${make_security_overview_nav_card({
                                                title:
                                                        __("Patrol Tracking"),
                                                description:
                                                        __(
                                                                "Live patrol positions and GPS activity"
                                                        ),
                                                icon:
                                                        "patrols",
                                                targetView:
                                                        "patrols",
                                        })}

                                        ${make_security_overview_nav_card({
                                                title:
                                                        __("Incident Operations"),
                                                description:
                                                        __(
                                                                "Reported incidents, severity and resolution"
                                                        ),
                                                icon:
                                                        "incidents",
                                                targetView:
                                                        "incidents",
                                        })}

                                        ${make_security_overview_nav_card({
                                                title:
                                                        __("Visitor Management"),
                                                description:
                                                        __(
                                                                "Appointments, check-ins and check-outs"
                                                        ),
                                                icon:
                                                        "visitors",
                                                targetView:
                                                        "visitors",
                                        })}

                                        ${make_security_overview_nav_card({
                                                title:
                                                        __("Contractor Management"),
                                                description:
                                                        __(
                                                                "Contractor appointments and site access"
                                                        ),
                                                icon:
                                                        "contractors",
                                                targetView:
                                                        "contractors",
                                                disabled:
                                                        true,
                                        })}

                                        ${make_security_overview_nav_card({
                                                title:
                                                        __("Movement Log"),
                                                description:
                                                        __(
                                                                "Visitor, contractor and vehicle movement"
                                                        ),
                                                icon:
                                                        "movement",
                                                targetView:
                                                        "movement",
                                                disabled:
                                                        true,
                                        })}

                                        ${make_security_overview_nav_card({
                                                title:
                                                        __("Security Reports"),
                                                description:
                                                        __(
                                                                "Analytics and operational reports"
                                                        ),
                                                icon:
                                                        "reports",
                                                targetView:
                                                        "reports",
                                                disabled:
                                                        true,
                                        })}

                                </div>
                        </div>
                </div>
        `);

        bind_security_overview_standard_events(page);

        if (
                typeof load_security_overview
                === "function"
        ) {
                load_security_overview(page);
        }
}


function make_security_overview_stat(
        elementId,
        label,
        unit,
        type
) {
        const icons = {
                guards: `
                        <svg viewBox="0 0 24 24">
                                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                        </svg>
                `,

                visitors: `
                        <svg viewBox="0 0 24 24">
                                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                                <circle cx="9" cy="7" r="4"></circle>
                                <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
                                <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
                        </svg>
                `,

                contractors: `
                        <svg viewBox="0 0 24 24">
                                <rect x="3" y="7" width="18" height="13" rx="2"></rect>
                                <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                <line x1="3" y1="12" x2="21" y2="12"></line>
                        </svg>
                `,

                vehicles: `
                        <svg viewBox="0 0 24 24">
                                <path d="M3 17h18"></path>
                                <path d="M5 17l1-5h12l1 5"></path>
                                <path d="M7 12l2-5h6l2 5"></path>
                                <circle cx="7" cy="18" r="2"></circle>
                                <circle cx="17" cy="18" r="2"></circle>
                        </svg>
                `,

                incidents: `
                        <svg viewBox="0 0 24 24">
                                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                                <line x1="12" y1="9" x2="12" y2="13"></line>
                                <line x1="12" y1="17" x2="12.01" y2="17"></line>
                        </svg>
                `,

                patrols: `
                        <svg viewBox="0 0 24 24">
                                <circle cx="12" cy="12" r="10"></circle>
                                <polyline points="12 6 12 12 16 14"></polyline>
                        </svg>
                `,
        };

        return `
                <div class="usd-stat-card usd-${type}">
                        <div class="usd-stat-icon">
                                ${icons[type] || ""}
                        </div>

                        <div class="usd-stat-body">
                                <div class="usd-stat-label">
                                        ${label}
                                </div>

                                <div
                                        class="usd-stat-value"
                                        id="${elementId}"
                                >
                                        —
                                </div>

                                <div class="usd-stat-unit">
                                        ${unit}
                                </div>
                        </div>
                </div>
        `;
}


function make_security_overview_insight(
        elementId,
        label
) {
        return `
                <div class="usd-insight-item">
                        <span class="usd-insight-dot"></span>

                        <span class="usd-insight-label">
                                ${label}
                        </span>

                        <strong
                                class="usd-insight-value"
                                id="${elementId}"
                        >
                                —
                        </strong>
                </div>
        `;
}


function make_security_overview_nav_card({
        title,
        description,
        icon,
        targetView,
        disabled = false,
}) {
        const icons = {
                patrols: `
                        <path d="M12 2a10 10 0 1 0 10 10"></path>
                        <polyline points="12 6 12 12 16 14"></polyline>
                `,

                incidents: `
                        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                        <line x1="12" y1="9" x2="12" y2="13"></line>
                        <line x1="12" y1="17" x2="12.01" y2="17"></line>
                `,

                visitors: `
                        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                        <circle cx="9" cy="7" r="4"></circle>
                `,

                contractors: `
                        <rect x="3" y="7" width="18" height="13" rx="2"></rect>
                        <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                `,

                movement: `
                        <polyline points="16 3 21 3 21 8"></polyline>
                        <line x1="4" y1="20" x2="21" y2="3"></line>
                        <polyline points="21 16 21 21 16 21"></polyline>
                        <line x1="15" y1="15" x2="21" y2="21"></line>
                        <line x1="4" y1="4" x2="9" y2="9"></line>
                `,

                reports: `
                        <line x1="18" y1="20" x2="18" y2="10"></line>
                        <line x1="12" y1="20" x2="12" y2="4"></line>
                        <line x1="6" y1="20" x2="6" y2="14"></line>
                `,
        };

        const disabledClass =
                disabled ? "disabled" : "";

        const statusText =
                disabled
                        ? `<small>${__("Coming soon")}</small>`
                        : "";

        return `
                <button
                        type="button"
                        class="usd-nav-card ${disabledClass}"
                        data-target-view="${escape_security_overview_html(
                                targetView
                        )}"
                        ${disabled ? "disabled" : ""}
                >
                        <div
                                class="usd-nav-icon usd-nav-${icon}"
                        >
                                <svg
                                        viewBox="0 0 24 24"
                                        fill="none"
                                        stroke="currentColor"
                                        stroke-width="2"
                                        width="22"
                                        height="22"
                                >
                                        ${icons[icon] || ""}
                                </svg>
                        </div>

                        <div class="usd-nav-body">
                                <div class="usd-nav-title">
                                        ${title}
                                </div>

                                <div class="usd-nav-desc">
                                        ${description}
                                </div>

                                ${statusText}
                        </div>

                        <svg
                                class="usd-nav-arrow"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                stroke-width="2"
                                width="16"
                                height="16"
                        >
                                <polyline
                                        points="9 18 15 12 9 6"
                                ></polyline>
                        </svg>
                </button>
        `;
}


function bind_security_overview_standard_events(
        page
) {
        const $root = $(page.main);

        $root.off(".securityOverviewStandard");

        $root.on(
                "click.securityOverviewStandard",
                ".usd-tab-btn",
                function () {
                        const tab = $(this).attr(
                                "data-tab"
                        );

                        $root
                                .find(".usd-tab-btn")
                                .removeClass("active");

                        $(this).addClass("active");

                        $root
                                .find(".usd-tab-content")
                                .removeClass("active");

                        $root
                                .find(`#usd-tab-${tab}`)
                                .addClass("active");
                }
        );

        $root.on(
                "change.securityOverviewStandard",
                "#usd-date-input",
                function () {
                        page.security_overview_date =
                                $(this).val()
                                || get_security_overview_today();

                        $root
                                .find("#usd-date-display")
                                .text(
                                        format_security_overview_long_date(
                                                page.security_overview_date
                                        )
                                );

                        if (
                                typeof load_security_overview
                                === "function"
                        ) {
                                load_security_overview(page);
                        }
                }
        );

        $root.on(
                "click.securityOverviewStandard",
                "#usd-refresh-btn",
                async function () {
                        const $button = $(this);

                        $button.prop(
                                "disabled",
                                true
                        );

                        $root
                                .find(".usd-stat-card")
                                .addClass("loading");

                        try {
                                if (
                                        typeof load_security_overview
                                        === "function"
                                ) {
                                        await Promise.resolve(
                                                load_security_overview(
                                                        page
                                                )
                                        );
                                } else {
                                        frappe.show_alert({
                                                message:
                                                        __(
                                                                "Overview data connection will be added next"
                                                        ),
                                                indicator:
                                                        "blue",
                                        });
                                }
                        } finally {
                                $button.prop(
                                        "disabled",
                                        false
                                );

                                $root
                                        .find(
                                                ".usd-stat-card"
                                        )
                                        .removeClass(
                                                "loading"
                                        );
                        }
                }
        );

        $root.on(
                "click.securityOverviewStandard",
                ".usd-nav-card:not(.disabled)",
                function () {
                        const targetView = $(this).attr(
                                "data-target-view"
                        );

                        if (
                                targetView
                                && typeof show_security_view
                                        === "function"
                        ) {
                                show_security_view(
                                        page,
                                        targetView
                                );
                        }
                }
        );
}


function get_security_overview_today() {
        if (
                frappe.datetime
                && frappe.datetime.get_today
        ) {
                return frappe.datetime.get_today();
        }

        const today = new Date();

        const year = today.getFullYear();

        const month = String(
                today.getMonth() + 1
        ).padStart(2, "0");

        const day = String(
                today.getDate()
        ).padStart(2, "0");

        return `${year}-${month}-${day}`;
}


function format_security_overview_long_date(
        value
) {
        if (!value) {
                return "";
        }

        const date = new Date(
                `${value}T00:00:00`
        );

        if (!Number.isFinite(date.getTime())) {
                return String(value);
        }

        return date.toLocaleDateString(
                [],
                {
                        weekday: "long",
                        year: "numeric",
                        month: "long",
                        day: "numeric",
                }
        );
}


function escape_security_overview_html(value) {
        return String(
                value === null
                || value === undefined
                        ? ""
                        : value
        )
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
}

/* END CLEAN SECURITY OVERVIEW */

