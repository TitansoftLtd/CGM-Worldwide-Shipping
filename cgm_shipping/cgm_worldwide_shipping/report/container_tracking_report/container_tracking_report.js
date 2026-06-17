// Copyright (c) 2026, Titansoft Limited and contributors

frappe.query_reports["Container Tracking Report"] = {
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
			options:
				"\nPending Arrival\nVessel Berthed\nDischarged / At Port\nReleased / In Transit\nAt Warehouse\nCargo Offloaded\nEmpty Returned\nReturn Overdue\nInterchange Received",
		},
		{
			fieldname: "from_date",
			label: __("Discharge From"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("Discharge To"),
			fieldtype: "Date",
		},
		{
			fieldname: "shipping_line",
			label: __("Shipping Line"),
			fieldtype: "Link",
			options: "Supplier",
		},
		{
			fieldname: "show_only_active",
			label: __("Show Only Active"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "show_only_alerts",
			label: __("Show Only Alerts"),
			fieldtype: "Check",
			default: 0,
		},
	],
	formatter(value, row, column, data) {
		if (data && data.row_style) {
			return `<span style="${data.row_style}">${frappe.format(value, column)}</span>`;
		}
		return value;
	},
};
