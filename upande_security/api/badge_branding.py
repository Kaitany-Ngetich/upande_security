# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Company details printed on gate badges (Gate Badge Card print format).

Everything comes from the site the badge is printed on: the name, logo,
website and address from the Company record and its Address, and the
emergency number from Security Ops Settings > Badge Emergency Contacts.
Nothing is assumed about which company the site belongs to, so a company
with no emergency number set prints a badge without one rather than
another company's number.
"""

import frappe


def get_badge_branding(company: str | None, farm: str | None = None) -> dict:
	"""Name, logo, emergency contact and address line for one badge.
	Soft-fails to the bare company name - a badge is never worth breaking a
	print over."""
	branding = frappe._dict(
		company_name=company or "",
		logo=None,
		emergency_label="Emergency Contact",
		emergency_phone=None,
		address_line="",
	)
	if not company:
		return branding

	try:
		info = frappe.db.get_value(
			"Company", company, ["company_name", "company_logo", "website"], as_dict=True
		) or frappe._dict()
		branding.company_name = info.company_name or company
		branding.logo = info.company_logo

		contact = _emergency_contact(company, farm)
		if contact:
			branding.emergency_phone = contact.contact_phone
			branding.emergency_label = contact.contact_label or branding.emergency_label

		branding.address_line = _address_line(company, farm, branding.company_name, info.website)
	except Exception:
		frappe.log_error(title="Gate badge branding lookup failed")
	return branding


def _emergency_contact(company: str, farm: str | None):
	"""The farm's own row if there is one, else the company-wide row."""
	rows = [
		r
		for r in frappe.get_cached_doc("Security Ops Settings").get("badge_emergency_contacts") or []
		if r.company == company and r.contact_phone
	]
	if farm:
		for r in rows:
			if r.farm == farm:
				return r
	for r in rows:
		if not r.farm:
			return r
	return None


def _address_line(company: str, farm: str | None, company_name: str, website: str | None) -> str:
	addresses = frappe.get_all(
		"Address",
		filters=[
			["Dynamic Link", "link_doctype", "=", "Company"],
			["Dynamic Link", "link_name", "=", company],
			["Address", "disabled", "=", 0],
		],
		fields=["address_line1", "address_line2", "city", "pincode", "country", "phone"],
		order_by="is_primary_address desc, is_your_company_address desc, modified desc",
		limit=1,
	)
	parts = [company_name + (f" — {farm}" if farm else "")]
	if addresses:
		a = addresses[0]
		street = ", ".join(
			p for p in [a.address_line1, a.address_line2, " ".join(filter(None, [a.pincode, a.city])), a.country] if p
		)
		if street:
			parts.append(street)
		if a.phone:
			parts.append(f"Tel: {a.phone}")
	if website:
		parts.append(website.replace("https://", "").replace("http://", "").rstrip("/"))
	return " · ".join(parts)
