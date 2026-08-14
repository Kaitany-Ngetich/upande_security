# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Nearby-guard SOS alerting.

Relying solely on the Security Head/supervisor to reach a distressed guard
can be slow — this adds a second, faster channel: every OTHER guard whose
last known GPS position is within range gets alerted directly, so whoever's
physically closest can respond immediately rather than waiting for the
Security Head to relay it.

Delivery is via Expo's push service (https://exp.host/--/api/v2/push/send)
— every registered guard device gets a `data`-only push carrying enough for
the app to trigger a full-screen, ringing incoming-alert (via
react-native-callkeep) rather than a normal notification banner. See
[[reference_upande_security_sos_ios_voip_push_caveat]]-equivalent note: true
"rings even when the app is killed" on iOS additionally needs a VoIP push
(PushKit/CallKit) backed by an Apple VoIP certificate — that's account-level
setup outside what a push through Expo's *standard* service can guarantee.
Android reaches full spec through Expo's standard service alone (FCM
data push + a full-screen-intent notification client-side).
"""

import json
import math
import urllib.request

import frappe

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EARTH_RADIUS_M = 6371000.0


def _haversine_m(lat1, lng1, lat2, lng2):
	r1, r2 = math.radians(lat1), math.radians(lat2)
	dlat = math.radians(lat2 - lat1)
	dlng = math.radians(lng2 - lng1)
	a = math.sin(dlat / 2) ** 2 + math.cos(r1) * math.cos(r2) * math.sin(dlng / 2) ** 2
	return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _resolve_calling_guard():
	"""Same resolution order as get_security_head_contact.py and
	submit_patrol_points.py: Employee via user_id first, then Security Guard
	by full_name match. Falls back to "App User" so ANY authenticated Frappe
	login always resolves to something — not just Employees/Security Guards
	— since any logged-in user can now register a push token and take part
	in nearby-guard SOS alerting."""
	current_user = frappe.session.user
	employee = frappe.db.get_value("Employee", {"user_id": current_user}, ["name", "employee_name"], as_dict=True)
	if employee:
		return "Internal Guard", employee.name, employee.employee_name

	user_full = frappe.db.get_value("User", current_user, "full_name")
	if user_full:
		guard = frappe.db.get_value("Security Guard", {"full_name": user_full}, ["name", "full_name"], as_dict=True)
		if guard:
			return "External Guard", guard.name, guard.full_name

	app_user_name = user_full or current_user
	return "App User", current_user, app_user_name


@frappe.whitelist()
def register_push_token(expo_push_token, platform=None, lat=None, lng=None):
	"""Call this on app start/login so the backend always has a current
	device to reach this guard on. Upserts — a guard reinstalling the app or
	switching phones replaces their old token rather than accumulating
	stale ones."""
	guard_type, guard_id, _ = _resolve_calling_guard()
	if not guard_id:
		frappe.response["message"] = {"error": "No Employee or Security Guard record linked to this login"}
		return

	filters = {"guard_type": guard_type}
	if guard_type == "Internal Guard":
		filters["internal_guard"] = guard_id
	elif guard_type == "External Guard":
		filters["external_guard"] = guard_id
	else:
		filters["app_user"] = guard_id

	existing_name = frappe.db.get_value("Guard Device Token", filters, "name")
	if existing_name:
		doc = frappe.get_doc("Guard Device Token", existing_name)
	else:
		doc = frappe.new_doc("Guard Device Token")
		doc.guard_type = guard_type
		if guard_type == "Internal Guard":
			doc.internal_guard = guard_id
		elif guard_type == "External Guard":
			doc.external_guard = guard_id
		else:
			doc.app_user = guard_id

	doc.expo_push_token = expo_push_token
	if platform:
		doc.platform = platform
	if lat is not None:
		doc.last_seen_lat = lat
	if lng is not None:
		doc.last_seen_lng = lng
	doc.updated_at = frappe.utils.now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	frappe.response["message"] = {"registered": True, "name": doc.name}


@frappe.whitelist()
def ping_location(lat, lng):
	"""Cheap periodic location update for any logged-in user's own Guard
	Device Token — NOT full patrol GPS tracking (see submit_patrol_points.py
	for that). This is the location source `_nearby_guard_tokens()` uses
	for guard_type == "App User" rows, since there's no Patrol GPS Log for
	non-patrolling app users. Call this every few minutes from the mobile
	app for any logged-in user who isn't actively on a tracked patrol."""
	guard_type, guard_id, _ = _resolve_calling_guard()
	if not guard_id:
		frappe.response["message"] = {"error": "No Employee, Security Guard, or User record linked to this login"}
		return

	filters = {"guard_type": guard_type}
	if guard_type == "Internal Guard":
		filters["internal_guard"] = guard_id
	elif guard_type == "External Guard":
		filters["external_guard"] = guard_id
	else:
		filters["app_user"] = guard_id

	existing_name = frappe.db.get_value("Guard Device Token", filters, "name")
	if not existing_name:
		frappe.response["message"] = {
			"error": "No Guard Device Token registered yet for this login — call register_push_token first"
		}
		return

	doc = frappe.get_doc("Guard Device Token", existing_name)
	doc.last_seen_lat = lat
	doc.last_seen_lng = lng
	doc.updated_at = frappe.utils.now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	frappe.response["message"] = {"updated": True, "name": doc.name}


