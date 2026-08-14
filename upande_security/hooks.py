app_name = "upande_security"
app_title = "Upande Security"
app_publisher = "dev@upande.com"
app_description = "Upande Security app"
app_email = "dev@upande.com"
app_license = "mit"

# Apps
# ------------------

# erpnext supplies Employee, Supplier, Timesheet, Asset, Location and Driver;
# hrms supplies Attendance and Shift Type. Both are read or written by this
# module's server scripts, so an install without them is broken on arrival.
# upande_kaitet is deliberately NOT listed: it provides Farm and Tractor Daily
# Task here, but krv16 sources Farm from upande_core and has no Tractor Daily
# Task at all, so requiring it would block a valid deployment.
required_apps = ["erpnext", "hrms"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "upande_security",
# 		"logo": "/assets/upande_security/logo.png",
# 		"title": "Upande Security",
# 		"route": "/upande_security",
# 		"has_permission": "upande_security.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/upande_security/css/upande_security.css"
# app_include_js = "/assets/upande_security/js/upande_security.js"

# include js, css files in header of web template
# web_include_css = "/assets/upande_security/css/upande_security.css"
# web_include_js = "/assets/upande_security/js/upande_security.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "upande_security/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "upande_security/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "upande_security.utils.jinja_methods",
# 	"filters": "upande_security.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "upande_security.install.before_install"
# after_install = "upande_security.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "upande_security.uninstall.before_uninstall"
# after_uninstall = "upande_security.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "upande_security.utils.before_app_install"
# after_app_install = "upande_security.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "upande_security.utils.before_app_uninstall"
# after_app_uninstall = "upande_security.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "upande_security.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "upande_security.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Runs at the very end of every `bench migrate`, after fixture sync -
# keeps the Security Workspace's native shortcuts matched to whichever
# doctypes this app actually owns at that moment, dynamically (not a
# hardcoded list), on every site this app deploys to. See
# sync_workspace.py's own docstring for why this has to be after_migrate
# and not a one-time patch.
after_migrate = [
	"upande_security.sync_workspace.sync_shortcuts",
]

doc_events = {
	"Attendance": {
		"after_insert": "upande_security.api.guard_checkin.sync_shift_checkin",
		"on_update": "upande_security.api.guard_checkin.sync_shift_checkin",
	},
	"Visitor Badge": {
		"after_insert": "upande_security.api.visitor_badge_qr.generate_qr_for_badge",
	},
	# Auto-provision the Company/Farm User Permission rows the hierarchical
	# access scoping (Patrol Report, Near Miss Report, Patrol GPS Log,
	# Incident Report, Security Asset, Visitor Badge, Attendance, ...)
	# depends on to actually restrict a Security Head/guard to their own
	# company/farm instead of being silently unrestricted.
	"Employee": {
		"validate": "upande_security.api.user_permission_sync.sync_from_employee",
	},
	"Security Guard": {
		"validate": "upande_security.api.user_permission_sync.sync_from_security_guard",
	},
	# Stamp Farm onto doctypes that otherwise carry no link back to a
	# company/farm, so a Security Head's DocPerm row on them can actually
	# be scoped by the standard Frappe Link + User Permission engine.
	"Patrol GPS Log": {
		"before_insert": "upande_security.api.scoping.stamp_patrol_gps_log_farm",
	},
	"Incident Report": {
		"before_insert": "upande_security.api.scoping.stamp_incident_report_farm",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
    "cron": {
        "*/15 * * * *": [
            # Live check on every Active shift: flag a guard who's gone
            # quiet (no GPS ping in 30 min) and, separately, one whose last
            # ping falls outside their assigned farm's boundary.
            "upande_security.tasks.check_patrol_geofence_and_gaps",
        ],
    },
    "hourly": [
        # A shift that merely elapses is never saved again, so its status has to
        # be advanced on a timer: Scheduled -> Active -> Ended.
        "upande_security.tasks.refresh_shift_statuses",
    ],
    "daily": [
        # Pulls today's on-duty guards from HR's own roster (Shift Type +
        # Shift Assignment) into Security Guard Shift Assignment, so
        # Security never re-plans what HR already scheduled and never
        # rosters a guard HR has them down as off.
        "upande_security.tasks.sync_shifts_from_hr_roster",
        # Warns Security Heads/System Managers about contractor compliance
        # documents (insurance, safety certs, permits) expiring within 14
        # days or already expired.
        "upande_security.tasks.check_contractor_document_expiry",
        # Nags the assignee + Security Heads/System Managers about any
        # Incident Report corrective action (CAPA) past its due date and
        # still not Completed.
        "upande_security.tasks.check_overdue_capa_actions",
    ],
}

# Testing
# -------

# before_tests = "upande_security.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "upande_security.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "upande_security.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "upande_security.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["upande_security.utils.before_request"]
# after_request = ["upande_security.utils.after_request"]

# Job Events
# ----------
# before_job = ["upande_security.utils.before_job"]
# after_job = ["upande_security.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"upande_security.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

fixtures = [
    {
        "dt": "Web Page",
        "filters": [
            ["route", "in", ["security-dashboard", "patrol-map"]],
        ],
    },
    {
        "dt": "Server Script",
        "filters": [
            ["module", "=", "Upande Security"],
        ],
    },
    {
        "dt": "Client Script",
        "filters": [
            ["module", "=", "Upande Security"],
        ],
    },
    {
        # Custom Fields are enumerated by name, not swept up by `dt`.
        #
        # Two reasons. Filtering Employee/Supplier/Timesheet by `dt` scoops up
        # every other team's customizations — Employee alone carries 200+
        # payroll and HR fields that this app must never ship. And a second
        # fixture entry cannot be used to separate the two sets, because every
        # entry for a doctype writes the same custom_field.json and the last
        # one silently wins.
        #
        # Cost: adding a custom field means adding it here too.
        "dt": "Custom Field",
        "filters": [
            [
                "name",
                "in",
                [
                    "Appointment-custom_meet_with",
                    "Appointment-workflow_state",
                    "Appointment-custom_host_whatsapp_no",
                    "Appointment-custom_company",
                    "Appointment-custom_farmunit",
                    "Appointment-custom_visit_purpose",
                    "Appointment-custom_number_of_passengers",
                    "Appointment-custom_mode_of_transport",
                    "Appointment-custom_vehicles_number_plate",
                    "Appointment-custom_vehicles_colour",
                    "Appointment-custom_motorcycles_plate",
                    "Appointment-custom_visitor_type",
                    "Appointment-custom_check_in_and_check_out",
                    "Appointment-custom_check_in_time",
                    "Appointment-custom_check_out_time",
                    "Appointment-custom_temp_exit_time",
                    "Appointment-custom_reporting_status",
                    "Appointment-custom_temp_exit_log",
                    "Appointment-custom_visitorcontractor_tab",
                    "Appointment-custom_contractor_ref",
                    "Appointment-custom_customer",
                    "Appointment-custom_scope_of_work",
                    "Appointment-custom_expected_exit",
                    "Appointment-custom_contractor_personnel",
                    "Appointment-custom_taxi_driver_check_out_time",
                    "Appointment-custom_id_number",
                    "Appointment-custom_visitor_badge",
                    "Appointment-custom_host_received_time",
                    "Attendance-custom_gate_app_entry",
                    "Attendance-custom_temp_exit_time",
                    "Attendance-custom_temp_exit_log",
                    "Attendance-custom_farm",
                    "Attendance-custom_mode_of_transport",
                    "Attendance-custom_employee_category",
                    "Attendance-custom_vehicle_number_plate",
                    "Employee-custom_farm",
                    "Employee-default_shift",
                    "Supplier-custom_is_contractor",
                    "Supplier-custom_access_start_date",
                    "Supplier-custom_access_end_date",
                    "Supplier-custom_approval_date",
                    "Supplier-custom_approved_by",
                    "Supplier-custom_compliance_documents",
                    "Timesheet-custom_asset",
                ],
            ],
        ],
    },
    {
        "dt": "Custom HTML Block",
        "filters": [
            ["name", "=", "Security Navigation"],
        ],
    },
    {
        # The workspace shell itself (the left-sidebar entry in Desk) — without
        # this, "Security Navigation" (the Custom HTML Block above) has nothing
        # to render inside on a fresh site. Missing this fixture is exactly why
        # the workspace didn't show up in Desk after a fresh deploy.
        "dt": "Workspace",
        "filters": [
            ["name", "=", "Security"],
        ],
    },
    {
        # Single doctype — its child-table rows (dispatch_sources config,
        # among others) are real data, not field defaults, so they need an
        # actual fixture record or a fresh deploy ships with none configured.
        "dt": "Security Ops Settings",
        "filters": [
            ["name", "=", "Security Ops Settings"],
        ],
    },
    {
        # Master data, not per-site business records: mirrors the static
        # options list on Incident Report.nature_of_incident (a plain
        # Select, not a Link to this doctype) so the mobile app's category
        # picker - which sources its options from here via
        # list_incident_categories, not from the Select's own option list -
        # has something to show. Without this fixture, Incident Category
        # ships empty on every fresh deploy and the picker is blank, same
        # bug class as the Workspace-shortcuts gap.
        "dt": "Incident Category",
    },
    {
        # Security Asset and Visitor Badge were built via the Desk UI
        # (DocType.custom = 1) rather than as an app-owned doctype .json,
        # so unlike Patrol Report/Incident Report/etc. their schema (fields,
        # permissions) lives only in the DB. Without this they — and any
        # DocPerm fix made to them — would silently vanish on a fresh
        # deploy, the same class of bug the Security workspace hit before.
        "dt": "DocType",
        "filters": [
            ["name", "in", ["Security Asset", "Visitor Badge"]],
        ],
    },
    {
        # The badge itself (built via Desk's Print Format builder, DB-only,
        # same class of gap as the Workspace/DocType entries above) - the
        # Visitor Badge doctype ships fine without this, there's just
        # nothing to actually render one on a fresh deploy.
        "dt": "Print Format",
        "filters": [
            ["name", "=", "Visitor Badge Card"],
        ],
    },
    {
        # Appointment is a core CRM doctype, not owned by this app - these
        # are label-only overrides (Property Setters) on two of its native
        # fields, not new fields, so this uses `name`, not `dt`-wide, same
        # reasoning as the Custom Field allowlist above: a `dt`-wide filter
        # on Appointment would sweep up every other team's Property
        # Setters on this same widely-shared doctype.
        "dt": "Property Setter",
        "filters": [
            [
                "name",
                "in",
                [
                    "Appointment-details_section-label",
                    "Appointment-customer_details-label",
                ],
            ],
        ],
    },
    {
        # The Secretary role, needed for the Appointment visitor-review
        # workflow below (Approve/Reject/Redirect/Reschedule). Filtered by
        # name, not swept up by `dt`, for the same reason every other role
        # already assigned in this system (Gate Guard, Security Head) is
        # never fixture-tracked wholesale — a `dt`-wide Role export would
        # ship every role on the site, including ones owned by HR/ERPNext.
        "dt": "Role",
        "filters": [
            ["name", "in", ["Secretary"]],
        ],
    },
    {
        # The Appointment visitor-review Workflow. Before this existed,
        # Desk showed zero workflow action buttons to anyone (Administrator
        # included) despite "Appointment Gate Workflow Actions" (the Client
        # Script above) having full before_workflow_action handlers for
        # Approve/Reject/Redirect/Reschedule/Confirm Check In/Confirm Check
        # Out - a Workflow document defining real states/transitions for
        # those exact action names never existed, so the handlers could
        # never fire for anyone. Workflow Transition and Workflow Document
        # State are child tables of Workflow and export automatically with
        # it - no separate fixture entry needed for either.
        "dt": "Workflow",
        "filters": [
            ["name", "in", ["Appointment Visitor Review"]],
        ],
    },
    {
        # Grants the new Secretary role base read/write/create on Appointment
        # (permlevel 0) - a Workflow Transition's `allowed` role can only
        # ever narrow an already-granted base permission, never create one,
        # so without this row Secretary users get a bare PermissionError
        # the moment Desk asks for available workflow actions, before the
        # workflow engine's own role/condition check is ever reached.
        # Custom DocPerm names are random per-site hashes (e.g. "qfbl7t58a9"),
        # not portable across environments, so this is filtered on the
        # stable (parent, role) pair instead of `name`.
        "dt": "Custom DocPerm",
        "filters": [
            ["parent", "=", "Appointment"],
            ["role", "=", "Secretary"],
        ],
    },
]

