# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""CCTV Alerts: create, de-duplicate, notify, escalate, and the guard's actions.

Every alert carries clip_start / clip_end (event time minus pre-roll, plus
post-roll), so the link in a notification opens the exact footage - the
recipient never searches the recorder.

Rules (CCTV Alert Rule) are optional. With no rule for a trigger, the
trigger's default severity applies and the people who already receive
security alerts (Security Ops Settings > Notification Rules) are told - so
the module is useful before anyone has written a rule, and the routing the
client already configured is reused rather than duplicated.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from upande_security.cctv.settings import get_settings, is_on

DEFAULT_SEVERITY = {
	"Entry in Forbidden Hours": "High", "Unauthorized Person": "High", "Unknown Person": "Medium",
	"Door Open Too Long": "Medium", "Dwell Exceeded": "High", "Tailgating": "Medium",
	"Unregistered Vehicle": "Medium", "Watchlisted Vehicle": "Critical", "Vehicle Overstay": "Low",
	"Vehicle After Hours": "Medium", "Vehicle in Wrong Zone": "High", "Exit Not Recorded": "Low",
	"Arrived Before Approval": "Low", "Gate Mismatch": "Low", "Camera Tamper": "Medium",
	"Video Loss": "Medium", "Recording Gap": "Medium", "Camera Offline": "Medium", "Agent Offline": "High",
}
# Minutes to acknowledge before escalating, by severity (rule overrides).
ACK_MINUTES = {"Info": 0, "Low": 0, "Medium": 15, "High": 5, "Critical": 2}
DEFAULT_DEBOUNCE_SECONDS = 300


# ------------------------------------------------------------------ rules

def _window_active(rule, when):
	if not rule.windows:
		return True
	day = when.strftime("%A")
	for w in rule.windows:
		days = w.days or "Every Day"
		ok_day = (
			days == "Every Day"
			or days == day
			or (days == "Monday to Friday" and when.weekday() < 5)
			or (days == "Monday to Saturday" and when.weekday() < 6)
			or (days == "Weekends" and when.weekday() >= 5)
		)
		if not ok_day:
			continue
		t = when.time()
		start, end = get_datetime(f"2000-01-01 {w.from_time}").time(), get_datetime(f"2000-01-01 {w.to_time}").time()
		if (start <= t <= end) if start <= end else (t >= start or t <= end):
			return True
	return False


def find_rule(trigger_type, farm=None, zone=None, camera=None):
	"""The most specific enabled rule for this trigger (camera > zone > site > any)."""
	rules = frappe.get_all("CCTV Alert Rule", filters={"enabled": 1, "trigger_type": trigger_type},
		fields=["name", "farm", "zone", "camera"])
	best, best_rank = None, -1
	for r in rules:
		if (r.farm and r.farm != farm) or (r.zone and r.zone != zone) or (r.camera and r.camera != camera):
			continue
		rank = (4 if r.camera else 0) + (2 if r.zone else 0) + (1 if r.farm else 0)
		if rank > best_rank:
			best, best_rank = r, rank
	return frappe.get_cached_doc("CCTV Alert Rule", best.name) if best else None


# ------------------------------------------------------------------ create

