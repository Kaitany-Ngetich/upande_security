# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Security Watchlist.company -> restrict_to_company.

A Link field named `company` is pre-filled with the creating user's default
company, which silently restricted every new watch to that company - an
employee or visitor of another company was then never matched. The renamed
field is left blank unless someone deliberately sets it.

No-op once the old column is gone.
"""

import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	if frappe.db.has_column("Security Watchlist", "company"):
		rename_field("Security Watchlist", "company", "restrict_to_company")
