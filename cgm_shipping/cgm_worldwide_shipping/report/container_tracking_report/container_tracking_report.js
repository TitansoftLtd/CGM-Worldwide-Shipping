// Copyright (c) 2026, Titansoft Limited and contributors

frappe.query_reports["Container Tracking Report"] = {
	filters: [
		{
			fieldname: "project",
			label: __("CGM Reference"),
			fieldtype: "Link",
			options: "Project",
		},
		{
			fieldname: "bl_number",
			label: __("B/L Number"),
			fieldtype: "Data",
		},
		{
			fieldname: "clearance_station",
			label: __("Clearance Station"),
			fieldtype: "Link",
			options: "Clearance Station",
		},
		{
			fieldname: "shipping_line",
			label: __("Shipping Line"),
			fieldtype: "Link",
			options: "Supplier",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			// From the shared status table, so transit statuses can be filtered too.
			options: window.cgm_shipping?.container_tracking?.status_select_options?.() || "",
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
			fieldname: "show_only_active",
			label: __("Show Active Only"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "show_expanded",
			label: __("Show Expanded Columns"),
			fieldtype: "Check",
			default: 0,
		},
	],
	formatter(value, row, column, data) {
		const formatted = frappe.format(value, column);
		if (data && data.row_style) {
			if (data.is_group_header) {
				return `<div style="${data.row_style}">${frappe.utils.escape_html(
					data.container_number || ""
				)}</div>`;
			}
			return `<span style="${data.row_style}">${formatted}</span>`;
		}
		if (column.fieldname === "status" && value) {
			const color = cgm_container_status_color(value);
			return `<span class="indicator-pill ${color}">${formatted}</span>`;
		}
		return formatted;
	},
};

function cgm_container_status_color(status) {
	const status_color = window.cgm_shipping?.container_tracking?.status_color;
	return status_color ? status_color(status) : "gray";
}
