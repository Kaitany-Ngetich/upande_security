# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class UnauthorizedAccessAttempt(Document):
	"""Audit log record, one per detected unauthorized attempt (a rejected
	Gate Dispatch/Gate Receiving verification, or a badge scan that didn't
	resolve to anything valid).

	Created programmatically via ignore_permissions=True from
	upande_security.api.security_alerts.log_unauthorized_access - never
	filled in directly by a guard through a form, so there is deliberately
	no create/write permission for Security Head, only read (see this
	doctype's own permissions list)."""

	pass
