# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""The security report: the period's patrols (the dashboard's guard
ranking), incidents and watch list, emailed with a PDF attached - on demand
from the Security Dashboard, or on a schedule to the people in Security Ops
Settings' Security Reports table. The guard ranking on its own can also be
downloaded as Excel, CSV or PDF.

Nothing here is tied to one site: farms, companies and people come from the
site's own records, the incident types left out come from Security Ops
Settings (SOS by default), and links point at the site's own URL.

Patrol figures come from patrol_ranking.get_guard_ranking, so the report
says what the dashboard says. Run from the dashboard, everything is limited
to what the sender may see; the scheduled job runs as Administrator and is
narrowed by each subscription's company / farm instead.

The watch list is covert (see watchlist.py): it goes only to recipients
whose login holds Security Head or System Manager - the roles that can open
it in Desk. Everyone else on the same send gets the report without it, and
an address with no login never gets it.
"""

import csv
import io
import re

import frappe
from frappe import _

from upande_security.api.patrol_ranking import get_guard_ranking, resolve_period
from upande_security.api.security_dashboard import _farms_of_company, hidden_incident_types

# Who may email the report from the dashboard. Downloading the ranking only
# needs what viewing it needs.
SEND_ROLES = ("System Manager", "Security Head", "Security Manager")
WATCHLIST_ROLES = ("System Manager", "Security Head")
SECTIONS = ("patrols", "incidents", "watchlist")
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
OPEN_STATUSES = ("Open", "In Progress")
SEVERITY_ORDER = ("Critical", "High", "Medium", "Low")
# The most incidents / watch list transactions listed in one email; the
# summary counts always cover all of them.
LIST_LIMIT = 300

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



# --- data ----------------------------------------------------------------------

def _ranking(period=None, from_date=None, to_date=None, farm=None, company=None):
	return get_guard_ranking(
		period=period or "this_week", from_date=from_date, to_date=to_date, farm=farm, company=company
	)


def _scope_label(farm=None, company=None):
	return farm or company or "All farms"


def _scope_farms(farm=None, company=None):
	"""Farm names the report covers, or None for every farm."""
	if farm:
		return [farm]
	if company:
		return _farms_of_company(company)
	return None


def _user_of(email):
	"""The enabled login behind an address, if any."""
	return frappe.db.get_value("User", {"email": email, "enabled": 1}, "name") or (
		frappe.db.get_value("User", {"name": email, "enabled": 1}, "name"))


def allowed_farms(user):
	"""The farms this login may see, from its User Permissions - their Farm
	rows if any (as Desk applies them), else every farm of their Company
	rows - or None when they are not limited at all."""
	perms = frappe.get_all("User Permission", filters={"user": user, "allow": ["in", ["Company", "Farm"]]},
		fields=["allow", "for_value"])
	farms = {p.for_value for p in perms if p.allow == "Farm"}
	companies = [p.for_value for p in perms if p.allow == "Company"]
	if farms:
		if companies:
			farms &= set(frappe.get_all("Farm", filters={"company": ["in", companies]}, pluck="name"))
		return farms
	if companies:
		return set(frappe.get_all("Farm", filters={"company": ["in", companies]}, pluck="name"))
	return None


def covers(user, farm=None, company=None):
	"""True when a report on farm / company (both blank: every farm) holds
	nothing this login is not allowed to see. An address with no login is
	not limited by anything - who gets what is then the sender's call."""
	if not user:
		return True
	allowed = allowed_farms(user)
	if allowed is None:
		return True
	wanted = _scope_farms(farm, company)
	if wanted is None:
		return False
	return set(wanted) <= allowed and bool(allowed)


def default_scope(user):
	"""(farm, company) to fill in for a limited login whose row left both
	blank: their one farm, else their one company. (None, None) when they
	are not limited, or limited to more than one company."""
	allowed = allowed_farms(user)
	if not allowed:
		return None, None
	if len(allowed) == 1:
		return next(iter(allowed)), None
	companies = {frappe.db.get_value("Farm", f, "company") for f in allowed}
	if len(companies) == 1:
		company = companies.pop()
		if set(_farms_of_company(company)) == allowed:
			return None, company
	return None, None