def _nearby_guard_tokens(latitude, longitude, exclude_guard_type, exclude_guard_id):
	"""Every OTHER guard with a registered push token whose most recent
	Patrol GPS Log ping is both recent enough and close enough to
	(latitude, longitude). Settings-driven radius/staleness so this can be
	tuned per how spread out a farm actually is without a code change."""
	settings = frappe.db.get_value(
		"Security Ops Settings",
		"Security Ops Settings",
		["nearby_guard_alert_radius_m", "nearby_alert_stale_minutes"],
		as_dict=True,
	)
	radius_m = (settings.nearby_guard_alert_radius_m if settings else None) or 1500
	stale_minutes = (settings.nearby_alert_stale_minutes if settings else None) or 30
	stale_cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-stale_minutes)

	# ignore_permissions: this has to see every guard's token to find who's
	# nearby, not just the caller's own row. Gate Guard's if_owner=1 on this
	# doctype (added for the hierarchical access-scoping fix) is correct for
	# Desk/API access in general, but would otherwise silently reduce this
	# to "only my own row" and, combined with the self-exclusion below,
	# make every alert come back empty.
	tokens = frappe.get_all(
		"Guard Device Token",
		fields=[
			"name",
			"guard_type",
			"internal_guard",
			"external_guard",
			"app_user",
			"expo_push_token",
			"last_seen_lat",
			"last_seen_lng",
			"updated_at",
		],
		ignore_permissions=True,
	)

	alertable = []
	for t in tokens:
		if t.guard_type == exclude_guard_type and (
			(t.guard_type == "Internal Guard" and t.internal_guard == exclude_guard_id)
			or (t.guard_type == "External Guard" and t.external_guard == exclude_guard_id)
			or (t.guard_type == "App User" and t.app_user == exclude_guard_id)
		):
			continue

		if t.guard_type == "Internal Guard":
			guard_filter = {"personel": "Internal Guard", "internal_guard": t.internal_guard}
			guard_id = t.internal_guard
			guard_name = frappe.db.get_value("Employee", t.internal_guard, "employee_name") or t.internal_guard
		elif t.guard_type == "External Guard":
			guard_filter = {"personel": "External Guard", "external_guard": t.external_guard}
			guard_id = t.external_guard
			guard_name = frappe.db.get_value("Security Guard", t.external_guard, "full_name") or t.external_guard
		else:
			guard_id = t.app_user
			guard_name = frappe.db.get_value("User", t.app_user, "full_name") or t.app_user

			if t.updated_at and frappe.utils.get_datetime(t.updated_at) >= frappe.utils.get_datetime(stale_cutoff):
				try:
					g_lat = float(t.last_seen_lat)
					g_lng = float(t.last_seen_lng)
				except (TypeError, ValueError):
					continue

				distance_m = _haversine_m(float(latitude), float(longitude), g_lat, g_lng)
				if distance_m <= radius_m:
					alertable.append(
						{
							"guard_id": guard_id,
							"guard_name": guard_name,
							"expo_push_token": t.expo_push_token,
							"distance_m": round(distance_m),
						}
					)
			continue

		# ignore_permissions: same reasoning as the Guard Device Token fetch
		# above — this is reading a DIFFERENT guard's GPS ping, not the
		# caller's own, and Patrol GPS Log's DocPerm (if_owner=1 for
		# Employee/Security Guard, no Gate Guard row at all) would silently
		# filter this down to nothing for any real caller.
		latest = frappe.get_all(
			"Patrol GPS Log",
			filters=guard_filter,
			fields=["latitude", "longitude", "captured_at"],
			order_by="captured_at desc",
			limit_page_length=1,
			ignore_permissions=True,
		)
		if not latest:
			continue
		if frappe.utils.get_datetime(latest[0].captured_at) < frappe.utils.get_datetime(stale_cutoff):
			continue

		try:
			g_lat = float(latest[0].latitude)
			g_lng = float(latest[0].longitude)
		except (TypeError, ValueError):
			continue

		distance_m = _haversine_m(float(latitude), float(longitude), g_lat, g_lng)
		if distance_m <= radius_m:
			alertable.append(
				{
					"guard_id": guard_id,
					"guard_name": guard_name,
					"expo_push_token": t.expo_push_token,
					"distance_m": round(distance_m),
				}
			)

	return alertable


