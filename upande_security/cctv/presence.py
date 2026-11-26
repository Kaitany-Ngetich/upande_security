# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""People: face enrolment (consent-bound), presence on site, timelines, and
data-subject requests.

LEGAL GATE
Face data is sensitive personal data (Kenya Data Protection Act 2019, s.2
"biometric data"). Nothing here that touches faces runs unless:
  * CCTV Settings > Face Recognition Enabled is on, which itself only counts
    once a Legal Approval Reference is recorded (settings.get_settings), and
  * the person's own consent is "Given" (enrolment), and
  * the site is licensed for presence (when entitlements are enforced).
Withdrawing consent removes the face from every site's store; erase deletes
sightings and anonymises the profile.

WHERE THE FACE DATA LIVES
Images are private File attachments on the profile (permlevel 1). The face
embeddings are computed and stored only on each site's agent (its local
vector store); ERPNext holds a reference, never the embedding.

PRESENCE
"Who is on site" is the latest sighting per person within the presence
window (CCTV Settings > Presence: Forget After), unless their latest
sighting was going out. It is "last seen", never "is there now".
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, getdate, now_datetime, time_diff_in_seconds

from upande_security.cctv.settings import get_settings, is_on, require, site_allows

OPS = {"System Manager", "Security Head", "Security Manager", "CCTV Operator"}
ADMIN = ("System Manager", "Security Head")


def _require_faces():
	if not is_on("face_recognition_enabled"):
		frappe.throw(_("Face recognition is off. It needs the legal approval reference and the switch in CCTV Settings."),
			frappe.PermissionError)


def _profile_sites(doc):
	"""Sites a person is enrolled at: the employee's company's sites, or the visit's site."""
	company = None
	if doc.employee:
		company = frappe.db.get_value("Employee", doc.employee, "company")
	farms = frappe.get_all("Farm", filters={"company": company}, pluck="name") if company else []
	return [f for f in farms if frappe.db.exists("CCTV Site Agent", {"farm": f}) and site_allows(f, "presence")]


# ------------------------------------------------------------------ enrolment

@frappe.whitelist()
def enroll(profile, sites=None):
	"""Send the person's face images to the site agents for enrolment."""
	frappe.only_for(ADMIN)
	_require_faces()
	doc = frappe.get_doc("CCTV Person Profile", profile)
	if doc.consent_status not in ("Given", "Not Required"):
		frappe.throw(_("Record the person's consent first (Consent Status = Given, with the signed form attached)."))
	if doc.consent_status == "Given" and not doc.consent_document:
		frappe.throw(_("Attach the signed consent form."))
	if doc.status != "Active":
		frappe.throw(_("Only an active profile can be enrolled."))
	if not doc.face_images:
		frappe.throw(_("Add 3-5 clear, frontal face images first."))
	sites = frappe.parse_json(sites) if isinstance(sites, str) else (sites or _profile_sites(doc))
	if not sites:
		frappe.throw(_("No site with a CCTV agent (and a presence licence) to enrol at."))
	from upande_security.cctv.commands import queue

	queued = []
	for farm in sites:
		agent = frappe.db.get_value("CCTV Site Agent", {"farm": farm})
		if agent:
			queued.append(queue(agent, "enroll_face", {"person_profile": profile, "name": doc.full_name}, "CCTV Person Profile", profile))
	doc.add_comment("Info", _("Face enrolment requested at {0} by {1}.").format(", ".join(sites), frappe.session.user))
	return {"ok": True, "commands": queued}


def on_enrolled(profile, farm, result):
	doc = frappe.get_doc("CCTV Person Profile", profile)
	sites = {s.strip() for s in (doc.enrolled_sites or "").splitlines() if s.strip()}
	sites.add(farm)
	doc.face_enrolled = 1
	doc.embedding_ref = result.get("embedding_ref") or doc.embedding_ref or profile
	doc.enrolled_sites = "\n".join(sorted(sites))
	for i, q in enumerate(result.get("quality") or []):
		if i < len(doc.face_images):
			doc.face_images[i].quality = round(float(q) * 100, 1) if q is not None else None
			doc.face_images[i].enrolled = 1 if (q or 0) > 0 else 0
	doc.flags.ignore_permissions = True
	doc.save()


def on_deleted(profile, farm):
	doc = frappe.get_doc("CCTV Person Profile", profile)
	sites = {s.strip() for s in (doc.enrolled_sites or "").splitlines() if s.strip()} - {farm}
	doc.enrolled_sites = "\n".join(sorted(sites))
	if not sites:
		doc.face_enrolled = 0
		doc.embedding_ref = None
		for row in doc.face_images:
			row.enrolled = 0
	doc.flags.ignore_permissions = True
	doc.save()


def _remove_everywhere(doc):
	from upande_security.cctv.commands import queue

	out = []
	for farm in [s.strip() for s in (doc.enrolled_sites or "").splitlines() if s.strip()]:
		agent = frappe.db.get_value("CCTV Site Agent", {"farm": farm})
		if agent:
			out.append(queue(agent, "delete_face", {"person_profile": doc.name}, "CCTV Person Profile", doc.name))
	return out


@frappe.whitelist()
def withdraw_consent(profile, note=None):
	"""Consent withdrawn: the face leaves every site's store; the profile stops matching."""
	frappe.only_for(ADMIN)
	doc = frappe.get_doc("CCTV Person Profile", profile)
	cmds = _remove_everywhere(doc)
	doc.consent_status = "Withdrawn"
	doc.status = "Withdrawn"
	doc.flags.ignore_permissions = True
	doc.save()
	doc.add_comment("Info", _("Consent withdrawn ({0}). Face removal requested at every enrolled site.").format(note or "no note"))
	return {"ok": True, "commands": cmds}


