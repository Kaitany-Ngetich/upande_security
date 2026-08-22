from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import get_datetime


@frappe.whitelist()
def get_visitors_dashboard(
    company: str | None = None,
    farm: str | None = None,
    status: str | None = None,
    transport: str | None = None,
    search: str | None = None,
    start: int | str = 0,
    page_length: int | str = 50,
) -> dict[str, Any]:
    """
    Return Appointment records for the Visitors dashboard.

    Contractor appointments are excluded where the Appointment With
    field is available.
    """

    if not frappe.has_permission("Appointment", ptype="read"):
        frappe.throw(
            _("You do not have permission to view Appointments."),
            frappe.PermissionError,
        )

    meta = frappe.get_meta("Appointment")
    field_map = get_appointment_field_map(meta)

    base_filters: dict[str, Any] = {}

    appointment_type_field = field_map["appointment_type"]

    if appointment_type_field:
        base_filters[appointment_type_field] = ["!=", "Contractor"]

    if company and company not in {
        "All companies",
        "All Companies",
    }:
        company_field = field_map["company"]

        if company_field:
            base_filters[company_field] = company

    if farm and farm not in {
        "All farms/units",
        "All Farms/Units",
        "All Sites",
    }:
        farm_field = field_map["farm"]

        if farm_field:
            base_filters[farm_field] = farm

    summary = get_visitor_summary(
        base_filters=base_filters,
        status_field=field_map["status"],
    )

    row_filters = dict(base_filters)

    status_field = field_map["status"]
    transport_field = field_map["transport"]

    if status and status != "All statuses" and status_field:
        row_filters[status_field] = status

    if (
        transport
        and transport != "All transport"
        and transport_field
    ):
        row_filters[transport_field] = transport

    or_filters: list[list[Any]] = []

    if search:
        search_value = f"%{search.strip()}%"

        for fieldname in [
            field_map["visitor_name"],
            field_map["meet_with"],
            field_map["phone"],
            field_map["email"],
            field_map["plate"],
        ]:
            if fieldname:
                or_filters.append(
                    [fieldname, "like", search_value]
                )

        or_filters.append(["name", "like", search_value])

    query_fields = [
        "name",
        "creation",
        "modified",
    ]

    for fieldname in field_map.values():
        if fieldname and fieldname not in query_fields:
            query_fields.append(fieldname)

    order_field = (
        field_map["scheduled_time"]
        or field_map["check_in"]
        or "modified"
    )

    records = frappe.get_list(
        "Appointment",
        filters=row_filters,
        or_filters=or_filters or None,
        fields=query_fields,
        order_by=f"{order_field} desc",
        start=max(int(start or 0), 0),
        page_length=min(max(int(page_length or 50), 1), 200),
    )

    filtered_total = permission_aware_count(
        filters=row_filters,
        or_filters=or_filters,
    )

    rows = [
        normalise_appointment(record, field_map)
        for record in records
    ]

    return {
        "summary": summary,
        "rows": rows,
        "filtered_total": filtered_total,
        "status_options": get_distinct_options(
            field_map["status"],
            base_filters,
        ),
        "transport_options": get_distinct_options(
            field_map["transport"],
            base_filters,
        ),
        "field_map": field_map,
    }


def get_appointment_field_map(meta) -> dict[str, str | None]:
    return {
        "visitor_name": first_field(
            meta,
            [
                "customer_name",
                "visitor_name",
                "full_name",
                "party_name",
                "contact_name",
            ],
            [
                "Name",
                "Visitor Name",
                "Customer Name",
            ],
        ),
        "meet_with": first_field(
            meta,
            [
                "custom_meet_with",
                "meeting_with",
                "meet_with",
                "custom_host",
                "host",
                "party",
            ],
            [
                "Meet With",
                "Host",
            ],
        ),
        "transport": first_field(
            meta,
            [
                "custom_mode_of_transport",
                "mode_of_transport",
                "transport_mode",
            ],
            [
                "Mode of Transport",
                "Transport",
            ],
        ),
        "plate": first_field(
            meta,
            [
                "custom_vehicles_number_plate",
                "custom_vehicle_number_plate",
                "vehicles_number_plate",
                "motorcycles_plate",
                "vehicle_number_plate",
                "registration_number",
                "vehicle_number",
            ],
            [
                "Vehicle Number Plate",
                "Number Plate",
                "Plate",
            ],
        ),
        "check_in": first_field(
            meta,
            [
                "custom_check_in",
                "custom_check_in_time",
                "check_in",
                "checkin",
                "check_in_time",
            ],
            [
                "Check In",
                "Check In Time",
            ],
        ),
        "check_out": first_field(
            meta,
            [
                "custom_check_out",
                "custom_check_out_time",
                "check_out",
                "checkout",
                "check_out_time",
            ],
            [
                "Check Out",
                "Check Out Time",
            ],
        ),
        "status": first_field(
            meta,
            [
                "workflow_state",
                "status",
            ],
            [
                "Workflow State",
                "Status",
            ],
        ),
        "scheduled_time": first_field(
            meta,
            [
                "scheduled_time",
                "appointment_time",
                "appointment_date",
            ],
            [
                "Scheduled Time",
            ],
        ),
        "appointment_type": first_field(
            meta,
            [
                "appointment_with",
                "party_type",
                "custom_visitor_type",
                "visitor_type",
            ],
            [
                "Appointment With",
                "Visitor Type",
            ],
        ),
        "company": first_field(
            meta,
            [
                "company",
                "compan",
                "custom_company",
            ],
            [
                "Company",
            ],
        ),
        "farm": first_field(
            meta,
            [
                "custom_farm",
                "custom_farm_unit",
                "farm",
                "farmunit",
                "farm_unit",
                "site",
            ],
            [
                "Farm/Unit",
                "Farm / Unit",
                "Farm",
                "Site",
            ],
        ),
        "phone": first_field(
            meta,
            [
                "customer_phone_number",
                "phone_number",
                "mobile_no",
                "phone",
            ],
            [
                "Phone Number",
                "Mobile Number",
            ],
        ),
        "email": first_field(
            meta,
            [
                "customer_email",
                "email",
                "email_id",
            ],
            [
                "Email",
                "Email Address",
            ],
        ),
    }


def first_field(
    meta,
    fieldnames: list[str],
    labels: list[str] | None = None,
) -> str | None:
    for fieldname in fieldnames:
        if meta.has_field(fieldname):
            return fieldname

    normalised_labels = {
        normalise_label(label)
        for label in (labels or [])
    }

    for field in meta.fields:
        if normalise_label(field.label) in normalised_labels:
            return field.fieldname

    return None


def normalise_label(value: str | None) -> str:
    return " ".join(
        str(value or "").strip().lower().split()
    )


def get_visitor_summary(
    base_filters: dict[str, Any],
    status_field: str | None,
) -> dict[str, int]:
    summary = {
        "total": 0,
        "checked_in": 0,
        "checked_out": 0,
        "scheduled": 0,
    }

    if not status_field:
        summary["total"] = permission_aware_count(
            filters=base_filters
        )
        return summary

    status_groups = frappe.get_list(
        "Appointment",
        filters=base_filters,
        fields=[
            status_field,
            {"COUNT": "name", "as": "record_count"},
        ],
        group_by=status_field,
        page_length=1000,
    )

    for row in status_groups:
        state = str(row.get(status_field) or "")
        count = int(row.get("record_count") or 0)
        normalised = state.lower().strip()

        summary["total"] += count

        if "checked in" in normalised:
            summary["checked_in"] += count

        elif "checked out" in normalised:
            summary["checked_out"] += count

        elif any(
            phrase in normalised
            for phrase in [
                "scheduled",
                "approved",
                "rescheduled",
                "open",
            ]
        ):
            summary["scheduled"] += count

    return summary


def permission_aware_count(
    filters: dict[str, Any],
    or_filters: list[list[Any]] | None = None,
) -> int:
    result = frappe.get_list(
        "Appointment",
        filters=filters,
        or_filters=or_filters or None,
        fields=[{"COUNT": "name", "as": "record_count"}],
        page_length=1,
    )

    if not result:
        return 0

    return int(result[0].get("record_count") or 0)


def get_distinct_options(
    fieldname: str | None,
    filters: dict[str, Any],
) -> list[str]:
    if not fieldname:
        return []

    records = frappe.get_list(
        "Appointment",
        filters={
            **filters,
            fieldname: ["is", "set"],
        },
        fields=[fieldname],
        group_by=fieldname,
        order_by=fieldname,
        page_length=200,
    )

    return [
        row.get(fieldname)
        for row in records
        if row.get(fieldname)
    ]


