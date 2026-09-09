frappe.query_reports["Project Expense Summary"] = {
	filters: [
		{
			fieldname: "project",
			label: __("Project / Shipment"),
			fieldtype: "Link",
			options: "Project",
		},
	],
};
