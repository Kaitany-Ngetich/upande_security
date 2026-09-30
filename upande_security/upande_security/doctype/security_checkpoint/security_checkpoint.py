# Copyright (c) 2026, dev@upande.com and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SecurityCheckpoint(Document):
	"""Admin-configured reference data: a physical point on a farm (e.g. a
	specific gate, store, or block corner) a patrol is expected to physically
	reach. Read by upande_security.tasks.check_unscanned_checkpoints, which
	flags any Active shift that hasn't come within radius_m of one of its
	farm's active checkpoints within Security Ops Settings'
	missed_checkin_minutes of shift start."""

	pass