def normalise_appointment(
    record,
    fields: dict[str, str | None],
) -> dict[str, Any]:
    check_in = value_from(record, fields["check_in"])
    check_out = value_from(record, fields["check_out"])
    status = value_from(record, fields["status"])

    return {
        "name": record.name,
        "visitor_name": (
            value_from(record, fields["visitor_name"])
            or record.name
        ),
        "meet_with": value_from(
            record,
            fields["meet_with"],
        ),
        "transport": value_from(
            record,
            fields["transport"],
        ),
        "plate": value_from(
            record,
            fields["plate"],
        ),
        "check_in": format_time(check_in),
        "check_out": format_time(check_out),
        "duration": calculate_duration(
            check_in,
            check_out,
        ),
        "status": clean_status(status),
        "raw_status": status,
        "scheduled_time": format_datetime(
            value_from(
                record,
                fields["scheduled_time"],
            )
        ),
    }


def value_from(record, fieldname: str | None):
    if not fieldname:
        return None

    return record.get(fieldname)


def clean_status(value) -> str:
    status = str(value or "")

    if status.startswith("Visitor "):
        status = status[len("Visitor "):]

    return status or "Not Set"


def format_time(value) -> str:
    if not value:
        return ""

    try:
        return get_datetime(value).strftime("%H:%M")
    except Exception:
        return str(value)


def format_datetime(value) -> str:
    if not value:
        return ""

    try:
        return get_datetime(value).strftime(
            "%d %b %Y %H:%M"
        )
    except Exception:
        return str(value)


def calculate_duration(check_in, check_out) -> str:
    if not check_in or not check_out:
        return ""

    try:
        start = get_datetime(check_in)
        end = get_datetime(check_out)
        seconds = max(int((end - start).total_seconds()), 0)
    except Exception:
        return ""

    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60

    if hours:
        return f"{hours}h {minutes}m"

    return f"{minutes}m"

# BEGIN PATROL DASHBOARD API

