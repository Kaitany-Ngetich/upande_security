# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""The Security Dashboard's guard ranking as a report: downloaded (Excel,
CSV or PDF), emailed on demand from the dashboard's Send report button, and
emailed on a schedule to the people in Security Ops Settings' Guard Ranking
Report table.

Every figure comes from patrol_ranking.get_guard_ranking, so the report
always says what the dashboard says. Run from the dashboard it uses the
viewer's own farm permissions; the scheduled job runs as Administrator and
is narrowed by each subscription's company / farm instead.
"""

import csv
import io
import re

import frappe
from frappe import _

from upande_security.api.patrol_ranking import get_guard_ranking

# Who may email the report to other people from the dashboard. Downloading
# only needs what viewing the ranking needs.
SEND_ROLES = ("System Manager", "Security Head", "Security Manager")
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
PERIOD_LABELS = {
	"this_week": "This week",
	"last_week": "Last week",
	"this_month": "This month",
	"last_month": "Last month",
	"custom": "Custom",
}

COLUMNS = [
	("farm", "Farm"),
	("rank", "Rank"),
	("name", "Guard"),
	("kind", "Type"),
	("score", "Score"),
	("area_ha", "Area patrolled (ha)"),
	("coverage_pct", "Coverage (%)"),
	("cells", "Grid cells"),
	("distance_km", "Distance (km)"),
	("patrol_hours", "Patrol time (h)"),
	("patrols", "Patrols"),
	("valid_scans", "Valid scans"),
	("scans", "All scans"),
	("shifts", "Shifts"),
	("incidents_scored", "Incidents on shift (scored)"),
	("incidents", "Incidents on shift (all)"),
	("incidents_serious", "Serious incidents"),
]


def _ranking(period=None, from_date=None, to_date=None, farm=None, company=None):
	return get_guard_ranking(
		period=period or "this_week", from_date=from_date, to_date=to_date, farm=farm, company=company
	)


def _scope_label(farm=None, company=None):
	return farm or company or "All farms"


def _fmt_hours(h):
	m = int(round((h or 0) * 60))
	return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def _fmt_ha(x):
	if x is None:
		return "—"
	return f"{x:.0f} ha" if x >= 100 else (f"{x:.1f} ha" if x >= 10 else f"{x:.2f} ha")


def _table_rows(data):
	"""Header plus one row per guard, then each farm's total row - the
	same figures as the dashboard table, for Excel and CSV."""
	out = [[label for _k, label in COLUMNS]]
	by_farm = {}
	for r in data.get("rows") or []:
		by_farm.setdefault(r["farm"], []).append(r)
	for f in data.get("farms") or []:
		for r in by_farm.get(f["farm"], []):
			out.append([r.get(k) for k, _l in COLUMNS])
		out.append([
			f["farm"], "", "Farm total", f"{f['guards']} guards", "",
			f.get("covered_ha"), f.get("coverage_pct"), "",
			f.get("distance_km"), f.get("patrol_hours"), f.get("patrols"),
			f.get("valid_scans"), f.get("scans"), "", "", "", "",
		])
	return out


def _filename(data, scope):
	slug = re.sub(r"[^A-Za-z0-9]+", "-", scope).strip("-") or "all"
	return f"guard-ranking-{slug}-{data['from_date']}-to-{data['to_date']}"


def render_html(data, scope, note=None):
	"""The report as HTML: the email body and, through get_pdf, the PDF.
	Inline styles only - mail clients drop <style> blocks."""
	esc = frappe.utils.escape_html
	period = data["from_date"] if data["from_date"] == data["to_date"] else f"{data['from_date']} to {data['to_date']}"
	th = "padding:6px 8px;border-bottom:1px solid #d6d6d2;font-size:11px;color:#6b6b66;text-align:{a};font-weight:600"
	td = "padding:6px 8px;border-bottom:1px solid #ececea;font-size:12px;text-align:{a}"
	heads = [("#", "left"), ("Guard", "left"), ("Score", "right"), ("Area patrolled", "right"),
		("Distance", "right"), ("Patrol time", "right"), ("Patrols", "right"), ("Valid scans", "right"),
		("Incidents on shift", "right")]
	parts = [
		"<div style='font-family:Arial,Helvetica,sans-serif;color:#1f1f1c'>",
		f"<h2 style='margin:0 0 4px;font-size:18px'>Guard ranking · {esc(scope)}</h2>",
		f"<div style='color:#6b6b66;font-size:12px;margin-bottom:12px'>{esc(period)}</div>",
	]
	if note:
		parts.append(f"<p style='font-size:13px;margin:0 0 14px'>{esc(note)}</p>")
	by_farm = {}
	for r in data.get("rows") or []:
		by_farm.setdefault(r["farm"], []).append(r)
	if not data.get("farms"):
		parts.append("<p style='font-size:13px'>No patrols in this period.</p>")
	for f in data.get("farms") or []:
		rows = by_farm.get(f["farm"], [])
		if f.get("covered_ha") is not None:
			gap = max(0.0, (f.get("area_ha") or 0) - f["covered_ha"])
			area = (f"{_fmt_ha(f['covered_ha'])} of {_fmt_ha(f['area_ha'])} patrolled ({f['coverage_pct']}%)"
				f" · <span style='color:#a32d2d'>{_fmt_ha(gap)} not patrolled</span>")
		else:
			area = "no boundary, area not measured"
		parts.append(
			f"<h3 style='margin:18px 0 4px;font-size:14px'>{esc(f['farm'])}</h3>"
			f"<div style='font-size:12px;color:#6b6b66;margin-bottom:6px'>{f['guards']} "
			f"{'guard' if f['guards'] == 1 else 'guards'} · {area} · {f.get('distance_km', 0):.2f} km walked · "
			f"{_fmt_hours(f.get('patrol_hours'))} on patrol</div>"
			"<table cellspacing='0' cellpadding='0' style='border-collapse:collapse;width:100%'><tr>"
			+ "".join(f"<th style='{th.format(a=a)}'>{h}</th>" for h, a in heads)
			+ "</tr>"
		)
		for r in rows:
			cov = (f"{_fmt_ha(r['area_ha'])} <span style='color:#8a8a84'>({r['coverage_pct']:.1f}%)</span>"
				if r.get("area_ha") is not None else "—")
			scans = r.get("valid_scans") or 0
			if data.get("checkpoints") and r.get("scans") and r["scans"] != scans:
				scans = f"{scans} / {r['scans']}"
			inc = r.get("incidents_scored") or 0
			inc_txt = f"{inc}" + (f" ({r['incidents_serious']} serious)" if r.get("incidents_serious") else "")
			cells = [
				(r["rank"], "left"), (esc(r.get("name") or r["guard"]), "left"), (f"<b>{r['score']:.1f}</b>", "right"),
				(cov, "right"), (f"{r['distance_km']:.2f} km", "right"), (_fmt_hours(r["patrol_hours"]), "right"),
				(r["patrols"], "right"), (scans, "right"),
				(f"<span style='color:{'#a32d2d' if inc else '#1f1f1c'}'>{inc_txt}</span>", "right"),
			]
			parts.append("<tr>" + "".join(f"<td style='{td.format(a=a)}'>{v}</td>" for v, a in cells) + "</tr>")
		if len(rows) > 1:
			tot = [
				("", "left"), ("<b>Farm total</b>", "left"), ("", "right"),
				(f"<b>{_fmt_ha(f.get('covered_ha'))}</b>" if f.get("covered_ha") is not None else "—", "right"),
				(f"<b>{f.get('distance_km', 0):.2f} km</b>", "right"), (f"<b>{_fmt_hours(f.get('patrol_hours'))}</b>", "right"),
				(f"<b>{f.get('patrols', 0)}</b>", "right"), (f"<b>{f.get('valid_scans', 0)}</b>", "right"), ("", "right"),
			]
			parts.append("<tr style='background:#f6f6f3'>" + "".join(
				f"<td style='{td.format(a=a)}'>{v}</td>" for v, a in tot) + "</tr>")
		parts.append("</table>")
	w = data.get("weights") or {}
	pc = lambda x: f"{round((x or 0) * 100)}%"
	parts.append(
		"<p style='font-size:11px;color:#8a8a84;margin-top:18px;line-height:1.5'>"
		f"Score (0–100) = {pc(w.get('coverage'))} coverage + {pc(w.get('distance'))} distance + "
		f"{pc(w.get('scans'))} valid checkpoint scans + {pc(w.get('safety'))} safety, each against the best guard "
		"on the same farm. Area patrolled counts the farm's "
		f"{data.get('cell_width_m')} × {data.get('cell_height_m')} m squares any guard's GPS track entered, "
		"each once. "
		f"<a href='{frappe.utils.get_url('/security-dashboard#patrols')}'>Open the Security Dashboard</a></p></div>"
	)
	return "".join(parts)


def _pdf(html):
	from frappe.utils.pdf import get_pdf

	page = ("<!doctype html><html><head><meta charset='utf-8'></head><body style='margin:0'>"
		+ html + "</body></html>")
	return get_pdf(page, {"orientation": "Landscape", "page-size": "A4"})


@frappe.whitelist()
def export_ranking(fmt="xlsx", period=None, from_date=None, to_date=None, farm=None, company=None):
	"""Download the ranking the dashboard is showing as Excel, CSV or PDF."""
	data = _ranking(period, from_date, to_date, farm, company)
	scope = _scope_label(farm, company)
	name = _filename(data, scope)
	from frappe.desk.utils import provide_binary_file

	if fmt == "pdf":
		provide_binary_file(name, "pdf", _pdf(render_html(data, scope)))
	elif fmt == "csv":
		buf = io.StringIO()
		csv.writer(buf).writerows(_table_rows(data))
		provide_binary_file(name, "csv", buf.getvalue().encode("utf-8-sig"))
	else:
		from frappe.utils.xlsxutils import make_xlsx

		provide_binary_file(name, "xlsx", make_xlsx(_table_rows(data), "Guard ranking").getvalue())


def _clean_emails(recipients):
	if isinstance(recipients, str):
		try:
			parsed = frappe.parse_json(recipients)
			recipients = parsed if isinstance(parsed, list) else recipients
		except Exception:
			pass
	if isinstance(recipients, str):
		recipients = re.split(r"[,;\s]+", recipients)
	out, seen = [], set()
	for e in recipients or []:
		e = (e or "").strip()
		if e and e.lower() not in seen:
			if not EMAIL_RE.match(e):
				frappe.throw(_("{0} is not a valid email address.").format(frappe.bold(e)))
			seen.add(e.lower())
			out.append(e)
	return out


def _deliver(recipients, data, scope, note=None):
	html = render_html(data, scope, note)
	period = data["from_date"] if data["from_date"] == data["to_date"] else f"{data['from_date']} to {data['to_date']}"
	frappe.sendmail(
		recipients=recipients,
		subject=f"Guard ranking · {scope} · {period}",
		message=html,
		attachments=[{"fname": _filename(data, scope) + ".pdf", "fcontent": _pdf(html)}],
		now=False,
	)


@frappe.whitelist(methods=["POST"])
def send_ranking_report(recipients, period=None, from_date=None, to_date=None, farm=None, company=None, note=None):
	"""The dashboard's Send report button: email the ranking on screen,
	with the PDF attached, to the addresses given. Built in the background
	(working out a month's ranking and the PDF can take a while)."""
	if not set(SEND_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only a Security Head or Security Manager can send the report."), frappe.PermissionError)
	emails = _clean_emails(recipients)
	if not emails:
		frappe.throw(_("Add at least one email address."))
	if len(emails) > 50:
		frappe.throw(_("Send to 50 people at most at a time."))
	note = (note or "").strip()[:1000] or None
	# Fail fast on a bad period or no permission, before queueing.
	if not frappe.has_permission("Patrol GPS Log", ptype="read"):
		frappe.throw(_("You do not have permission to view Patrol GPS Logs."), frappe.PermissionError)
	frappe.enqueue(
		"upande_security.api.ranking_report._send_now",
		queue="long",
		timeout=1200,
		recipients=emails,
		period=period,
		from_date=from_date,
		to_date=to_date,
		farm=farm,
		company=company,
		note=note,
	)
	return {"queued": True, "recipients": emails}


def _send_now(recipients, period=None, from_date=None, to_date=None, farm=None, company=None, note=None):
	"""Background half of send_ranking_report - runs as the user who sent
	it, so the report holds only the farms they can see."""
	try:
		data = _ranking(period, from_date, to_date, farm, company)
		sender = frappe.utils.get_fullname(frappe.session.user)
		note = (f"{note}\n\n— {sender}" if note else f"Sent by {sender} from the Security Dashboard.")
		_deliver(recipients, data, _scope_label(farm, company), note)
	except Exception:
		frappe.log_error("Guard ranking report send failed")
		raise


@frappe.whitelist()
def report_recipient_options():
	"""Suggestions for the Send report dialog: the subscription list's
	addresses and everyone with a security role."""
	if not set(SEND_ROLES) & set(frappe.get_roles()):
		return []
	people = {}
	for row in frappe.get_all(
		"Guard Ranking Report Subscription", fields=["user", "email"], filters={"parenttype": "Security Ops Settings"}
	):
		if row.email:
			people[row.email.lower()] = {"email": row.email, "name": frappe.utils.get_fullname(row.user) if row.user else row.email}
	users = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": ["in", ["Security Head", "Security Manager", "Security Supervisor"]]},
		pluck="parent",
		distinct=True,
	)
	for u in frappe.get_all("User", filters={"name": ["in", users or ["__none__"]], "enabled": 1}, fields=["name", "full_name", "email"]):
		if u.email and u.email.lower() not in people:
			people[u.email.lower()] = {"email": u.email, "name": u.full_name or u.email}
	return sorted(people.values(), key=lambda p: (p["name"] or "").lower())


def _due_period(row, today):
	"""(period, from_date, to_date) when this subscription is due today,
	else None. Daily: yesterday; Weekly: last week, on the chosen weekday;
	Monthly: last month, on the 1st."""
	if row.frequency == "Daily":
		y = frappe.utils.add_days(today, -1)
		return "custom", y, y
	if row.frequency == "Weekly":
		if WEEKDAYS[today.weekday()] != (row.send_on or "Monday"):
			return None
		monday = frappe.utils.add_days(today, -today.weekday())
		return "custom", frappe.utils.add_days(monday, -7), frappe.utils.add_days(monday, -1)
	if row.frequency == "Monthly":
		if today.day != 1:
			return None
		last = frappe.utils.add_days(today, -1)
		return "custom", last.replace(day=1), last
	return None


def send_scheduled_reports():
	"""Daily, 07:00 (hooks cron): email each due subscription. Rows asking
	for the same report (period and scope) share one email and one ranking.
	last_sent_on keeps a re-run on the same day from sending twice."""
	settings = frappe.get_single("Security Ops Settings")
	rows = [r for r in (settings.get("ranking_report_subscriptions") or []) if r.enabled and r.email]
	if not rows:
		return
	today = frappe.utils.getdate()
	groups = {}
	for r in rows:
		if r.last_sent_on and frappe.utils.getdate(r.last_sent_on) == today:
			continue
		due = _due_period(r, today)
		if not due:
			continue
		key = (due, r.farm or "", "" if r.farm else (r.company or ""))
		groups.setdefault(key, []).append(r)
	for (due, farm, company), members in groups.items():
		period, first, last = due
		try:
			data = _ranking(period, str(first), str(last), farm or None, company or None)
			emails = _clean_emails([m.email for m in members])
			freq = members[0].frequency.lower()
			_deliver(emails, data, _scope_label(farm, company),
				f"Your {freq} guard ranking report from the Security Dashboard.")
			for m in members:
				frappe.db.set_value("Guard Ranking Report Subscription", m.name, "last_sent_on", today,
					update_modified=False)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(f"Guard ranking report for {_scope_label(farm, company)} failed")