def raise_alert(trigger_type, farm=None, camera=None, zone=None, event_time=None, source_event=None,
		summary=None, severity=None, plate=None, vehicle_visit=None, appointment=None, person_name=None,
		person_profile=None, confidence=None, snapshot=None, subject_key=None, force=False, hold_seconds=0, guard=None):
	"""Create (or bump) one alert. Returns the CCTV Alert name, or None when
	alerts are off, the rule is outside its active window, or nothing applies."""
	if not (force or is_on("alerts_enabled")):
		return None
	s = get_settings()
	when = get_datetime(event_time) if event_time else now_datetime()
	if camera and not zone:
		zone = frappe.db.get_value("CCTV Camera", camera, "zone")
	if camera and not farm:
		farm = frappe.db.get_value("CCTV Camera", camera, "farm")

	rule = find_rule(trigger_type, farm, zone, camera)
	if rule and not _window_active(rule, when):
		return None
	severity = severity or (rule.severity if rule else None) or DEFAULT_SEVERITY.get(trigger_type, "Medium")

	key = "|".join(str(x or "") for x in (trigger_type, farm, zone or camera, subject_key or plate or person_name))
	debounce = (rule.debounce_seconds if rule and rule.debounce_seconds is not None else DEFAULT_DEBOUNCE_SECONDS)
	if debounce:
		existing = frappe.get_all("CCTV Alert",
			filters={"debounce_key": key, "status": ["in", ["Open", "Acknowledged", "Escalated"]],
				"modified": [">=", add_to_date(now_datetime(), seconds=-debounce)]},
			fields=["name", "repeat_count"], limit=1)
		if existing:
			frappe.db.set_value("CCTV Alert", existing[0].name,
				{"repeat_count": (existing[0].repeat_count or 0) + 1, "last_repeat_at": now_datetime()})
			return existing[0].name

	pre = rule.pre_roll_seconds if rule and rule.pre_roll_seconds else s.pre_roll_seconds
	post = rule.post_roll_seconds if rule and rule.post_roll_seconds else s.post_roll_seconds
	ack = (rule.ack_within_minutes if rule and rule.require_ack and rule.ack_within_minutes else ACK_MINUTES.get(severity, 0))

	doc = frappe.get_doc({
		"doctype": "CCTV Alert",
		"alert_type": trigger_type,
		"severity": severity,
		"status": "Open",
		"summary": summary,
		"farm": farm,
		"company": frappe.db.get_value("Farm", farm, "company") if farm else None,
		"zone": zone,
		"camera": camera,
		"rule": rule.name if rule else None,
		"event_time": when,
		"clip_start": add_to_date(when, seconds=-pre),
		"clip_end": add_to_date(when, seconds=post),
		"source_event": source_event,
		"snapshot": snapshot,
		"plate": plate,
		"vehicle_visit": vehicle_visit,
		"appointment": appointment,
		"person_name": person_name,
		"person_profile": person_profile,
		"confidence": confidence,
		"debounce_key": key,
		"hold_until": add_to_date(now_datetime(), seconds=hold_seconds) if hold_seconds else None,
		"next_escalation_at": add_to_date(now_datetime(), seconds=(hold_seconds or 0) + ack * 60) if ack else None,
		"security_guard": (guard or {}).get("security_guard"),
		"guard_employee": (guard or {}).get("employee"),
		"guard_name": (guard or {}).get("name"),
	})
	if zone:
		for cam in frappe.get_all("CCTV Camera", filters={"zone": zone, "enabled": 1, "name": ["!=", camera or ""]}, pluck="name", limit=6):
			doc.append("related_cameras", {"camera": cam, "reason": "Same zone"})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.insert()
	if not hold_seconds:
		notify(doc, rule)
	# else: guard_match.release_held notifies when the hold ends, unless a guard explains it first
	return doc.name


# ------------------------------------------------------------------ notify

def _role_users(roles):
	if not roles:
		return []
	users = frappe.get_all("Has Role", filters={"role": ["in", list(roles)], "parenttype": "User"}, pluck="parent", distinct=True)
	return [u for u in users if u not in ("Administrator", "Guest")
		and frappe.db.get_value("User", u, "enabled")]


def _recipients(rule, level=0):
	"""[(user, channel)] for the rule (level 0) or an escalation level."""
	from upande_security.utils.notifications import resolve_notification_users

	out = []
	rows = []
	if rule:
		rows = rule.recipients if level == 0 else [r for r in rule.escalation if r.level == level]
	for r in rows:
		if getattr(r, "recipient_type", "Role") == "User" or (level and r.user):
			if r.user:
				out.append((r.user, r.channel or "On Screen"))
		elif r.role:
			out.extend((u, r.channel or "On Screen") for u in _role_users([r.role]))
	if not out:
		kind = "security" if level == 0 else "escalation"
		out = [(u, "On Screen") for u in resolve_notification_users(kind)]
	seen, unique = set(), []
	for u, ch in out:
		if (u, ch) not in seen:
			seen.add((u, ch))
			unique.append((u, ch))
	return unique


def _message(doc):
	when = frappe.utils.format_datetime(doc.event_time, "d MMM yyyy HH:mm")
	where = " / ".join(filter(None, [doc.farm, doc.zone, doc.camera and frappe.db.get_value("CCTV Camera", doc.camera, "camera_name")]))
	who = doc.plate or doc.person_name or ""
	subject = f"[{(doc.severity or '').upper()}] {doc.alert_type}" + (f" – {who}" if who else "")
	link = frappe.utils.get_url(f"/app/cctv-alert/{doc.name}")
	body = (f"{doc.alert_type}<br>Where: {where or '-'}<br>Time: {when}"
		+ (f"<br>Who: {who}" if who else "")
		+ (f"<br>{doc.summary}" if doc.summary else "")
		+ f"<br><br>Open with exact playback: <a href='{link}'>{link}</a>")
	return subject, body, link


def notify(doc, rule=None, level=0):
	from upande_security.cctv.channels import deliver

	subject, body, link = _message(doc)
	sent_group = set()
	for user, channel in _recipients(rule, level):
		status, error, fell_back = deliver(channel, user, subject, body, doc.name, link, sent_group)
		doc.append("notifications", {"channel": channel + (" -> On Screen" if fell_back else ""), "recipient": user,
			"sent_at": now_datetime(), "delivery_status": status, "error": error})
		frappe.publish_realtime("cctv_alert", {"name": doc.name, "alert_type": doc.alert_type, "severity": doc.severity,
			"subject": subject, "link": link}, user=user, after_commit=True)
	doc.flags.ignore_permissions = True
	doc.save()