def _incidents(first, last, farm=None, company=None):
	"""The period's incidents, minus the types left out, as the person
	running the report may see them (get_list)."""
	filters = [["incident_datetime", "between", [f"{first} 00:00:00", f"{last} 23:59:59"]]]
	farms = _scope_farms(farm, company)
	if farms is not None:
		filters.append(["farm", "in", farms])
	hidden = hidden_incident_types()
	if hidden:
		filters.append(["nature_of_incident", "not in", hidden])
	rows = frappe.get_list(
		"Incident Report",
		filters=filters,
		fields=["name", "incident_datetime", "farm", "location", "nature_of_incident", "severity",
			"status", "reporter_name", "assigned_to", "description"],
		order_by="incident_datetime desc",
		limit_page_length=0,
	)

	def count(key):
		out = {}
		for r in rows:
			k = r.get(key) or "Not set"
			out[k] = out.get(k, 0) + 1
		return out

	return {
		"rows": rows,
		"total": len(rows),
		"open": sum(1 for r in rows if r.status in OPEN_STATUSES),
		"serious": sum(1 for r in rows if r.severity in ("High", "Critical")),
		"by_type": sorted(count("nature_of_incident").items(), key=lambda x: -x[1]),
		"by_severity": sorted(count("severity").items(),
			key=lambda x: SEVERITY_ORDER.index(x[0]) if x[0] in SEVERITY_ORDER else 9),
		"by_status": count("status"),
		"by_farm": sorted(count("farm").items(), key=lambda x: -x[1]),
		"hidden": list(hidden),
	}


def _watchlist(first, last, farm=None, company=None):
	"""Active watches, the period's transactions by watched people, and the
	watches opened or closed in the period. A watch restricted to a company
	only appears in reports for that company (or all farms)."""
	start, end = f"{first} 00:00:00", f"{last} 23:59:59"
	report_company = company or (frappe.db.get_value("Farm", farm, "company") if farm else None)
	fields = ["name", "full_name", "person_type", "status", "incident", "restrict_to_company", "reason",
		"added_on", "closed_on", "activity_count", "last_activity_on"]
	entries = frappe.get_all(
		"Security Watchlist",
		filters=[["status", "=", "Active"]],
		or_filters=None,
		fields=fields,
		order_by="added_on desc",
		limit_page_length=0,
	)
	closed = frappe.get_all(
		"Security Watchlist",
		filters=[["status", "=", "Inactive"], ["closed_on", "between", [start, end]]],
		fields=fields,
		order_by="closed_on desc",
		limit_page_length=0,
	)

	def in_scope(e):
		return not report_company or not e.restrict_to_company or e.restrict_to_company == report_company

	entries = [e for e in entries if in_scope(e)]
	closed = [e for e in closed if in_scope(e)]
	act_filters = [["occurred_at", "between", [start, end]]]
	farms = _scope_farms(farm, company)
	if farms is not None:
		act_filters.append(["farm", "in", farms])
	activity = frappe.get_all(
		"Watchlist Activity",
		filters=act_filters,
		fields=["watchlist", "person", "activity_type", "occurred_at", "matched_on", "farm", "gate",
			"reference_doctype", "reference_name"],
		order_by="occurred_at desc",
		limit_page_length=0,
	)
	keep = {e.name for e in entries} | {e.name for e in closed}
	activity = [a for a in activity if a.watchlist in keep]
	per_entry = {}
	for a in activity:
		per_entry[a.watchlist] = per_entry.get(a.watchlist, 0) + 1
	for e in entries + closed:
		e.period_activity = per_entry.get(e.name, 0)
	return {
		"active": entries,
		"closed": closed,
		"opened": sum(1 for e in entries + closed if e.added_on and start <= str(e.added_on) <= end),
		"activity": activity,
	}


def _may_see_watchlist(email):
	"""True when this address belongs to an enabled login holding Security
	Head or System Manager."""
	user = frappe.db.get_value("User", {"email": email, "enabled": 1}, "name") or (
		frappe.db.get_value("User", {"name": email, "enabled": 1}, "name"))
	if not user:
		return False
	return bool(set(WATCHLIST_ROLES) & set(frappe.get_roles(user)))


