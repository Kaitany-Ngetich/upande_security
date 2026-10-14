# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Which app version each login runs, and pushing updates to outdated phones.

The gate app reports its version on every open (report_app_version) onto the
login's Guard Device Token - the same record the push token lives on. Update
Status compares each phone with the newest over-the-air update any phone on
the same channel has reported, so nothing has to be kept in sync by hand:

- Up to date: running the newest update seen on its channel.
- Outdated: an older update, or the original install with an update out.
- Needs New Install: an older native build (runtime) that over-the-air
  updates can no longer reach - needs the new APK.
- Unknown (old app): never reported a version, i.e. still on an app from
  before version reporting existed - itself a sign it is out of date.

push_app_update sends an "app_update" push; the app downloads the update and
restarts itself on receipt (or when the guard taps the notification).
"""

import frappe

from upande_security.api.notifications import _send_expo_push
from upande_security.api.sos_alert import _resolve_calling_guard

_MANAGER_ROLES = ("Security Head", "System Manager")


def _token_filters(guard_type, guard_id):
	filters = {"guard_type": guard_type}
	if guard_type == "Internal Guard":
		filters["internal_guard"] = guard_id
	elif guard_type == "External Guard":
		filters["external_guard"] = guard_id
	else:
		filters["app_user"] = guard_id
	return filters


def device_token_for_session():
	"""The calling login's Guard Device Token (a new unsaved one if none)."""
	guard_type, guard_id, guard_name = _resolve_calling_guard()
	existing = frappe.db.get_value("Guard Device Token", _token_filters(guard_type, guard_id), "name")
	if existing:
		doc = frappe.get_doc("Guard Device Token", existing)
	else:
		doc = frappe.new_doc("Guard Device Token")
		doc.guard_type = guard_type
		for field, value in _token_filters(guard_type, guard_id).items():
			doc.set(field, value)
	doc.login_user = frappe.session.user
	doc.guard_name = guard_name
	return doc


@frappe.whitelist(methods=["POST"])
def report_app_version(
	app_version=None,
	runtime_version=None,
	update_id=None,
	update_created_at=None,
	update_channel=None,
	is_embedded_launch=None,
	device_model=None,
	os_version=None,
	platform=None,
):
	"""Called by the app on every open. Never fails the app: errors are
	logged and reported back softly."""
	try:
		doc = device_token_for_session()
		doc.app_version = (app_version or "")[:140]
		doc.runtime_version = (runtime_version or "")[:140]
		doc.update_id = (update_id or "")[:140]
		doc.update_channel = (update_channel or "")[:140]
		doc.update_created_at = _parse_datetime(update_created_at)
		doc.is_embedded_launch = 1 if str(is_embedded_launch).lower() in ("1", "true") else 0
		doc.device_model = (device_model or "")[:140]
		doc.os_version = (os_version or "")[:140]
		if platform in ("ios", "android"):
			doc.platform = platform
		doc.last_app_open = frappe.utils.now_datetime()
		doc.save(ignore_permissions=True)
		refresh_update_status()
		frappe.db.commit()
		return {"name": doc.name, "update_status": frappe.db.get_value("Guard Device Token", doc.name, "update_status")}
	except Exception as e:
		frappe.log_error("report_app_version", frappe.get_traceback())
		return {"error": str(e)}


def _parse_datetime(value):
	"""App sends ISO-8601 UTC (e.g. 2026-10-14T11:02:03.000Z); stored as the
	site's local time like every other Datetime."""
	if not value:
		return None
	try:
		from dateutil import parser

		dt = parser.isoparse(str(value))
		if dt.tzinfo:
			from zoneinfo import ZoneInfo

			dt = dt.astimezone(ZoneInfo(frappe.utils.get_system_timezone())).replace(tzinfo=None)
		return dt
	except Exception:
		return None


def _version_key(version):
	parts = []
	for piece in str(version or "").split("."):
		parts.append(int(piece) if piece.isdigit() else 0)
	return tuple(parts)


def refresh_update_status():
	"""Recompute Update Status on every Guard Device Token (a few hundred
	rows at most), writing only the ones that changed."""
	rows = frappe.get_all(
		"Guard Device Token",
		fields=["name", "app_version", "runtime_version", "update_channel", "update_created_at", "update_status"],
	)
	runtimes = [r.runtime_version for r in rows if r.runtime_version]
	newest_runtime = max(runtimes, key=_version_key) if runtimes else None
	newest_by_channel = {}
	for r in rows:
		if r.runtime_version == newest_runtime and r.update_created_at:
			channel = r.update_channel or ""
			if channel not in newest_by_channel or r.update_created_at > newest_by_channel[channel]:
				newest_by_channel[channel] = r.update_created_at
	for r in rows:
		if not r.app_version and not r.runtime_version:
			status = "Unknown (old app)"
		elif r.runtime_version and newest_runtime and _version_key(r.runtime_version) < _version_key(newest_runtime):
			status = "Needs New Install"
		else:
			newest = newest_by_channel.get(r.update_channel or "")
			if newest and (not r.update_created_at or r.update_created_at < newest):
				status = "Outdated"
			else:
				status = "Up to date"
		if status != r.update_status:
			frappe.db.set_value("Guard Device Token", r.name, "update_status", status, update_modified=False)


def _require_manager():
	if not any(role in _MANAGER_ROLES for role in frappe.get_roles()):
		frappe.throw("Only a Security Head or System Manager can push app updates.", frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def push_app_update(names=None):
	"""Send the update push to the given Guard Device Tokens."""
	_require_manager()
	names = frappe.parse_json(names) if isinstance(names, str) else (names or [])
	return _push(names)


@frappe.whitelist(methods=["POST"])
def push_update_to_outdated():
	"""Send the update push to every phone that is not up to date."""
	_require_manager()
	refresh_update_status()
	names = frappe.get_all(
		"Guard Device Token",
		filters={"update_status": ["in", ["Outdated", "Unknown (old app)"]]},
		pluck="name",
	)
	return _push(names)


def _push(names):
	rows = frappe.get_all(
		"Guard Device Token",
		filters={"name": ["in", names or [""]]},
		fields=["name", "expo_push_token", "update_status"],
	)
	targets = [r for r in rows if r.expo_push_token]
	messages = [
		{
			"to": r.expo_push_token,
			"title": "App update available",
			"body": "Tap to install the latest Security Gate update.",
			"data": {"type": "app_update"},
			"priority": "high",
			"sound": "default",
			"channelId": "visitor-approved",
		}
		for r in targets
	]
	result = _send_expo_push(messages)
	now = frappe.utils.now_datetime()
	for r in targets:
		frappe.db.set_value(
			"Guard Device Token",
			r.name,
			{"update_requested_at": now, "update_requested_by": frappe.session.user},
			update_modified=False,
		)
	frappe.db.commit()
	return {
		"pushed": len(targets),
		"no_push_token": len(rows) - len(targets),
		"needs_new_install": len([r for r in targets if r.update_status == "Needs New Install"]),
		"error": result.get("error"),
	}
