# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Shared filters for the CCTV reports: a date range, a site, a company."""

import frappe
from frappe.utils import add_days, getdate


def window(filters, default_days=30):
	f = frappe._dict(filters or {})
	to = getdate(f.to_date) if f.to_date else getdate()
	frm = getdate(f.from_date) if f.from_date else add_days(to, -default_days + 1)
	return f"{frm} 00:00:00", f"{to} 23:59:59"


def site_clause(filters, column="farm", alias=""):
	"""SQL fragment + values limiting to the chosen site or company's sites."""
	f = frappe._dict(filters or {})
	col = f"{alias}.{column}" if alias else column
	if f.farm:
		return f" and {col} = %(farm)s", {"farm": f.farm}
	if f.company:
		farms = frappe.get_all("Farm", filters={"company": f.company}, pluck="name") or ["-"]
		return f" and {col} in %(farms)s", {"farms": tuple(farms)}
	return "", {}


def median(values):
	vals = sorted(v for v in values if v is not None)
	if not vals:
		return None
	mid = len(vals) // 2
	return vals[mid] if len(vals) % 2 else round((vals[mid - 1] + vals[mid]) / 2, 1)


COMMON_FILTERS_JS = """[
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -29) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "farm", label: __("Site"), fieldtype: "Link", options: "Farm" }"""
