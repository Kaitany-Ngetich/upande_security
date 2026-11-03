"""Incident Report's injury follow-up and police fields were Custom Fields made
by hand on one site and never shipped. They are now standard fields of the
doctype; drop the Custom Field records first so the sync can own the same
columns (same names and types, so the data stays where it is)."""

import frappe

FIELDS = (
	"classification_section", "activity_at_time_of_injury", "body_part_affected",
	"classification_cb_1", "nature_of_injury", "is_fatal",
	"injury_section", "injury_case_status", "injury_current_location", "injury_cb_1",
	"days_off_work", "return_to_work_date",
	"response_section", "first_aid_given", "first_aider_name", "response_cb_1",
	"ambulance_needed", "ambulance_provider", "ambulance_called_at",
	"hospital_section", "taken_to_hospital", "hospital_name", "hospital_cb_1",
	"hospital_admission_type", "attending_physician", "treatment_summary",
	"police_section", "police_report_required", "ob_number", "police_cb_1", "police_station",
	"compensation_section", "compensation_required", "wiba_claim_filed", "wiba_claim_number",
	"compensation_cb_1", "payment_status", "amount_paid",
	"doshs_section", "doshs_deadline", "doshs_reported", "doshs_cb_1",
	"doshs_reported_date", "doshs_reference_number",
)


def execute():
	for name in frappe.get_all(
		"Custom Field",
		filters={"dt": "Incident Report", "fieldname": ("in", FIELDS)},
		pluck="name",
	):
		# delete the record only; the column and its data stay for the sync
		frappe.db.delete("Custom Field", {"name": name})
	frappe.clear_cache(doctype="Incident Report")