@frappe.whitelist()
def get_patrols_dashboard(
    date: str | None = None,
    personnel: str | None = None,
    search: str | None = None,
    active_window_minutes: int | str = 15,
) -> dict[str, Any]:
    """
    Return live Patrol GPS Log information for the patrol dashboard.

    One dashboard row represents one distinct patrol ID. The row uses
    the most recent GPS point recorded for that patrol.
    """

    doctype = "Patrol GPS Log"

    if not frappe.has_permission(doctype, ptype="read"):
        frappe.throw(
            _("You do not have permission to view Patrol GPS Logs."),
            frappe.PermissionError,
        )

    selected_date = (
        frappe.utils.getdate(date)
        if date
        else frappe.utils.getdate()
    )

    active_minutes = max(
        int(active_window_minutes or 15),
        1,
    )

    day_start = f"{selected_date} 00:00:00"
    day_end = f"{selected_date} 23:59:59"

    filters: dict[str, Any] = {
        "captured_at": [
            "between",
            [day_start, day_end],
        ],
    }

    if personnel and personnel not in {
        "All Personnel",
        "All personnel",
    }:
        filters["personel"] = personnel

    or_filters: list[list[Any]] = []

    if search:
        search_value = f"%{search.strip()}%"

        or_filters = [
            ["patrol", "like", search_value],
            ["internal_guard", "like", search_value],
            ["external_guard", "like", search_value],
        ]

    points = frappe.get_list(
        doctype,
        filters=filters,
        or_filters=or_filters or None,
        fields=[
            "name",
            "patrol",
            "personel",
            "internal_guard",
            "external_guard",
            "captured_at",
            "latitude",
            "longitude",
            "gps_accuracy",
            "creation",
            "modified",
        ],
        order_by="captured_at desc",
        page_length=5000,
    )

    patrol_groups: dict[str, dict[str, Any]] = {}

    for point in points:
        patrol_id = str(point.get("patrol") or "").strip()

        if not patrol_id:
            patrol_id = _("Unassigned Patrol")

        if patrol_id not in patrol_groups:
            patrol_groups[patrol_id] = {
                "latest": point,
                "first": point,
                "point_count": 0,
            }

        patrol_groups[patrol_id]["point_count"] += 1
        patrol_groups[patrol_id]["first"] = point

    now = frappe.utils.now_datetime()
    today = frappe.utils.getdate()
    selected_is_today = selected_date == today

    rows: list[dict[str, Any]] = []
    active_count = 0
    stale_count = 0
    alert_count = 0
    guards: set[str] = set()

    for patrol_id, group in patrol_groups.items():
        latest = group["latest"]
        first = group["first"]

        latest_datetime = (
            frappe.utils.get_datetime(
                latest.get("captured_at")
            )
            if latest.get("captured_at")
            else None
        )

        minutes_since_update = None
        tracking_status = "Historical"

        if selected_is_today and latest_datetime:
            minutes_since_update = max(
                int(
                    (
                        now - latest_datetime
                    ).total_seconds()
                    / 60
                ),
                0,
            )

            if minutes_since_update <= active_minutes:
                tracking_status = "Active"
                active_count += 1
            else:
                tracking_status = "Stale"
                stale_count += 1
                alert_count += 1

        personnel_type = latest.get("personel") or ""
        guard = (
            latest.get("internal_guard")
            or latest.get("external_guard")
            or ""
        )

        if guard:
            guards.add(str(guard))

        latitude = _patrol_float(
            latest.get("latitude")
        )
        longitude = _patrol_float(
            latest.get("longitude")
        )
        accuracy = _patrol_float(
            latest.get("gps_accuracy")
        )

        coordinate_valid = (
            latitude is not None
            and longitude is not None
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        )

        poor_accuracy = (
            accuracy is not None
            and accuracy > 50
        )

        if not coordinate_valid:
            alert_count += 1

        if poor_accuracy:
            alert_count += 1

        rows.append(
            {
                "patrol": patrol_id,
                "personnel_type": personnel_type,
                "guard": guard,
                "latest_log": latest.get("name"),
                "latest_captured_at": _patrol_datetime(
                    latest.get("captured_at")
                ),
                "first_captured_at": _patrol_datetime(
                    first.get("captured_at")
                ),
                "latitude": latitude,
                "longitude": longitude,
                "gps_accuracy": accuracy,
                "point_count": group["point_count"],
                "tracking_status": tracking_status,
                "minutes_since_update": minutes_since_update,
                "last_seen": _patrol_last_seen(
                    minutes_since_update,
                    selected_is_today,
                ),
                "coordinate_valid": coordinate_valid,
                "poor_accuracy": poor_accuracy,
                "route": (
                    f"Form/Patrol GPS Log/"
                    f"{latest.get('name')}"
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            0
            if row["tracking_status"] == "Active"
            else 1
            if row["tracking_status"] == "Stale"
            else 2,
            row["patrol"],
        )
    )

    return {
        "selected_date": str(selected_date),
        "active_window_minutes": active_minutes,
        "summary": {
            "total_patrols": len(rows),
            "active_patrols": active_count,
            "stale_patrols": stale_count,
            "guards_tracked": len(guards),
            "gps_points": len(points),
            "tracking_alerts": alert_count,
        },
        "rows": rows,
        "map_points": [
            {
                "patrol": row["patrol"],
                "guard": row["guard"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "status": row["tracking_status"],
                "latest_log": row["latest_log"],
            }
            for row in rows
            if row["coordinate_valid"]
        ],
        "personnel_options": [
            "Internal Guard",
            "External Guard",
        ],
    }


def _patrol_float(value) -> float | None:
    if value in (None, ""):
        return None

    raw_value = str(value).strip().lower()

    for suffix in [
        "metres",
        "meters",
        "metre",
        "meter",
        "m",
    ]:
        if raw_value.endswith(suffix):
            raw_value = raw_value[
                : -len(suffix)
            ].strip()
            break

    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def _patrol_datetime(value) -> str:
    if not value:
        return ""

    try:
        return frappe.utils.get_datetime(value).strftime(
            "%d %b %Y %H:%M:%S"
        )
    except Exception:
        return str(value)


def _patrol_last_seen(
    minutes: int | None,
    selected_is_today: bool,
) -> str:
    if not selected_is_today or minutes is None:
        return _("Historical")

    if minutes < 1:
        return _("Just now")

    if minutes == 1:
        return _("1 minute ago")

    if minutes < 60:
        return _("{0} minutes ago").format(minutes)

    hours = minutes // 60
    remaining_minutes = minutes % 60

    if remaining_minutes:
        return _("{0}h {1}m ago").format(
            hours,
            remaining_minutes,
        )

    return _("{0}h ago").format(hours)


# END PATROL DASHBOARD API


# BEGIN INCIDENTS DASHBOARD API


@frappe.whitelist()
def get_incidents_dashboard(
    date_from=None,
    date_to=None,
    status=None,
    severity=None,
    category=None,
    location=None,
    assigned_to=None,
    search=None,
    limit=500,
):
    """
    Return permission-aware Incident Report data for the
    Security Command Centre.

    Incident Report is the parent DocType.

    Supporting DocTypes:
        Incident Category
        Incident Person
    """

    doctype = "Incident Report"

    if not frappe.has_permission(
        doctype,
        ptype="read",
    ):
        frappe.throw(
            _("You do not have permission to view Incident Reports."),
            frappe.PermissionError,
        )

    try:
        row_limit = int(limit or 500)
    except (TypeError, ValueError):
        row_limit = 500

    row_limit = max(1, min(row_limit, 2000))

    filters = []

    if date_from:
        start_date = frappe.utils.getdate(date_from)

        filters.append(
            [
                "incident_datetime",
                ">=",
                f"{start_date} 00:00:00",
            ]
        )

    if date_to:
        end_date = frappe.utils.getdate(date_to)

        filters.append(
            [
                "incident_datetime",
                "<=",
                f"{end_date} 23:59:59",
            ]
        )

    if status and status not in {
        "All",
        "All Statuses",
        "All statuses",
    }:
        filters.append(
            ["status", "=", status]
        )

    if severity and severity not in {
        "All",
        "All Severities",
        "All severities",
    }:
        filters.append(
            ["severity", "=", severity]
        )

    if category:
        filters.append(
            [
                "nature_of_incident",
                "=",
                category,
            ]
        )

    if location:
        filters.append(
            ["location", "=", location]
        )

    if assigned_to:
        filters.append(
            ["assigned_to", "=", assigned_to]
        )

    search_value = str(search or "").strip()
    or_filters = []

    if search_value:
        like_value = f"%{search_value}%"

        or_filters = [
            ["name", "like", like_value],
            [
                "nature_of_incident",
                "like",
                like_value,
            ],
            ["location", "like", like_value],
            ["reporter_name", "like", like_value],
            ["reported_by", "like", like_value],
            ["assigned_to", "like", like_value],
            ["description", "like", like_value],
        ]

    query_options = {
        "doctype": doctype,
        "filters": filters,
        "fields": [
            "name",
            "incident_datetime",
            "location",
            "nature_of_incident",
            "severity",
            "status",
            "reported_by",
            "reporter_name",
            "reported_datetime",
            "assigned_to",
            "description",
            "resolution",
            "corrective_actions",
            "resolution_datetime",
            "remarks",
            "attachment_1",
            "attachment_2",
            "attachment_3",
            "attachment_4",
            "owner",
            "creation",
            "modified",
        ],
        "order_by": "incident_datetime desc",
        "limit_page_length": row_limit,
    }

    if or_filters:
        query_options["or_filters"] = or_filters

    incidents = frappe.get_list(
        **query_options
    )

    incident_names = [
        row.get("name")
        for row in incidents
        if row.get("name")
    ]

    person_counts = {
        incident_name: {
            "responsible_persons": 0,
            "victims": 0,
            "witnesses": 0,
            "total_persons": 0,
        }
        for incident_name in incident_names
    }

    if incident_names:
        child_rows = frappe.get_all(
            "Incident Person",
            filters={
                "parenttype": "Incident Report",
                "parent": [
                    "in",
                    incident_names,
                ],
                "parentfield": [
                    "in",
                    [
                        "responsible_persons",
                        "victims",
                        "witnesses",
                    ],
                ],
            },
            fields=[
                "parent",
                "parentfield",
            ],
            limit_page_length=10000,
        )

        for child in child_rows:
            parent = child.get("parent")
            parentfield = child.get("parentfield")

            if parent not in person_counts:
                continue

            if parentfield in {
                "responsible_persons",
                "victims",
                "witnesses",
            }:
                person_counts[parent][parentfield] += 1
                person_counts[parent]["total_persons"] += 1

    # Nature of Incident is a Select on Incident Report, so the filter options
    # are the field's own choices. Reading them from meta keeps the dropdown in
    # step with the field automatically; the old Incident Category master is no
    # longer what incidents are classified against.
    nature_options = (
        frappe.get_meta("Incident Report").get_field("nature_of_incident").options
        or ""
    )

    categories = [
        {
            "name": option,
            "category_name": option,
            # Only the master carried these; a Select has no per-option metadata.
            "default_severity": None,
            "color": None,
        }
        for option in (line.strip() for line in nature_options.split("\n"))
        if option
    ]

    category_details = {}

    for category_row in categories:
        category_name = (
            category_row.get("category_name")
            or category_row.get("name")
        )

        if not category_name:
            continue

        category_details[category_name] = {
            "default_severity":
                category_row.get(
                    "default_severity"
                ),
            "color":
                category_row.get("color"),
        }

    summary = {
        "total_incidents": len(incidents),
        "open_incidents": 0,
        "in_progress_incidents": 0,
        "high_critical_incidents": 0,
        "resolved_incidents": 0,
        "closed_incidents": 0,
        "unassigned_incidents": 0,
    }

    category_totals = {}
    rows = []

    for incident in incidents:
        incident_name = incident.get("name")
        incident_status = (
            incident.get("status")
            or "Not Set"
        )
        incident_severity = (
            incident.get("severity")
            or "Not Set"
        )
        incident_category = (
            incident.get("nature_of_incident")
            or "Not Set"
        )

        if incident_status == "Open":
            summary["open_incidents"] += 1

        elif incident_status == "In Progress":
            summary[
                "in_progress_incidents"
            ] += 1

        elif incident_status == "Resolved":
            summary["resolved_incidents"] += 1

        elif incident_status == "Closed":
            summary["closed_incidents"] += 1

        if incident_severity in {
            "High",
            "Critical",
        }:
            summary[
                "high_critical_incidents"
            ] += 1

        if not incident.get("assigned_to"):
            summary["unassigned_incidents"] += 1

        category_totals.setdefault(
            incident_category,
            0,
        )
        category_totals[incident_category] += 1

        attachments = [
            incident.get("attachment_1"),
            incident.get("attachment_2"),
            incident.get("attachment_3"),
            incident.get("attachment_4"),
        ]

        attachments = [
            attachment
            for attachment in attachments
            if attachment
        ]

        counts = person_counts.get(
            incident_name,
            {
                "responsible_persons": 0,
                "victims": 0,
                "witnesses": 0,
                "total_persons": 0,
            },
        )

        category_meta = category_details.get(
            incident_category,
            {},
        )

        rows.append(
            {
                "name": incident_name,
                "incident_datetime":
                    _incident_format_datetime(
                        incident.get(
                            "incident_datetime"
                        )
                    ),
                "incident_datetime_raw":
                    incident.get(
                        "incident_datetime"
                    ),
                "location":
                    incident.get("location")
                    or "",
                "nature_of_incident":
                    incident_category,
                "severity":
                    incident_severity,
                "status":
                    incident_status,
                "reported_by":
                    incident.get("reported_by")
                    or "",
                "reporter_name":
                    incident.get("reporter_name")
                    or incident.get("reported_by")
                    or "",
                "reported_datetime":
                    _incident_format_datetime(
                        incident.get(
                            "reported_datetime"
                        )
                    ),
                "assigned_to":
                    incident.get("assigned_to")
                    or "",
                "description":
                    _incident_text_preview(
                        incident.get("description")
                    ),
                "resolution":
                    _incident_text_preview(
                        incident.get("resolution")
                    ),
                "corrective_actions":
                    _incident_text_preview(
                        incident.get(
                            "corrective_actions"
                        )
                    ),
                "resolution_datetime":
                    _incident_format_datetime(
                        incident.get(
                            "resolution_datetime"
                        )
                    ),
                "resolution_datetime_raw": incident.get("resolution_datetime"),
                "remarks":
                    _incident_text_preview(
                        incident.get("remarks")
                    ),
                "responsible_persons":
                    counts[
                        "responsible_persons"
                    ],
                "victims":
                    counts["victims"],
                "witnesses":
                    counts["witnesses"],
                "total_persons":
                    counts["total_persons"],
                "evidence_count":
                    len(attachments),
                "attachments":
                    attachments,
                "category_color":
                    category_meta.get("color"),
                "default_category_severity":
                    category_meta.get(
                        "default_severity"
                    ),
                "owner":
                    incident.get("owner"),
                "modified":
                    _incident_format_datetime(
                        incident.get("modified")
                    ),
            }
        )

    category_summary = []

    for category_name, count in sorted(
        category_totals.items(),
        key=lambda item: (
            -item[1],
            item[0],
        ),
    ):
        category_meta = category_details.get(
            category_name,
            {},
        )

        category_summary.append(
            {
                "category": category_name,
                "count": count,
                "color":
                    category_meta.get("color"),
                "default_severity":
                    category_meta.get(
                        "default_severity"
                    ),
            }
        )

    locations = sorted(
        {
            row["location"]
            for row in rows
            if row["location"]
        }
    )

    assigned_users = sorted(
        {
            row["assigned_to"]
            for row in rows
            if row["assigned_to"]
        }
    )

    return {
        "summary": summary,
        "rows": rows,
        "category_summary": category_summary,
        "filter_options": {
            "statuses": [
                "Open",
                "In Progress",
                "Resolved",
                "Closed",
            ],
            "severities": [
                "Low",
                "Medium",
                "High",
                "Critical",
            ],
            "categories": [
                {
                    "value":
                        category.get(
                            "category_name"
                        )
                        or category.get("name"),
                    "label":
                        category.get(
                            "category_name"
                        )
                        or category.get("name"),
                    "default_severity":
                        category.get(
                            "default_severity"
                        ),
                    "color":
                        category.get("color"),
                }
                for category in categories
            ],
            "locations": locations,
            "assigned_users": assigned_users,
        },
        "applied_filters": {
            "date_from": date_from,
            "date_to": date_to,
            "status": status,
            "severity": severity,
            "category": category,
            "location": location,
            "assigned_to": assigned_to,
            "search": search_value,
        },
    }


def _incident_format_datetime(value):
    if not value:
        return ""

    try:
        return frappe.utils.get_datetime(
            value
        ).strftime(
            "%d %b %Y %H:%M"
        )
    except Exception:
        return str(value)


def _incident_text_preview(
    value,
    maximum_length=180,
):
    if not value:
        return ""

    text = " ".join(
        str(value).split()
    )

    if len(text) <= maximum_length:
        return text

    return (
        text[: maximum_length - 1].rstrip()
        + "…"
    )


# END INCIDENTS DASHBOARD API

# BEGIN CONTRACTORS DASHBOARD API


@frappe.whitelist()
def get_contractors_dashboard(
    reporting_status=None,
    transport=None,
    search=None,
    date_from=None,
    date_to=None,
    limit=2000,
):
    """
    Return Appointment records where visitor_type is Contractor.

    The endpoint deliberately uses the Visitor/Contractor fields,
    with fallbacks to the core Appointment fields.
    """

    doctype = "Appointment"

    if not frappe.has_permission(
        doctype,
        ptype="read",
    ):
        frappe.throw(
            _("You do not have permission to view Appointments."),
            frappe.PermissionError,
        )

    try:
        row_limit = int(limit or 2000)
    except (TypeError, ValueError):
        row_limit = 2000

    row_limit = max(1, min(row_limit, 5000))

    filters = {
        "visitor_type": "Contractor",
    }

    if reporting_status and reporting_status not in {
        "All",
        "All Statuses",
        "All statuses",
    }:
        filters["reporting_status"] = reporting_status

    if transport and transport not in {
        "All",
        "All Transport",
        "All transport",
    }:
        filters["mode_of_transport"] = transport

    appointments = frappe.get_list(
        doctype,
        filters=filters,
        fields=[
            "name",

            # Core Appointment fields
            "scheduled_time",
            "status",
            "host_whatsapp_no",
            "farmunit",
            "customer_name",
            "customer_phone_number",
            "customer_email",
            "customer_details",

            # Visitor/Contractor fields
            "scheduled_t",
            "statuss",
            "meeting_with",
            "whatsapp_no",
            "compan",
            "farm_unit",
            "number_passengers",
            "name1",
            "phone_no",
            "mail",
            "detail",
            "visitor_type",
            "contractor_ref",
            "mode_of_transport",
            "vehicles_number_plate",
            "vehicles_color",
            "motorcycles_plate",
            "check_in_time",
            "check_out_time",
            "reporting_status",

            "owner",
            "creation",
            "modified",
        ],
        order_by="modified desc",
        page_length=row_limit,
    )

    selected_from = (
        frappe.utils.getdate(date_from)
        if date_from
        else None
    )

    selected_to = (
        frappe.utils.getdate(date_to)
        if date_to
        else None
    )

    search_value = str(search or "").strip().lower()

    rows = []

    for appointment in appointments:
        scheduled_raw = (
            appointment.get("scheduled_t")
            or appointment.get("scheduled_time")
        )

        scheduled_date = None

        if scheduled_raw:
            try:
                scheduled_date = frappe.utils.getdate(
                    scheduled_raw
                )
            except Exception:
                scheduled_date = None

        if (
            selected_from
            and scheduled_date
            and scheduled_date < selected_from
        ):
            continue

        if (
            selected_to
            and scheduled_date
            and scheduled_date > selected_to
        ):
            continue

        contractor_name = (
            appointment.get("name1")
            or appointment.get("customer_name")
            or ""
        )

        phone = (
            appointment.get("phone_no")
            or appointment.get(
                "customer_phone_number"
            )
            or ""
        )

        email = (
            appointment.get("mail")
            or appointment.get("customer_email")
            or ""
        )

        company = appointment.get("compan") or ""

        farm = (
            appointment.get("farm_unit")
            or appointment.get("farmunit")
            or ""
        )

        host_phone = (
            appointment.get("whatsapp_no")
            or appointment.get(
                "host_whatsapp_no"
            )
            or ""
        )

        plate = (
            appointment.get(
                "vehicles_number_plate"
            )
            or appointment.get(
                "motorcycles_plate"
            )
            or ""
        )

        searchable_values = [
            appointment.get("name"),
            contractor_name,
            phone,
            email,
            company,
            farm,
            appointment.get("contractor_ref"),
            appointment.get("meeting_with"),
            plate,
        ]

        if search_value:
            combined = " ".join(
                str(value or "")
                for value in searchable_values
            ).lower()

            if search_value not in combined:
                continue

        movement_status = (
            appointment.get("reporting_status")
            or "Not Set"
        )

        checked_in = (
            movement_status == "Checked In"
            and not appointment.get("check_out_time")
        )

        checked_out = (
            movement_status == "Checked Out"
            or bool(appointment.get("check_out_time"))
        )

        rows.append(
            {
                "name": appointment.get("name"),
                "contractor_name": contractor_name,
                "phone": phone,
                "email": email,
                "company": company,
                "farm_unit": farm,
                "contractor_ref":
                    appointment.get("contractor_ref")
                    or "",
                "meeting_with":
                    appointment.get("meeting_with")
                    or "",
                "host_whatsapp_no": host_phone,
                "scheduled_time":
                    _contractor_format_datetime(
                        scheduled_raw
                    ),
                "scheduled_time_raw": scheduled_raw,
                "appointment_status":
                    appointment.get("statuss")
                    or appointment.get("status")
                    or "",
                "reporting_status": movement_status,
                "mode_of_transport":
                    appointment.get(
                        "mode_of_transport"
                    )
                    or "",
                "vehicle_plate":
                    appointment.get(
                        "vehicles_number_plate"
                    )
                    or "",
                "motorcycle_plate":
                    appointment.get(
                        "motorcycles_plate"
                    )
                    or "",
                "plate": plate,
                "vehicle_colour":
                    appointment.get(
                        "vehicles_color"
                    )
                    or "",
                "number_passengers":
                    _contractor_integer(
                        appointment.get(
                            "number_passengers"
                        )
                    ),
                "check_in_time":
                    _contractor_format_datetime(
                        appointment.get(
                            "check_in_time"
                        )
                    ),
                "check_in_time_raw":
                    appointment.get(
                        "check_in_time"
                    ),
                "check_out_time":
                    _contractor_format_datetime(
                        appointment.get(
                            "check_out_time"
                        )
                    ),
                "check_out_time_raw":
                    appointment.get(
                        "check_out_time"
                    ),
                "checked_in": checked_in,
                "checked_out": checked_out,
                "route": (
                    f"Form/Appointment/"
                    f"{appointment.get('name')}"
                ),
                "modified":
                    _contractor_format_datetime(
                        appointment.get("modified")
                    ),
            }
        )

    summary = {
        "total_contractors": len(rows),
        "scheduled": sum(
            1
            for row in rows
            if row["reporting_status"] == "Scheduled"
        ),
        "checked_in": sum(
            1
            for row in rows
            if row["checked_in"]
        ),
        "checked_out": sum(
            1
            for row in rows
            if row["checked_out"]
        ),
        "pending_host_review": sum(
            1
            for row in rows
            if row["reporting_status"]
            == "Pending Host Review"
        ),
        "expired": sum(
            1
            for row in rows
            if row["reporting_status"] == "Expired"
        ),
        "with_vehicle": sum(
            1
            for row in rows
            if row["mode_of_transport"]
            in {"Vehicle", "Motorcycle"}
        ),
    }

    return {
        "summary": summary,
        "rows": rows,
        "filter_options": {
            "reporting_statuses": [
                "Scheduled",
                "Checked In",
                "Checked Out",
                "Expired",
                "Pending Host Review",
            ],
            "transport_modes": [
                "On Foot",
                "Vehicle",
                "Motorcycle",
            ],
            "companies": sorted(
                {
                    row["company"]
                    for row in rows
                    if row["company"]
                }
            ),
            "farms": sorted(
                {
                    row["farm_unit"]
                    for row in rows
                    if row["farm_unit"]
                }
            ),
        },
        "applied_filters": {
            "reporting_status": reporting_status,
            "transport": transport,
            "search": search_value,
            "date_from": date_from,
            "date_to": date_to,
        },
    }


def _contractor_format_datetime(value):
    if not value:
        return ""

    try:
        return frappe.utils.get_datetime(
            value
        ).strftime("%d %b %Y %H:%M")
    except Exception:
        return str(value)


def _contractor_integer(value):
    if value in (None, ""):
        return 0

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


# END CONTRACTORS DASHBOARD API


# ─────────────────────────────────────────────────────────────────
# Web Page dashboard bridge — used by security-dasboard Web Page
# ─────────────────────────────────────────────────────────────────

def _resolve_range(period=None, from_date=None, to_date=None):
    today = frappe.utils.getdate()

    if period == "custom" and from_date and to_date:
        return frappe.utils.getdate(from_date), frappe.utils.getdate(to_date)
    if period == "last_7_days":
        return frappe.utils.add_days(today, -6), today
    if period == "last_30_days":
        return frappe.utils.add_days(today, -29), today
    return today, today


def _haversine_km(p1, p2):
    from math import radians, sin, cos, sqrt, atan2

    lat1, lon1 = p1
    lat2, lon2 = p2
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _path_distance_km(points):
    if len(points) < 2:
        return 0.0
    return sum(
        _haversine_km(points[i - 1], points[i])
        for i in range(1, len(points))
    )


@frappe.whitelist()
def fetchSecurityDasboardData(
    tab=None,
    period=None,
    from_date=None,
    to_date=None,
    farm=None,
    shift_type=None,
    status=None,
    company=None,
):
    tab = (tab or "").strip().lower()
    range_from, range_to = _resolve_range(period, from_date, to_date)

    if tab == "incidents":
        return _fetch_incidents_tab(range_from, range_to)
    if tab == "patrols":
        return _fetch_patrols_tab(range_from, range_to)
    if tab == "shifts":
        return _fetch_shifts_tab(
            range_from, range_to, farm=farm, shift_type=shift_type, status=status, company=company
        )
    if tab == "near_miss":
        return _fetch_near_miss_tab(range_from, range_to)

    frappe.throw(_("Unknown dashboard tab: {0}").format(tab))


def _fetch_near_miss_tab(range_from, range_to):
    """Near misses are meant to be caught early, not discovered a week
    later buried in a list view — this is what actually surfaces them:
    a dashboard tab plus a "needs review" count driving both this page's
    nav badge and the Overview page's recent-activity card.

    "Needs review" = not yet escalated to a full Incident Report AND
    still within the last 48 hours — an old near miss nobody escalated
    is presumably already a closed matter, not something still pending
    action; the badge should reflect what's actually still actionable.
    """
    if not frappe.has_permission("Near Miss Report", ptype="read"):
        frappe.throw(
            _("You do not have permission to view Near Miss Reports."),
            frappe.PermissionError,
        )

    rows = frappe.get_all(
        "Near Miss Report",
        filters={
            "near_miss_datetime": ["between", [f"{range_from} 00:00:00", f"{range_to} 23:59:59"]]
        },
        fields=[
            "name", "near_miss_datetime", "farm", "location", "reporter_name",
            "description", "could_have_resulted_in", "converted_to_incident",
        ],
        order_by="near_miss_datetime desc",
        limit_page_length=500,
    )

    needs_review_cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-48)
    needs_review = 0
    for r in rows:
        if r.converted_to_incident:
            continue
        if frappe.utils.get_datetime(r.near_miss_datetime) >= needs_review_cutoff:
            needs_review += 1

    by_outcome = {}
    for r in rows:
        key = r.could_have_resulted_in or "Other"
        by_outcome[key] = by_outcome.get(key, 0) + 1

    return {
        "success": True,
        "range_from": str(range_from),
        "range_to": str(range_to),
        "summary": {
            "total": len(rows),
            "needs_review": needs_review,
            "escalated": sum(1 for r in rows if r.converted_to_incident),
            "by_outcome": [{"outcome": k, "count": v} for k, v in by_outcome.items()],
        },
        "rows": [
            {
                "name": r.name,
                "near_miss_datetime": str(r.near_miss_datetime),
                "farm": r.farm or "",
                "location": r.location or "",
                "reporter_name": r.reporter_name or "",
                "description": r.description or "",
                "could_have_resulted_in": r.could_have_resulted_in or "",
                "converted_to_incident": r.converted_to_incident or "",
                "needs_review": (
					not r.converted_to_incident
					and frappe.utils.get_datetime(r.near_miss_datetime) >= needs_review_cutoff
				),
            }
            for r in rows
        ],
    }


def _fetch_incidents_tab(range_from, range_to):
    data = get_incidents_dashboard(
        date_from=str(range_from), date_to=str(range_to), limit=2000
    )
    rows = data.get("rows", [])
    summary = data.get("summary", {})

    critical_open = sum(
        1 for r in rows
        if r["severity"] == "Critical" and r["status"] not in ("Resolved", "Closed")
    )
    high_open = sum(
        1 for r in rows
        if r["severity"] == "High" and r["status"] not in ("Resolved", "Closed")
    )

    total_minutes, resolved_count = 0.0, 0
    for r in rows:
        if r.get("incident_datetime_raw") and r.get("resolution_datetime_raw"):
            try:
                start = frappe.utils.get_datetime(r["incident_datetime_raw"])
                end = frappe.utils.get_datetime(r["resolution_datetime_raw"])
                diff = (end - start).total_seconds() / 60
                if diff >= 0:
                    total_minutes += diff
                    resolved_count += 1
            except Exception:
                pass
    avg_resolution = int(total_minutes / resolved_count) if resolved_count else 0

    severity_counts, state_counts, category_counts = {}, {}, {}
    reporter_counts, location_counts, day_counts = {}, {}, {}
    gallery = []

    for r in rows:
        severity_counts[r["severity"]] = severity_counts.get(r["severity"], 0) + 1
        state_counts[r["status"]] = state_counts.get(r["status"], 0) + 1
        category_counts[r["nature_of_incident"]] = (
            category_counts.get(r["nature_of_incident"], 0) + 1
        )
        reporter = r.get("reporter_name") or "Unknown"
        reporter_counts[reporter] = reporter_counts.get(reporter, 0) + 1
        if r.get("location"):
            location_counts[r["location"]] = location_counts.get(r["location"], 0) + 1
        if r.get("incident_datetime_raw"):
            day = str(frappe.utils.getdate(r["incident_datetime_raw"]))
            day_counts[day] = day_counts.get(day, 0) + 1
        for att in r.get("attachments", []):
            gallery.append({
                "name": r["name"],
                "url": att,
                "severity": r["severity"],
                "nature_of_incident": r["nature_of_incident"],
                "location": r.get("location"),
            })

    recent = [
        {
            "name": r["name"],
            "nature_of_incident": r["nature_of_incident"],
            "severity": r["severity"],
            "workflow_state": r["status"],
            "location": r.get("location"),
            "reporter_name": r.get("reporter_name"),
            "incident_datetime": r.get("incident_datetime_raw"),
            "attachments": r.get("attachments", []),
        }
        for r in rows[:50]
    ]

    return {
        "success": True,
        "range_from": str(range_from),
        "range_to": str(range_to),
        "incidents_total": summary.get("total_incidents", 0),
        "incidents_open": summary.get("open_incidents", 0),
        "incidents_critical_open": critical_open,
        "incidents_high_open": high_open,
        "incidents_under_investigation": summary.get("in_progress_incidents", 0),
        "incidents_resolved": summary.get("resolved_incidents", 0),
        "incidents_closed": summary.get("closed_incidents", 0),
        "incidents_avg_resolution_minutes": avg_resolution,
        "incidents_by_severity": [
            {"severity": k, "count": v} for k, v in severity_counts.items()
        ],
        "incidents_by_state": [
            {"state": k, "count": v} for k, v in state_counts.items()
        ],
        "incidents_by_category": sorted(
            [{"category": k, "count": v} for k, v in category_counts.items()],
            key=lambda x: -x["count"],
        ),
        "incidents_by_reporter": sorted(
            [{"reporter": k, "count": v} for k, v in reporter_counts.items()],
            key=lambda x: -x["count"],
        )[:10],
        "incidents_by_location": sorted(
            [{"location": k, "count": v} for k, v in location_counts.items()],
            key=lambda x: -x["count"],
        )[:10],
        "incidents_over_time": [
            {"day": k, "count": day_counts[k]} for k in sorted(day_counts.keys())
        ],
        "incidents_gallery": gallery[:24],
        "incidents_recent": recent,
    }


def _patrol_reports_by_tag(tags):
    """Map patrol tag -> its Patrol Report, fetched in one query.

    One report per patrol, filed whenever the guard chooses.

    Returns {} when the doctype is absent or unreadable, so a caller without
    Patrol Report permission still gets the GPS half of the tab.
    """
    if not tags or not frappe.db.exists("DocType", "Patrol Report"):
        return {}
    if not frappe.has_permission("Patrol Report", ptype="read"):
        return {}

    rows = frappe.get_all(
        "Patrol Report",
        filters={"patrol": ["in", list(tags)]},
        fields=[
            "name", "patrol", "status", "report_type", "severity",
            "incident_report", "filed_at", "observations", "supervisor_remarks",
            "reviewed_by", "reviewed_on", "farm", "personel",
            "attachment_1", "attachment_2", "attachment_3", "attachment_4",
        ],
        order_by="filed_at asc, creation asc",
        limit_page_length=0,
    )

    by_tag = {}
    for r in rows:
        photos = [r.get(f"attachment_{i}") for i in range(1, 5)]
        photos = [p for p in photos if p]
        by_tag[r["patrol"]] = {
            "report": r["name"],
            "report_status": r.get("status"),
            "report_type": r.get("report_type") or "Routine",
            "severity": r.get("severity"),
            "incident_report": r.get("incident_report"),
            "filed_at": str(r["filed_at"]) if r.get("filed_at") else None,
            "observations": r.get("observations") or "",
            "supervisor_remarks": r.get("supervisor_remarks") or "",
            "reviewed_by": r.get("reviewed_by"),
            "reviewed_on": str(r["reviewed_on"]) if r.get("reviewed_on") else None,
            "report_farm": r.get("farm"),
            "report_personel": r.get("personel"),
            "photos": photos,
            "photo_count": len(photos),
        }
    return by_tag


def _fetch_patrols_tab(range_from, range_to):
    doctype = "Patrol GPS Log"

    if not frappe.has_permission(doctype, ptype="read"):
        frappe.throw(
            _("You do not have permission to view Patrol GPS Logs."),
            frappe.PermissionError,
        )

    day_start = f"{range_from} 00:00:00"
    day_end = f"{range_to} 23:59:59"

    points = frappe.get_list(
        doctype,
        filters={"captured_at": ["between", [day_start, day_end]]},
        fields=[
            "name", "patrol", "personel", "internal_guard",
            "external_guard", "captured_at", "latitude", "longitude",
        ],
        order_by="captured_at asc",
        page_length=5000,
    )

    groups = {}
    for p in points:
        patrol_id = str(p.get("patrol") or "Unassigned").strip() or "Unassigned"
        guard = p.get("internal_guard") or p.get("external_guard") or "Unassigned"
        key = f"{guard}::{patrol_id}"
        if key not in groups:
            groups[key] = {"guard": guard, "patrol": patrol_id, "points": [], "timestamps": []}
        lat = _patrol_float(p.get("latitude"))
        lng = _patrol_float(p.get("longitude"))
        if lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180:
            groups[key]["points"].append([lat, lng])
        groups[key]["timestamps"].append(p.get("captured_at"))

    now = frappe.utils.now_datetime()
    today = frappe.utils.getdate()
    active_count = stale_count = 0
    total_distance = 0.0
    patrol_list, guard_agg = [], {}

    for key, g in groups.items():
        ts = g["timestamps"]
        last_fix = ts[-1] if ts else None
        distance_km = _path_distance_km(g["points"])
        total_distance += distance_km

        status = "Ended"
        if last_fix:
            try:
                last_dt = frappe.utils.get_datetime(last_fix)
                if last_dt.date() == today:
                    mins_since = (now - last_dt).total_seconds() / 60
                    if mins_since <= 15:
                        status = "Active"
                        active_count += 1
                    else:
                        status = "Stale"
                        stale_count += 1
            except Exception:
                pass

        patrol_list.append({
            "status": status,
            "patrol": g["patrol"],
            "guard": g["guard"],
            "points": len(ts),
            "distance_m": round(distance_km * 1000),
            "last_fix": str(last_fix) if last_fix else None,
        })

        employee_name, department = g["guard"], ""
        if frappe.db.exists("Employee", g["guard"]):
            emp = frappe.db.get_value(
                "Employee", g["guard"], ["employee_name", "department"], as_dict=True
            )
            if emp:
                employee_name = emp.employee_name or g["guard"]
                department = emp.department or ""

        agg = guard_agg.setdefault(g["guard"], {
            "employee": g["guard"],
            "employee_name": employee_name,
            "department": department,
            "patrols": 0,
            "distance_km": 0.0,
            "total_points": 0,
        })
        agg["patrols"] += 1
        agg["distance_km"] += distance_km
        agg["total_points"] += len(ts)

    guard_stats = [
        {**v, "distance_km": round(v["distance_km"], 2)} for v in guard_agg.values()
    ]

    # Attach each patrol's end-of-shift report so a supervisor sees the track and
    # the guard's account of it side by side.
    reports = _patrol_reports_by_tag({p["patrol"] for p in patrol_list})
    submitted = reviewed = flagged = incidents = 0

    for entry in patrol_list:
        rep = reports.get(entry["patrol"])
        entry["has_report"] = bool(rep)
        if not rep:
            continue
        entry.update(rep)
        if rep["report_type"] == "Incident":
            incidents += 1
        if rep["report_status"] == "Submitted":
            submitted += 1
        elif rep["report_status"] == "Reviewed":
            reviewed += 1
        elif rep["report_status"] == "Flagged":
            flagged += 1

    reported = sum(1 for p in patrol_list if p["has_report"])

    return {
        "success": True,
        "range_from": str(range_from),
        "range_to": str(range_to),
        "total_distance_km": round(total_distance, 2),
        "total_patrols_in_range": len(patrol_list),
        "active_patrols": active_count,
        "stale_patrols": stale_count,
        "total_patrol_points": len(points),
        "patrol_list": patrol_list,
        "guard_stats": guard_stats,
        # Patrol Report roll-up
        "reports_submitted": submitted,
        "reports_reviewed": reviewed,
        "reports_flagged": flagged,
        "reports_incidents": incidents,
        "patrols_reported": reported,
        "patrols_without_report": len(patrol_list) - reported,
    }


@frappe.whitelist()
def _guard_farm_lookup(selected_date):
    """Which farm was each guard assigned to on this date, per their own
    Security Guard Shift Assignment — Patrol GPS Log itself carries no farm
    field, so this is the only way to attribute a patrol point to a farm.
    Keyed the same way patrol groups are: internal_guard/external_guard id.
    Ambiguous on purpose in one direction only: a guard covering two farms
    in one day (a rotation) will just get whichever shift row is seen last —
    rare enough not to be worth a more elaborate merge here."""
    rows = frappe.db.sql(
        """
        SELECT internal_guard, external_guard, farm
        FROM `tabSecurity Guard Shift Assignment`
        WHERE farm IS NOT NULL AND farm != ''
          AND DATE(start_date) <= %(d)s
          AND (end_date IS NULL OR DATE(end_date) >= %(d)s)
        """,
        {"d": selected_date},
        as_dict=True,
    )
    lookup = {}
    for r in rows:
        if r.internal_guard:
            lookup[r.internal_guard] = r.farm
        if r.external_guard:
            lookup[r.external_guard] = r.farm
    return lookup


@frappe.whitelist()
def fetchPatrolData(date=None, farm=None):
    doctype = "Patrol GPS Log"

    if not frappe.has_permission(doctype, ptype="read"):
        frappe.throw(
            _("You do not have permission to view Patrol GPS Logs."),
            frappe.PermissionError,
        )

    selected_date = frappe.utils.getdate(date) if date else frappe.utils.getdate()
    day_start = f"{selected_date} 00:00:00"
    day_end = f"{selected_date} 23:59:59"

    points = frappe.get_list(
        doctype,
        filters={"captured_at": ["between", [day_start, day_end]]},
        fields=[
            "name", "patrol", "personel", "internal_guard",
            "external_guard", "captured_at", "latitude", "longitude", "farm",
        ],
        order_by="captured_at asc",
        page_length=5000,
    )

    # Fallback only — stamp_patrol_gps_log_farm (hooks.py before_insert on
    # Patrol GPS Log) already writes farm directly onto every row at capture
    # time, which is reliable regardless of whether the guard has a Shift
    # Assignment covering this exact date. This lookup only still matters for
    # rows inserted before that hook existed, where farm is blank.
    guard_farms = _guard_farm_lookup(selected_date)
    farm = (farm or "").strip()

    groups = {}
    for p in points:
        lat = _patrol_float(p.get("latitude"))
        lng = _patrol_float(p.get("longitude"))
        if lat is None or lng is None or not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            continue

        patrol_id = str(p.get("patrol") or "Unassigned").strip() or "Unassigned"
        guard = p.get("internal_guard") or p.get("external_guard") or "Unassigned"
        guard_farm = str(p.get("farm") or "").strip() or guard_farms.get(guard) or ""

        if farm and guard_farm != farm:
            continue

        key = f"{guard}::{patrol_id}"

        if key not in groups:
            guard_name = guard
            if p.get("internal_guard"):
                guard_name = frappe.db.get_value(
                    "Employee", p["internal_guard"], "employee_name"
                ) or guard
            elif p.get("external_guard"):
                guard_name = frappe.db.get_value(
                    "Security Guard", p["external_guard"], "full_name"
                ) or guard
            groups[key] = {
                "guard_id": guard, "guard_name": guard_name, "farm": guard_farm,
                "patrol_tag": patrol_id, "points": [], "timestamps": [],
            }

        groups[key]["points"].append([lat, lng])
        groups[key]["timestamps"].append(p.get("captured_at"))

    now = frappe.utils.now_datetime()
    is_today = selected_date == frappe.utils.getdate()

    patrol_paths, guard_totals = [], {}
    total_distance = total_duration = 0.0

    for key, g in groups.items():
        pts, ts = g["points"], g["timestamps"]
        distance_km = _path_distance_km(pts)
        first_fix, last_fix = (ts[0], ts[-1]) if ts else (None, None)

        duration_min = 0
        if first_fix and last_fix:
            try:
                duration_min = max(int(
                    (frappe.utils.get_datetime(last_fix)
                     - frappe.utils.get_datetime(first_fix)).total_seconds() / 60
                ), 0)
            except Exception:
                pass

        is_active = False
        if is_today and last_fix:
            try:
                mins_since = (now - frappe.utils.get_datetime(last_fix)).total_seconds() / 60
                is_active = mins_since <= 15
            except Exception:
                pass

        patrol_paths.append({
            "guard_id": g["guard_id"],
            "guard_name": g["guard_name"],
            "farm": g.get("farm") or "",
            "patrol_tag": g["patrol_tag"],
            "points": pts,
            "timestamps": [str(t) for t in ts],
            "point_count": len(pts),
            "distance_km": round(distance_km, 2),
            "duration_min": duration_min,
            "first_fix": str(first_fix) if first_fix else None,
            "last_fix": str(last_fix) if last_fix else None,
            "is_active": is_active,
            "last_point": pts[-1] if pts else None,
        })

        total_distance += distance_km
        total_duration += duration_min

        gt = guard_totals.setdefault(g["guard_id"], {
            "guard_id": g["guard_id"], "guard_name": g["guard_name"],
            "farm": g.get("farm") or "", "distance_km": 0.0, "is_active": False,
        })
        gt["distance_km"] += distance_km
        gt["is_active"] = gt["is_active"] or is_active

    guards = [
        {**v, "distance_km": round(v["distance_km"], 2)} for v in guard_totals.values()
    ]
    avg_duration = (total_duration / len(patrol_paths)) if patrol_paths else 0

    return {
        "success": True,
        "patrol_paths": patrol_paths,
        "guards": guards,
        "summary": {
            "total_guards": len(guards),
            "total_patrols": len(patrol_paths),
            "total_distance_km": round(total_distance, 2),
            "average_duration_min": round(avg_duration, 1),
        },
    }


# ─────────────────────────────────────────────────────────────────
# BEGIN SHIFT PLANNING DASHBOARD API
# ─────────────────────────────────────────────────────────────────

_SHIFT_FARM_PALETTE = [
    {"bg": "#E6F1FB", "text": "#0C447C"},  # blue
    {"bg": "#EAF3DE", "text": "#27500A"},  # green
    {"bg": "#FAEEDA", "text": "#633806"},  # amber
    {"bg": "#EEEDFE", "text": "#3C3489"},  # purple
    {"bg": "#FCEBEB", "text": "#791F1F"},  # rose
    {"bg": "#CCFBF1", "text": "#115E59"},  # teal
    {"bg": "#FFE4E6", "text": "#9F1239"},  # pink
    {"bg": "#E0E7FF", "text": "#3730A3"},  # indigo
]


def _shift_farm_colors(farm_names: list[str]) -> dict[str, dict[str, str]]:
    ordered = sorted({name for name in farm_names if name})
    return {
        name: _SHIFT_FARM_PALETTE[i % len(_SHIFT_FARM_PALETTE)]
        for i, name in enumerate(ordered)
    }


def _shift_guard_key(row) -> str | None:
    if row.get("internal_guard"):
        return f"employee::{row['internal_guard']}"
    if row.get("external_guard"):
        return f"security_guard::{row['external_guard']}"
    return None


def _shift_guard_name(row, employee_names, security_guard_names) -> str:
    if row.get("internal_guard"):
        return employee_names.get(row["internal_guard"], row["internal_guard"])
    if row.get("external_guard"):
        return security_guard_names.get(row["external_guard"], row["external_guard"])
    return _("Unassigned")


def _farm_name_field() -> str:
    """Farm's own display/naming field differs by which app supplies the
    doctype on a given site: upande_kaitet's Farm names itself `farm`,
    upande_core's Farm (krv16, kaitetv16-staging, ...) names itself
    `farm_name` instead - there's no field called `farm` there at all.
    Resolving this once from the site's own Farm meta, rather than
    hardcoding either name, is what lets this same dashboard code run
    unmodified across both schemas instead of throwing a field-permission
    error on whichever schema it wasn't written against."""
    meta = frappe.get_meta("Farm")
    return "farm_name" if meta.has_field("farm_name") else "farm"


@frappe.whitelist()
def search_guards_for_shift(guard_type, query):
    """Guard type-ahead for the Shift Assignments tab's New/Rotate modal.

    Deliberately raw SQL rather than frappe.get_list — neither Employee nor
    Security Guard grants "read" to the Security Head role (Employee is
    HR-only; Security Guard is HR Manager/System Manager only), so the ORM
    path silently returns zero rows for the very role this dashboard is
    built for. Same shape as the "Search Employees" Server Script the mobile
    app already uses for host search, gated here on read access to the
    Shift Assignment doctype itself instead.
    """
    if not frappe.has_permission("Security Guard Shift Assignment", ptype="read"):
        frappe.throw(
            _("You do not have permission to search guards for Shift Assignments."),
            frappe.PermissionError,
        )

    query = (query or "").strip()
    if len(query) < 2:
        return []
    like = "%" + query + "%"

    if guard_type == "Internal Guard":
        rows = frappe.db.sql(
            """
            SELECT name, employee_name AS label
            FROM `tabEmployee`
            WHERE status = 'Active'
              AND designation = 'Security Guard'
              AND (name LIKE %s OR employee_name LIKE %s)
            ORDER BY employee_name ASC
            LIMIT 20
            """,
            (like, like),
            as_dict=True,
        )
    elif guard_type == "External Guard":
        rows = frappe.db.sql(
            """
            SELECT name, COALESCE(full_name, first_name) AS label
            FROM `tabSecurity Guard`
            WHERE name LIKE %s OR full_name LIKE %s OR first_name LIKE %s
            ORDER BY label ASC
            LIMIT 20
            """,
            (like, like, like),
            as_dict=True,
        )
    else:
        frappe.throw(_("Unknown guard type: {0}").format(guard_type))

    return rows


def _fetch_shifts_tab(range_from, range_to, farm=None, shift_type=None, status=None, company=None):
    doctype = "Security Guard Shift Assignment"
    farm_name_field = _farm_name_field()

    if not frappe.has_permission(doctype, ptype="read"):
        frappe.throw(
            _("You do not have permission to view Shift Assignments."),
            frappe.PermissionError,
        )

    today = frappe.utils.getdate()

    # Farms scoped to the selected Company (or every farm, if no company chosen) —
    # drives both the Farm dropdown options and, below, which farms the coverage
    # board / rotation metrics are computed over.
    company_farms = frappe.get_list(
        "Farm",
        filters={"company": company} if company else {},
        fields=["name", farm_name_field],
        order_by=f"{farm_name_field} asc",
        page_length=500,
    )
    company_farms = [{"name": f["name"], "farm": f.get(farm_name_field)} for f in company_farms]

    # An explicit farm always wins; otherwise fall back to the company's farms
    # (or no restriction at all if neither farm nor company was picked).
    if farm:
        farm_scope = [farm]
    elif company:
        farm_scope = [f["name"] for f in company_farms] or ["__no_farm_matches__"]
    else:
        farm_scope = None

    range_filters = [
        ["start_date", "<=", f"{range_to} 23:59:59"],
        ["end_date", ">=", f"{range_from} 00:00:00"],
    ]

    if farm_scope is not None:
        range_filters.append(["farm", "in", farm_scope])
    if shift_type:
        range_filters.append(["shift_type", "=", shift_type])
    if status:
        range_filters.append(["status", "=", status])

    range_rows = frappe.get_list(
        doctype,
        filters=range_filters,
        fields=[
            "name", "security_guard", "internal_guard", "external_guard",
            "farm", "block", "shift_type", "start_date", "end_date", "status",
            "assigned_by", "remarks", "modified",
        ],
        order_by="start_date desc",
        page_length=1000,
    )

    # All-time rows (unfiltered by date, but still scoped to farm/company) drive
    # the rotation metric and today's coverage board, since a shift can span
    # outside the picked date range.
    all_rows_filters = {"status": "Active"}
    if farm_scope is not None:
        all_rows_filters["farm"] = ["in", farm_scope]

    all_rows = frappe.get_list(
        doctype,
        filters=all_rows_filters,
        fields=[
            "name", "security_guard", "internal_guard", "external_guard",
            "farm", "shift_type", "start_date", "end_date",
        ],
        page_length=5000,
    )

    employee_ids = {r["internal_guard"] for r in range_rows + all_rows if r.get("internal_guard")}
    security_guard_ids = {r["external_guard"] for r in range_rows + all_rows if r.get("external_guard")}

    employee_names = {
        e.name: e.employee_name
        for e in frappe.get_all(
            "Employee",
            filters={"name": ["in", list(employee_ids)]} if employee_ids else {"name": ["in", []]},
            fields=["name", "employee_name"],
        )
    }
    security_guard_names = {
        g.name: (g.full_name or g.name)
        for g in frappe.get_all(
            "Security Guard",
            filters={"name": ["in", list(security_guard_ids)]} if security_guard_ids else {"name": ["in", []]},
            fields=["name", "full_name"],
        )
    }

    # Coverage board is built over the same farm scope as the data above: just
    # the selected farm, or every farm in the selected company, or all farms.
    if farm:
        fallback = frappe.get_list("Farm", filters={"name": farm}, fields=["name", farm_name_field])
        board_farms = [f for f in company_farms if f["name"] == farm] or [
            {"name": f["name"], "farm": f.get(farm_name_field)} for f in fallback
        ]
    else:
        board_farms = company_farms

    farm_colors = _shift_farm_colors([a.get("farm") for a in range_rows])

    rows = []
    for r in range_rows:
        farm_name = r.get("farm") or ""
        color = farm_colors.get(farm_name, {"bg": "#F1EFE8", "text": "#444441"})
        rows.append({
            "name": r["name"],
            "guard_key": _shift_guard_key(r),
            "guard_name": _shift_guard_name(r, employee_names, security_guard_names),
            "guard_type": r.get("security_guard"),
            "farm": farm_name,
            "farm_color": color,
            "block": r.get("block") or "",
            "shift_type": r.get("shift_type"),
            "start_date": str(r["start_date"]) if r.get("start_date") else None,
            "end_date": str(r["end_date"]) if r.get("end_date") else None,
            "status": r.get("status"),
            "remarks": r.get("remarks") or "",
        })

    # Today's coverage board: farm -> {Day: guard_name, Night: guard_name}
    coverage = {f["farm"]: {"Day": None, "Night": None} for f in board_farms}
    for r in all_rows:
        start = frappe.utils.getdate(r["start_date"]) if r.get("start_date") else None
        end = frappe.utils.getdate(r["end_date"]) if r.get("end_date") else None
        if not (start and start <= today and (not end or end >= today)):
            continue
        slot = coverage.setdefault(r.get("farm"), {"Day": None, "Night": None})
        slot[r.get("shift_type")] = _shift_guard_name(r, employee_names, security_guard_names)

    coverage_board = [
        {"farm": farm_name, "day_guard": slots.get("Day"), "night_guard": slots.get("Night")}
        for farm_name, slots in coverage.items()
    ]
    coverage_board.sort(key=lambda x: x["farm"] or "")

    filled_slots = sum(
        1 for c in coverage_board for key in ("day_guard", "night_guard") if c[key]
    )
    total_slots = len(coverage_board) * 2

    # Rotation metric: guards who have covered more than one distinct farm.
    guard_farms = {}
    for r in all_rows:
        key = _shift_guard_key(r)
        if not key or not r.get("farm"):
            continue
        guard_farms.setdefault(key, set()).add(r["farm"])
    guards_on_rotation = sum(1 for farms_set in guard_farms.values() if len(farms_set) > 1)

    day_count = sum(1 for r in rows if r["shift_type"] == "Day" and r["status"] == "Active")
    night_count = sum(1 for r in rows if r["shift_type"] == "Night" and r["status"] == "Active")

    return {
        "success": True,
        "range_from": str(range_from),
        "range_to": str(range_to),
        "summary": {
            "total_assignments": len(rows),
            "day_shift_count": day_count,
            "night_shift_count": night_count,
            "farms_covered": sum(
                1 for c in coverage_board if c["day_guard"] or c["night_guard"]
            ),
            "farms_total": len(coverage_board),
            "unfilled_slots": total_slots - filled_slots,
            "guards_on_rotation": guards_on_rotation,
        },
        "coverage_board": coverage_board,
        "rows": rows,
        "farm_colors": farm_colors,
        "filter_options": {
            "farms": [f["farm"] for f in company_farms],
            "shift_types": ["Day", "Night"],
            "statuses": ["Active", "Cancelled"],
            "companies": [
                c.name
                for c in frappe.get_list("Company", fields=["name"], order_by="name asc", page_length=200)
            ],
        },
    }


@frappe.whitelist()
def get_farm_boundaries() -> dict[str, Any]:
    """
    Return, for every Farm that has a boundary GeoJSON file attached,
    the farm name and a URL the client can fetch the GeoJSON from.
    Farms without a boundary uploaded yet are simply omitted.
    """

    if not frappe.has_permission("Farm", ptype="read"):
        frappe.throw(
            _("You do not have permission to view Farms."),
            frappe.PermissionError,
        )

    farm_meta = frappe.get_meta("Farm")
    if not farm_meta.has_field("boundary_geojson"):
        # This site's Farm doctype (e.g. upande_core's, not upande_kaitet's)
        # has nowhere to store a boundary at all yet - same "just omit it"
        # treatment as a Farm that simply hasn't had one uploaded, rather
        # than erroring the whole Patrol Map over a field that doesn't exist
        # here.
        return {"success": True, "boundaries": []}

    farm_name_field = _farm_name_field()
    farms = frappe.get_list(
        "Farm",
        filters={"boundary_geojson": ["is", "set"]},
        fields=["name", farm_name_field, "boundary_geojson"],
        order_by=f"{farm_name_field} asc",
        page_length=500,
    )
    farms = [{"name": f["name"], "farm": f.get(farm_name_field), "boundary_geojson": f["boundary_geojson"]} for f in farms]

    return {
        "success": True,
        "boundaries": [
            {
                "farm": f.get("farm") or f.get("name"),
                "url": f.get("boundary_geojson"),
            }
            for f in farms
        ],
    }


# ─────────────────────────────────────────────────────────────────
# END SHIFT PLANNING DASHBOARD API
# ─────────────────────────────────────────────────────────────────