def _send_expo_push(messages):
	"""Fire-and-forget batch send to Expo's push API. Never raises — a
	push-delivery failure must not surface as an SOS failure to the
	distressed guard; it's logged and swallowed."""
	if not messages:
		return {"sent": 0}
	try:
		body = json.dumps(messages).encode()
		req = urllib.request.Request(
			EXPO_PUSH_URL,
			data=body,
			headers={"Content-Type": "application/json", "Accept": "application/json"},
			method="POST",
		)
		with urllib.request.urlopen(req, timeout=10) as resp:
			result = json.loads(resp.read())
		return {"sent": len(messages), "expo_response": result}
	except Exception as e:
		frappe.log_error("SOS nearby-guard push send", str(e))
		return {"sent": 0, "error": str(e)}


@frappe.whitelist()
def trigger_nearby_guard_alert(latitude, longitude, incident_name=None):
	"""Called right after (or alongside) the SOS incident is created on the
	client. Resolves who's calling, finds every other guard currently within
	range, and pushes each of them a data-only alert carrying enough for the
	app to show a full-screen ringing "guard needs help" screen rather than
	a normal notification banner.

	Never blocks or fails the SOS flow itself — every branch below degrades
	to an empty/error result rather than throwing, since by the time this is
	called the guard has already dialed and filed the incident; this is
	strictly an additional channel, not the primary one.
	"""
	guard_type, guard_id, guard_name = _resolve_calling_guard()
	guard_name = guard_name or "A guard"

	try:
		nearby = _nearby_guard_tokens(latitude, longitude, guard_type, guard_id)
	except Exception as e:
		frappe.log_error("trigger_nearby_guard_alert resolve", str(e))
		frappe.response["message"] = {"alerted": 0, "error": str(e)}
		return

	messages = []
	for g in nearby:
		messages.append(
			{
				"to": g["expo_push_token"],
				"priority": "high",
				"sound": "default",
				"title": "SOS — " + guard_name + " needs help",
				"body": guard_name + " is " + str(g["distance_m"]) + "m away and triggered an SOS.",
				"data": {
					"type": "sos_alert",
					"guard_name": guard_name,
					"latitude": latitude,
					"longitude": longitude,
					"incident_name": incident_name or "",
					"distance_m": g["distance_m"],
				},
				"channelId": "sos-alerts",
			}
		)

	send_result = _send_expo_push(messages)

	frappe.response["message"] = {
		"alerted": len(nearby),
		"guards": [{"guard_name": g["guard_name"], "distance_m": g["distance_m"]} for g in nearby],
		"push_result": send_result,
	}