def escalate_due():
	"""Scheduler (every minute): alerts nobody acknowledged in time move up a level."""
	if not is_on("alerts_enabled"):
		return
	for name in frappe.get_all("CCTV Alert", filters={"status": ["in", ["Open", "Escalated"]],
			"next_escalation_at": ["<=", now_datetime()]}, pluck="name", limit=200):
		doc = frappe.get_doc("CCTV Alert", name)
		rule = frappe.get_cached_doc("CCTV Alert Rule", doc.rule) if doc.rule else None
		level = (doc.escalation_level or 0) + 1
		levels = sorted({r.level for r in rule.escalation}) if rule else []
		next_row = next((r for r in (rule.escalation if rule else []) if r.level == level + 1), None)
		doc.escalation_level = level
		doc.status = "Escalated"
		if next_row:
			doc.next_escalation_at = add_to_date(now_datetime(), minutes=next_row.after_minutes or 10)
		elif doc.severity == "Critical":
			doc.next_escalation_at = add_to_date(now_datetime(), minutes=ACK_MINUTES["Critical"])  # repeat until acknowledged
		else:
			doc.next_escalation_at = None
		notify(doc, rule, level if (not levels or level in levels) else 0)


# ------------------------------------------------------------------ actions

def _get_for_write(name):
	doc = frappe.get_doc("CCTV Alert", name)
	if not frappe.has_permission("CCTV Alert", "write", doc):
		frappe.throw(_("You cannot act on this alert."), frappe.PermissionError)
	return doc


@frappe.whitelist()
def mark_viewed(name):
	doc = frappe.get_doc("CCTV Alert", name)
	if not frappe.has_permission("CCTV Alert", "read", doc):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	if not doc.first_viewed_by:
		frappe.db.set_value("CCTV Alert", name, {"first_viewed_by": frappe.session.user, "first_viewed_at": now_datetime()})
	return {"ok": True}


@frappe.whitelist()
def acknowledge(name, note=None):
	doc = _get_for_write(name)
	doc.status = "Acknowledged"
	doc.acknowledged_by = frappe.session.user
	doc.acknowledged_at = now_datetime()
	doc.next_escalation_at = None
	if note:
		doc.resolution_notes = ((doc.resolution_notes or "") + "\n" + note).strip()
	doc.save()
	return {"ok": True, "status": doc.status}


@frappe.whitelist()
def resolve(name, notes=None):
	doc = _get_for_write(name)
	doc.status = "Resolved"
	doc.resolved_at, doc.resolved_by = now_datetime(), frappe.session.user
	doc.next_escalation_at = None
	if notes:
		doc.resolution_notes = notes
	doc.save()
	return {"ok": True, "status": doc.status}


@frappe.whitelist()
def mark_false_alarm(name, reason, notes=None):
	if not reason:
		frappe.throw(_("Choose why it was a false alarm - it is used to tune the rules."))
	doc = _get_for_write(name)
	doc.status = "False Alarm"
	doc.resolved_at, doc.resolved_by = now_datetime(), frappe.session.user
	doc.false_alarm_reason = reason
	doc.next_escalation_at = None
	if notes:
		doc.resolution_notes = notes
	doc.save()
	return {"ok": True, "status": doc.status}


@frappe.whitelist()
def escalate(name):
	doc = _get_for_write(name)
	doc.next_escalation_at = now_datetime()
	doc.save()
	escalate_due()
	return {"ok": True}


@frappe.whitelist()
def create_incident(name):
	"""Open an Incident Report from the alert, carrying its facts across."""
	doc = _get_for_write(name)
	if doc.incident:
		return {"ok": True, "incident": doc.incident}
	inc = frappe.get_doc({
		"doctype": "Incident Report",
		"incident_datetime": doc.event_time,
		"farm": doc.farm,
		"location": " / ".join(filter(None, [doc.zone, doc.camera])),
		"severity": {"Critical": "Critical", "High": "High", "Medium": "Medium"}.get(doc.severity, "Low"),
		"nature_of_incident": "Intrusion" if doc.alert_type in ("Entry in Forbidden Hours", "Unauthorized Person", "Unknown Person", "Tailgating")
			else "Suspicious Activity",
		"description": f"From CCTV alert {doc.name}: {doc.alert_type}. {doc.summary or ''}"
			+ (f" Plate {doc.plate}." if doc.plate else "")
			+ f"\nFootage: {frappe.utils.get_url('/app/cctv-alert/' + doc.name)}",
		"reported_by": frappe.session.user,
	})
	inc.flags.ignore_mandatory = True
	inc.flags.ignore_links = True
	inc.insert()
	doc.incident = inc.name
	doc.save()
	return {"ok": True, "incident": inc.name}
