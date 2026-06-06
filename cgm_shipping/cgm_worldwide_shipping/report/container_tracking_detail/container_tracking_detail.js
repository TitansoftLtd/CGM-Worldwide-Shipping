// Copyright (c) 2026, Titansoft Limited and contributors

frappe.query_reports["Container Tracking Detail"] = {
	filters: [
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nDispatched\nDelivered\nEmpty Pending\nEmpty Returned\nOverdue",
		},
		{
			fieldname: "overdue_only",
			label: __("Overdue Only"),
			fieldtype: "Check",
		},
		{
			fieldname: "min_demurrage_days",
			label: __("Min Demurrage Days"),
			fieldtype: "Int",
		},
	],
};
