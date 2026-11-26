"""Guard + time indexes on Patrol GPS Log (see patrol_gps_log.on_doctype_update):
the doctype is only re-synced when its JSON changes, so add them here too."""

from upande_security.upande_security.doctype.patrol_gps_log.patrol_gps_log import on_doctype_update


def execute():
	on_doctype_update()