@frappe.whitelist()
def export_person_data(profile):
	"""Data-subject access request: everything held about this person, as JSON."""
	frappe.only_for(ADMIN)
	doc = frappe.get_doc("CCTV Person Profile", profile)
	data = {
		"profile": {k: doc.get(k) for k in ("full_name", "person_type", "employee", "status", "consent_status", "consent_date",
			"face_enrolled", "enrolled_sites", "valid_to")},
		"face_images": len(doc.face_images),
		"sightings": frappe.get_all("CCTV Person Sighting", filters={"person_profile": profile},
			fields=["sighting_time", "farm", "zone", "camera", "direction", "source", "confidence"], order_by="sighting_time asc"),
		"alerts": frappe.get_all("CCTV Alert", filters={"person_profile": profile},
			fields=["name", "alert_type", "event_time", "farm", "zone", "status"], order_by="event_time asc"),
	}
	doc.add_comment("Info", _("Personal data exported (access request) by {0}.").format(frappe.session.user))
	return data


@frappe.whitelist()
def erase_person(profile):
	"""Deletion request: remove the face everywhere, delete sightings, anonymise
	the profile. Alerts are kept as incident records but lose the name."""
	frappe.only_for(ADMIN)
	doc = frappe.get_doc("CCTV Person Profile", profile)
	cmds = _remove_everywhere(doc)
	n = 0
	for s in frappe.get_all("CCTV Person Sighting", filters={"person_profile": profile}, pluck="name"):
		frappe.delete_doc("CCTV Person Sighting", s, ignore_permissions=True, force=True, delete_permanently=True)
		n += 1
	frappe.db.sql("update `tabCCTV Alert` set person_name='(erased)' where person_profile=%s", profile)
	for f in frappe.get_all("File", filters={"attached_to_doctype": "CCTV Person Profile", "attached_to_name": profile}, pluck="name"):
		frappe.delete_doc("File", f, ignore_permissions=True, force=True)
	doc.full_name = "(erased)"
	doc.employee = None
	doc.party_doctype = doc.party_name = None
	doc.consent_document = None
	doc.set("face_images", [])
	doc.status = "Withdrawn"
	doc.consent_status = "Withdrawn"
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.save()
	return {"ok": True, "sightings_deleted": n, "commands": cmds}


# ------------------------------------------------------------------ presence

def _require_presence():
	require("presence_enabled")
	if not set(frappe.get_roles()) & OPS:
		frappe.throw(_("Not permitted."), frappe.PermissionError)


@frappe.whitelist()
def get_presence(company=None, farm=None):
	"""People last seen on site (named, and anonymous tracks), by zone."""
	_require_presence()
	s = get_settings()
	since = add_to_date(now_datetime(), hours=-s.presence_stale_hours)
	filters = {"sighting_time": [">=", since]}
	if farm:
		filters["farm"] = farm
	elif company:
		filters["farm"] = ["in", frappe.get_all("Farm", filters={"company": company}, pluck="name") or ["-"]]
	latest = {}
	for r in frappe.get_list("CCTV Person Sighting", filters={**filters, "person_profile": ["is", "set"]},
			fields=["person_profile", "farm", "zone", "camera", "sighting_time", "direction", "confidence"],
			order_by="sighting_time asc", limit_page_length=50000):
		latest[r.person_profile] = r
	now = now_datetime()
	people = []
	for profile, r in latest.items():
		if r.direction == "out":
			continue
		p = frappe.db.get_value("CCTV Person Profile", profile, ["full_name", "person_type", "employee"], as_dict=True) or {}
		people.append({**r, **p, "minutes_ago": int(time_diff_in_seconds(now, r.sighting_time) // 60)})
	tracks = frappe.get_list("CCTV Track", filters={"status": "Active", "kind": "Person", "person_profile": ["is", "not set"],
		"last_seen": [">=", since], **({"farm": filters["farm"]} if "farm" in filters else {})},
		fields=["name", "label", "farm", "last_zone", "last_camera", "last_seen", "sighting_count", "confidence"], limit_page_length=500)
	by_zone = {}
	for p in people:
		by_zone.setdefault(p.get("zone") or "(no zone)", []).append(p)
	return {"people": sorted(people, key=lambda x: x["minutes_ago"]), "by_zone": {k: len(v) for k, v in by_zone.items()},
		"anonymous_tracks": tracks, "window_hours": s.presence_stale_hours}


@frappe.whitelist()
def person_timeline(profile=None, track=None, date=None):
	"""Sightings of one person (or one anonymous track) on one day, in order."""
	_require_presence()
	day = getdate(date) if date else getdate()
	filters = {"sighting_time": ["between", [f"{day} 00:00:00", f"{day} 23:59:59"]]}
	if profile:
		filters["person_profile"] = profile
	elif track:
		filters["track"] = track
	else:
		frappe.throw(_("Choose a person or a track."))
	rows = frappe.get_list("CCTV Person Sighting", filters=filters,
		fields=["name", "sighting_time", "camera", "zone", "farm", "direction", "confidence", "source", "snapshot", "track"],
		order_by="sighting_time asc", limit_page_length=1000)
	names = dict(frappe.get_all("CCTV Camera", filters={"name": ["in", [r.camera for r in rows] or ["-"]]},
		fields=["name", "camera_name"], as_list=True))
	for r in rows:
		r.camera_name = names.get(r.camera)
	return rows