def build_report(first, last, farm=None, company=None, sections=SECTIONS):
	"""Everything the report shows, worked out once and shared by every
	recipient of one send."""
	sections = [s for s in SECTIONS if s in (sections or SECTIONS)]
	report = {"from_date": str(first), "to_date": str(last), "scope": _scope_label(farm, company),
		"sections": sections, "brand": _brand(farm, company)}
	if "patrols" in sections:
		report["ranking"] = _ranking("custom", str(first), str(last), farm, company)
	if "incidents" in sections:
		report["incidents"] = _incidents(first, last, farm, company)
	if "watchlist" in sections:
		report["watchlist"] = _watchlist(first, last, farm, company)
	return report


# --- rendering -----------------------------------------------------------------

def _fmt_hours(h):
	m = int(round((h or 0) * 60))
	return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def _fmt_ha(x):
	if x is None:
		return "—"
	return f"{x:.0f} ha" if x >= 100 else (f"{x:.1f} ha" if x >= 10 else f"{x:.2f} ha")


def _period_text(first, last):
	return str(first) if str(first) == str(last) else f"{first} to {last}"


def _dt(v):
	return frappe.utils.format_datetime(v, "dd MMM yyyy HH:mm") if v else ""


def _brand(farm=None, company=None):
	"""Whose report this is, for its heading: the company of the report's
	scope. A report on every farm spans companies, so it says so."""
	if company:
		return company
	if farm:
		c = frappe.db.get_value("Farm", farm, "company")
		if c:
			return c
	return _("All companies")


def render_html(report, note=None, with_watchlist=False):
	"""The report through templates/security_report.html - the email body
	and, through get_pdf, the PDF."""
	r = frappe._dict(report)
	r.period_text = _period_text(r.from_date, r.to_date)
	if r.get("ranking"):
		by_farm = {}
		for g in r.ranking.get("rows") or []:
			by_farm.setdefault(g["farm"], []).append(frappe._dict(g))
		r.guards_by_farm = by_farm
		r.ranking = frappe._dict(r.ranking, farms=[frappe._dict(f) for f in r.ranking.get("farms") or []])
		measured = [f for f in r.ranking.farms if f.get("covered_ha") is not None]
		r.area_total = frappe._dict(
			covered=sum(f.covered_ha for f in measured), area=sum(f.area_ha or 0 for f in measured)
		) if measured else None
	if r.get("incidents"):
		for i in r.incidents["rows"]:
			text = " ".join(frappe.utils.strip_html(i.description or "").split())
			i.summary = text if len(text) <= 240 else text[:237].rsplit(" ", 1)[0] + "…"
		r.incidents = frappe._dict(r.incidents)
	if r.get("watchlist"):
		r.watchlist = frappe._dict(r.watchlist)
	return frappe.render_template(
		"upande_security/templates/security_report.html",
		{
			"r": r,
			"with_watchlist": with_watchlist,
			"note": note,
			"brand": r.get("brand") or _brand(),
			"generated": frappe.utils.format_datetime(frappe.utils.now_datetime(), "dd MMM yyyy HH:mm"),
			"dashboard_url": frappe.utils.get_url("/security-dashboard"),
			"list_limit": LIST_LIMIT,
			"ha": _fmt_ha,
			"hours": _fmt_hours,
			"dt": _dt,
			"pct": lambda x: f"{round((x or 0) * 100)}%",
			"form_url": frappe.utils.get_url_to_form,
		},
	)


def _pdf(html):
	from frappe.utils.pdf import get_pdf

	page = "<!doctype html><html><head><meta charset='utf-8'></head><body style='margin:0'>" + html + "</body></html>"
	return get_pdf(page, {"orientation": "Landscape", "page-size": "A4"})


def _filename(prefix, first, last, scope):
	slug = re.sub(r"[^A-Za-z0-9]+", "-", scope).strip("-") or "all"
	return f"{prefix}-{slug}-{first}-to-{last}"


# --- downloads -----------------------------------------------------------------

def _table_rows(data):
	"""The ranking as rows for Excel and CSV: header, one row per guard,
	then each farm's total row."""
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


