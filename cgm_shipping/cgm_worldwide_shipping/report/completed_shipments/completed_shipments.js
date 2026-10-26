// For license information, please see license.txt

frappe.query_reports["Completed Shipments"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 1,
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "shipment_type",
			label: __("Shipment Type"),
			fieldtype: "Link",
			options: "Shipment Type",
		},
		{
			// Left blank the report covers every finished status, which is the usual question.
			fieldname: "shipment_status",
			label: __("Shipment Status"),
			fieldtype: "Select",
			options: ["", "Completed", "Settled"].join("\n"),
		},
	],
};
