# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ZoneAccessRule(Document):
	"""One line of a Security Zone's access policy.

	Validated by the parent (SecurityZone.validate), not here: a rule only
	makes sense against the zone's default_access and the order of its
	siblings, and a child's own validate cannot see either.
	"""

	pass
