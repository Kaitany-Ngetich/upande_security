# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Who to call in an emergency at a farm - one answer for the guard app's
emergency call, the lone-guard escalation SMS and the number printed on
visitor badges.

The Security Emergency Contact list holds the numbers (linked from Security
Ops Settings > Emergency Contacts). A contact names a company and any number
of its farms: a contact serving farms close enough to
share one, so farms far apart each get their own. A row with no farms is the
company's default, used wherever no farm contact is set. Nothing is tied to
one site: every company and farm comes from the site's own records.

For a call, narrowest first:
  1. the farm's own Emergency Contact - set on purpose, so it wins;
  2. a Security Head holding a Farm User Permission for the farm;
  3. a Security Head holding a Company User Permission for the company;
  4. the company-wide Emergency Contact.
A badge prints 1 or 4 only - a configured number, never a person's mobile.
"""

import frappe

_HEAD_BY_SCOPE = (
	"SELECT u.full_name, u.mobile_no, u.phone "
	"FROM `tabUser Permission` up "
	"JOIN `tabHas Role` hr ON hr.parent = up.user AND hr.role = 'Security Head' "
	"JOIN `tabUser` u ON u.name = up.user AND u.enabled = 1 "
	"WHERE up.allow = %s AND up.for_value = %s "
	"ORDER BY (u.mobile_no IS NULL OR u.mobile_no = '') LIMIT 1"
)


def _rows():
	"""Enabled contacts with their farms, read once per request."""
	cached = getattr(frappe.local, "_security_emergency_contacts", None)
	if cached is not None:
		return cached
	rows = frappe.get_all(
		"Security Emergency Contact",
		filters={"enabled": 1, "contact_phone": ["is", "set"]},
		fields=["name", "company", "contact_name", "contact_phone", "contact_label"],
		order_by="modified desc",
	)
	farms = {}
	for f in frappe.get_all(
		"Security Emergency Contact Farm",
		filters={"parenttype": "Security Emergency Contact", "parent": ["in", [r.name for r in rows] or ["__none__"]]},
		fields=["parent", "farm"],
	):
		farms.setdefault(f.parent, []).append(f.farm)
	for r in rows:
		r.farm_list = farms.get(r.name, [])
	frappe.local._security_emergency_contacts = rows
	return rows


def configured_contact(company=None, farm=None):
	"""The Emergency Contact row for this farm, else the company's default:
	{name, phone, label, scope ("farm" or "company")}, or None. The farm's
	company is used when company is not given."""
	if farm and not company:
		company = frappe.db.get_value("Farm", farm, "company")
	if not company:
		return None
	rows = [r for r in _rows() if r.company == company]
	if farm:
		for r in rows:
			if farm in r.farm_list:
				return _contact(r, "farm")
	for r in rows:
		if not r.farm_list:
			return _contact(r, "company")
	return None


def _contact(row, scope):
	return frappe._dict(
		name=row.contact_name or "Security Operations",
		phone=row.contact_phone,
		label=row.contact_label or "Emergency Contact",
		scope=scope,
	)


def _head(allow, value):
	rows = frappe.db.sql(_HEAD_BY_SCOPE, (allow, value), as_dict=True)
	if rows and (rows[0].mobile_no or rows[0].phone):
		return frappe._dict(name=rows[0].full_name or "", phone=rows[0].mobile_no or rows[0].phone)
	return None


def emergency_contact(company=None, farm=None):
	"""Who a guard at this farm calls: {name, phone, source} or None. source
	is farm_contact, farm_head, company_head or company_contact."""
	if farm and not company:
		company = frappe.db.get_value("Farm", farm, "company")
	configured = configured_contact(company, farm)
	if configured and configured.scope == "farm":
		return frappe._dict(name=configured.name, phone=configured.phone, source="farm_contact")
	if farm:
		head = _head("Farm", farm)
		if head:
			return frappe._dict(head, source="farm_head")
	if company:
		head = _head("Company", company)
		if head:
			return frappe._dict(head, source="company_head")
	if configured:
		return frappe._dict(name=configured.name, phone=configured.phone, source="company_contact")
	return None
