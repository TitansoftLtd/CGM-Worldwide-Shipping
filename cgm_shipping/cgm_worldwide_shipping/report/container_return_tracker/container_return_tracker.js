frappe.query_reports["Container Return Tracker"] = {
	filters: [
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "clearance_station",
			label: __("Clearance Station"),
			fieldtype: "Link",
			options: "Clearance Station",
		},
	],
};
