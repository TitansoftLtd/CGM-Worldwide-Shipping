frappe.query_reports["DTB Salary Payment Schedule"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.month_start(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.month_start(), -1),
			reqd: 1,
		},
		{
			fieldname: "payroll_entry",
			label: __("Payroll Entry"),
			fieldtype: "Link",
			options: "Payroll Entry",
		},
		{
			fieldname: "debit_account_no",
			label: __("Debit Account No"),
			fieldtype: "Data",
			description: __("Company DTB account the salaries are paid from"),
		},
		{
			fieldname: "narrative",
			label: __("Payment Narrative"),
			fieldtype: "Data",
			description: __("Defaults to 'Salary <Month> <Year>'"),
		},
		{
			fieldname: "beneficiary_address",
			label: __("Beneficiary Address"),
			fieldtype: "Data",
			default: "NAIROBI, KENYA",
		},
	],
};
