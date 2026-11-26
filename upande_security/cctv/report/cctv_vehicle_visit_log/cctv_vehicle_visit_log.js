// Copyright (c) 2026, dev@upande.com and contributors
// For license information, please see license.txt

frappe.query_reports["CCTV Vehicle Visit Log"] = {
	filters: [
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -29) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "farm", label: __("Site"), fieldtype: "Link", options: "Farm" },
		{ fieldname: "party_type", label: __("Party type"), fieldtype: "Select", options: "\nVisitor\nCustomer\nContractor\nSupplier\nFleet\nStaff\nUnknown" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nOn Premises\nDeparted\nOverstayed\nExit Not Recorded\nClosed Manually" },
	],
};