@frappe.whitelist()
def export_ranking(fmt="xlsx", period=None, from_date=None, to_date=None, farm=None, company=None):
	"""Download what the dashboard shows: the guard ranking as Excel, CSV or
	PDF, or ("report") the whole security report as a PDF - its watch list
	included only for a Security Head or System Manager."""
	from frappe.desk.utils import provide_binary_file

	scope = _scope_label(farm, company)
	if fmt == "report":
		first, last = resolve_period(period, from_date, to_date)
		report = build_report(first, last, farm, company)
		html = render_html(report, with_watchlist=bool(set(WATCHLIST_ROLES) & set(frappe.get_roles())))
		provide_binary_file(_filename("security-report", first, last, scope), "pdf", _pdf(html))
		return
	data = _ranking(period, from_date, to_date, farm, company)
	name = _filename("guard-ranking", data["from_date"], data["to_date"], scope)
	if fmt == "pdf":
		report = {"from_date": data["from_date"], "to_date": data["to_date"], "scope": scope,
			"sections": ["patrols"], "ranking": data, "brand": _brand(farm, company)}
		provide_binary_file(name, "pdf", _pdf(render_html(report)))
	elif fmt == "csv":
		buf = io.StringIO()
		csv.writer(buf).writerows(_table_rows(data))
		provide_binary_file(name, "csv", buf.getvalue().encode("utf-8-sig"))
	else:
		from frappe.utils.xlsxutils import make_xlsx

		provide_binary_file(name, "xlsx", make_xlsx(_table_rows(data), "Guard ranking").getvalue())


# --- sending -------------------------------------------------------------------

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


def _clean_sections(sections):
	if isinstance(sections, str):
		try:
			sections = frappe.parse_json(sections)
		except Exception:
			sections = sections.split(",")
	out = [s for s in SECTIONS if s in (sections or [])]
	return out or list(SECTIONS)


def deliver(recipients, report, note=None):
	"""Email the report. Recipients who may see the watch list get it;
	the rest get the same report without it, in a separate email so it
	never reaches them even as a Cc."""
	with_wl = "watchlist" in report["sections"]
	groups = {True: [], False: []}
	for e in recipients:
		groups[with_wl and _may_see_watchlist(e)].append(e)
	subject = f"Security report · {report['scope']} · {_period_text(report['from_date'], report['to_date'])}"
	fname = _filename("security-report", report["from_date"], report["to_date"], report["scope"]) + ".pdf"
	for show_wl, people in groups.items():
		if not people:
			continue
		html = render_html(report, note, with_watchlist=show_wl)
		frappe.sendmail(
			recipients=people,
			subject=subject,
			message=html,
			attachments=[{"fname": fname, "fcontent": _pdf(html)}],
			now=False,
		)


@frappe.whitelist(methods=["POST"])
def send_report(recipients, period=None, from_date=None, to_date=None, farm=None, company=None,
		sections=None, note=None):
	"""The dashboard's Send report button: email the security report for the
	period and scope on screen. Built in the background (a month of patrols
	and the PDF can take a while)."""
	if not set(SEND_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only a Security Head or Security Manager can send the report."), frappe.PermissionError)
	emails = _clean_emails(recipients)
	if not emails:
		frappe.throw(_("Add at least one email address."))
	if len(emails) > 50:
		frappe.throw(_("Send to 50 people at most at a time."))
	outside = [e for e in emails if not covers(_user_of(e), farm, company)]
	if outside:
		frappe.throw(_("{0} cannot see everything in a report on {1}. Pick a narrower company or farm, or leave them out.").format(
			", ".join(outside), frappe.bold(_scope_label(farm, company))))
	sections = _clean_sections(sections)
	# Only someone who can read the watch list can send it.
	if "watchlist" in sections and not frappe.has_permission("Security Watchlist", ptype="read"):
		sections = [s for s in sections if s != "watchlist"]
	if "patrols" in sections and not frappe.has_permission("Patrol GPS Log", ptype="read"):
		frappe.throw(_("You do not have permission to view Patrol GPS Logs."), frappe.PermissionError)
	first, last = resolve_period(period, from_date, to_date)
	if frappe.utils.date_diff(last, first) > 92:
		frappe.throw(_("Pick a period of three months or less."))
	frappe.enqueue(
		"upande_security.api.security_report._send_now",
		queue="long",
		timeout=1500,
		recipients=emails,
		first=str(first),
		last=str(last),
		farm=farm or None,
		company=company or None,
		sections=sections,
		note=(note or "").strip()[:1000] or None,
	)
	return {"queued": True, "recipients": emails, "sections": sections}


def _send_now(recipients, first, last, farm=None, company=None, sections=SECTIONS, note=None):
	"""Background half of send_report - runs as the sender, so it holds
	only what they can see."""
	try:
		report = build_report(first, last, farm, company, sections)
		sender = frappe.utils.get_fullname(frappe.session.user)
		note = f"{note}\n\n— {sender}" if note else f"Sent by {sender} from the Security Dashboard."
		deliver(recipients, report, note)
	except Exception:
		frappe.log_error("Security report send failed")
		raise


@frappe.whitelist()
def report_recipient_options():
	"""For the Send report dialog: suggested people (the subscription list
	and everyone with a security role, marking who would get the watch
	list) and the incident types the report leaves out."""
	if not set(SEND_ROLES) & set(frappe.get_roles()):
		return {"people": [], "hidden_incident_types": []}
	people = {}
	for row in frappe.get_all(
		"Security Report Subscription", fields=["user", "email"], filters={"parenttype": "Security Ops Settings"}
	):
		if row.email:
			people[row.email.lower()] = {"email": row.email,
				"name": frappe.utils.get_fullname(row.user) if row.user else row.email}
	users = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": ["in", ["Security Head", "Security Manager", "Security Supervisor"]]},
		pluck="parent",
		distinct=True,
	)
	for u in frappe.get_all("User", filters={"name": ["in", users or ["__none__"]], "enabled": 1},
			fields=["name", "full_name", "email"]):
		if u.email and u.email.lower() not in people:
			people[u.email.lower()] = {"email": u.email, "name": u.full_name or u.email}
	for p in people.values():
		p["watchlist"] = _may_see_watchlist(p["email"])
	return {
		"people": sorted(people.values(), key=lambda p: (p["name"] or "").lower()),
		"hidden_incident_types": list(hidden_incident_types()),
	}


