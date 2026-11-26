# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Company details printed on gate badges (Gate Badge Card print format).

Everything comes from the site the badge is printed on: the name, logo,
website and address from the Company record and its Address, and the
colour and lost-badge charge from Security Ops Settings > Badges per Company,
and the emergency number from Security Ops Settings > Emergency Contacts
(the farm's contact, else the company-wide one). Nothing is assumed about which company the site belongs
to: whatever a company has not set is left off its badge, never filled in
with another company's details.
"""

import frappe


DEFAULT_BADGE_COLOUR = "#1F4D2C"
BADGE_FIELDS = ("badge_colour", "lost_badge_charge")


def get_badge_branding(company: str | None, farm: str | None = None) -> dict:
	"""Name, logo, colour, emergency contact, lost-badge charge and address
	line for one badge (also used by the Staff Vehicle Sticker Card).
	Soft-fails to the bare company name - a badge is never worth breaking a
	print over."""
	branding = frappe._dict(
		company_name=company or "",
		logo=None,
		emergency_label="Emergency Contact",
		emergency_phone=None,
		badge_colour=DEFAULT_BADGE_COLOUR,
		lost_badge_charge=None,
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

		details = _company_badge_details(company, farm)
		# The farm's Emergency Contact, else the company-wide one - the same
		# number a guard there calls (api/emergency_contacts.py).
		from upande_security.api.emergency_contacts import configured_contact

		contact = configured_contact(company, farm)
		if contact:
			branding.emergency_phone = contact.phone
			branding.emergency_label = contact.label or branding.emergency_label
		branding.badge_colour = details.badge_colour or branding.badge_colour
		branding.lost_badge_charge = details.lost_badge_charge

		branding.address_line = _address_line(company, farm, branding.company_name, info.website)
	except Exception:
		frappe.log_error(title="Gate badge branding lookup failed")
	return branding


def _company_badge_details(company: str, farm: str | None) -> frappe._dict:
	"""The company-wide row, with anything the farm's own row sets on top."""
	rows = [
		r
		for r in frappe.get_cached_doc("Security Ops Settings").get("badge_emergency_contacts") or []
		if r.company == company
	]
	company_row = next((r for r in rows if not r.farm), None)
	farm_row = next((r for r in rows if farm and r.farm == farm), None)
	return frappe._dict(
		{f: (farm_row and farm_row.get(f)) or (company_row and company_row.get(f)) or None for f in BADGE_FIELDS}
	)


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
