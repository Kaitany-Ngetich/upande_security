# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

"""Unauthorized-access-attempt logging + alerting, shared by every gate-side
decision point that can reject or fail to resolve a credential: Gate Dispatch
Verification (api/gate_dispatch.py), Gate Receiving Verification and its
Supplier Badge lookup (api/gate_receiving.py), and the two Visitor Badge
lookup Server Scripts (fixtures/server_script.json).

The two Visitor Badge lookup scripts are sandboxed Server Scripts, which
cannot import this module directly, and - confirmed empirically against a
live safe_exec run, not just assumed - `frappe.get_attr` is NOT reachable
inside that sandbox either (it raises AttributeError: the sandbox's
NamespaceDict has no such attribute). What IS reachable is `frappe.call`,
which dispatches to any already-`@frappe.whitelist()`-decorated function by
its dotted path - exactly like a real `/api/method/...` call. That's why
log_unauthorized_access is whitelisted below, and why the two badge scripts
invoke it as `frappe.call("upande_security.api.security_alerts.
log_unauthorized_access", attempt_type=..., reference=..., ...)` rather than
via frappe.get_attr.

Gated on feature_security_alerts (Security Ops Settings), checked once here
rather than at every call site, so a call site never forgets the check.
Deliberately is_feature_enabled(), NOT require_feature(): a disabled flag
must only skip the logging/alerting, never block the underlying gate action
(dispatch/receiving/badge lookup) it's attached to - see
api.feature_flags.require_feature's own docstring on that split.

Entirely best-effort, matching this app's established convention for a
courtesy escalation layered on top of an already-complete action (see
gate_dispatch._auto_file_shortfall_incident, gate_receiving.
_notify_receiving_team): every exception is caught and logged here, never
re-raised, so a failure logging/alerting an unauthorized attempt can never
undo or block the gate decision that triggered it. Callers can call
log_unauthorized_access() plain, with no try/except of their own needed.
"""

import frappe

from upande_security.api.feature_flags import is_feature_enabled
from upande_security.utils.notifications import resolve_notification_users


@frappe.whitelist()
def log_unauthorized_access(attempt_type, reference, detail, company=None, farm=None):
	"""Records an Unauthorized Access Attempt and raises a Notification Log
	alert to whoever Security Ops Settings' Notification Rules configure for
	the "security" alert type (Security Head / System Manager by default).

	attempt_type: one of Unauthorized Access Attempt.attempt_type's own
	options ("Gate Dispatch Rejected", "Gate Receiving Rejected", "Invalid
	Badge Scan").
	reference: the dispatch/PO name, or the badge reference that was
	scanned - free text, not a Dynamic Link, since the source can vary.
	company/farm: best-effort, may be blank when the call site can't
	resolve either.

	No-ops entirely (returns None, no doc created) when feature_security_alerts
	is off on this instance."""
	if not is_feature_enabled("feature_security_alerts"):
		return None

	try:
		attempt = frappe.new_doc("Unauthorized Access Attempt")
		attempt.attempt_type = attempt_type
		attempt.reference = reference
		attempt.company = company
		attempt.farm = farm
		attempt.detail = detail
		attempt.attempted_by = frappe.session.user
		attempt.attempt_time = frappe.utils.now_datetime()
		# company/farm can arrive here as free-text from an allow_guest
		# caller (e.g. the QR-scan visitor badge lookup) rather than an
		# already-validated Link value - ignore_links so a bogus/mistyped
		# value still gets logged as a descriptive audit string instead of
		# silently dropping the whole attempt on a LinkValidationError.
		attempt.flags.ignore_links = True
		attempt.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception as e:
		frappe.log_error("log_unauthorized_access insert: " + str(attempt_type), str(e))
		return None

	try:
		_notify_unauthorized_access(attempt)
	except Exception as e:
		frappe.log_error("log_unauthorized_access notify: " + attempt.name, str(e))

	return attempt.name


def _notify_unauthorized_access(attempt):
	"""One Notification Log per resolved recipient - same idiom as
	tasks.py's _notify_security_ops, not reused directly since that helper
	is keyed to a Security Guard Shift Assignment document, and an
	Unauthorized Access Attempt has no shift to link to."""
	for recipient in resolve_notification_users("security"):
		notification = frappe.new_doc("Notification Log")
		notification.for_user = recipient
		notification.subject = attempt.attempt_type + ": " + (attempt.reference or attempt.name)
		notification.email_content = (attempt.detail or "").replace("\n", "<br>")
		notification.document_type = "Unauthorized Access Attempt"
		notification.document_name = attempt.name
		notification.type = "Alert"
		try:
			notification.insert(ignore_permissions=True)
		except Exception as e:
			# One bad recipient (e.g. a disabled/deleted User) must never
			# stop the rest from being notified.
			frappe.log_error("_notify_unauthorized_access for " + attempt.name, str(e))