# --- schedule --------------------------------------------------------------------

def _due_period(row, today):
	"""(first, last) when this subscription is due today, else None.
	Daily: yesterday; Weekly: last week, on the chosen weekday; Monthly:
	last month, on the 1st."""
	if row.frequency == "Daily":
		y = frappe.utils.add_days(today, -1)
		return y, y
	if row.frequency == "Weekly":
		if WEEKDAYS[today.weekday()] != (row.send_on or "Monday"):
			return None
		monday = frappe.utils.add_days(today, -today.weekday())
		return frappe.utils.add_days(monday, -7), frappe.utils.add_days(monday, -1)
	if row.frequency == "Monthly":
		if today.day != 1:
			return None
		last = frappe.utils.add_days(today, -1)
		return last.replace(day=1), last
	return None


def _row_sections(row):
	return tuple(s for s, f in (("patrols", "include_patrols"), ("incidents", "include_incidents"),
		("watchlist", "include_watchlist")) if row.get(f))


def send_scheduled_reports():
	"""Daily, 07:00 (hooks cron): email each due subscription. Rows asking
	for the same report (period, scope and sections) share one build and one
	email per audience; last_sent_on keeps a re-run on the same day from
	sending twice."""
	settings = frappe.get_single("Security Ops Settings")
	rows = [r for r in (settings.get("security_report_subscriptions") or []) if r.enabled and r.email]
	if not rows:
		return
	today = frappe.utils.getdate()
	groups = {}
	for r in rows:
		if r.last_sent_on and frappe.utils.getdate(r.last_sent_on) == today:
			continue
		# Access may have changed since the row was saved.
		if not covers(r.user or _user_of(r.email), r.farm, r.company):
			frappe.log_error(f"Security report not sent to {r.email}",
				f"{r.email} can no longer see everything in a report on {_scope_label(r.farm, r.company)}. "
				"Fix the row in Security Ops Settings > Security Reports.")
			continue
		due = _due_period(r, today)
		sections = _row_sections(r)
		if not due or not sections:
			continue
		key = (due, r.farm or "", "" if r.farm else (r.company or ""), sections)
		groups.setdefault(key, []).append(r)
	for (due, farm, company, sections), members in groups.items():
		first, last = due
		try:
			report = build_report(first, last, farm or None, company or None, sections)
			freq = {m.frequency.lower() for m in members}
			deliver(_clean_emails([m.email for m in members]), report,
				f"Your {' / '.join(sorted(freq))} security report.")
			for m in members:
				frappe.db.set_value("Security Report Subscription", m.name, "last_sent_on", today,
					update_modified=False)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(f"Security report for {_scope_label(farm, company)} failed")
