# Copyright (c) 2026, Titansoft Limited and contributors

from __future__ import annotations

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{
			"fieldname": "name",
			"label": _("Funding Request"),
			"fieldtype": "Link",
			"options": "Funding Request",
			"width": 160,
		},
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{
			"fieldname": "workflow_state",
			"label": _("Status"),
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"fieldname": "approved_by",
			"label": _("Approved By"),
			"fieldtype": "Link",
			"options": "User",
			"width": 160,
		},
		{
			"fieldname": "approval_date",
			"label": _("Approval Date"),
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"fieldname": "total_requested",
			"label": _("Total Requested"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "total_approved",
			"label": _("Total Approved"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "total_funded",
			"label": _("Total Funded"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "outstanding",
			"label": _("Outstanding"),
			"fieldtype": "Currency",
			"width": 120,
		},
	]
	conditions = []
	values = {}
	if filters.get("company"):
		conditions.append("company = %(company)s")
		values["company"] = filters.company
	if filters.get("from_date"):
		conditions.append("posting_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("posting_date <= %(to_date)s")
		values["to_date"] = filters.to_date
	if filters.get("workflow_state"):
		conditions.append("workflow_state = %(workflow_state)s")
		values["workflow_state"] = filters.workflow_state
	where = (" where " + " and ".join(conditions)) if conditions else ""
	data = frappe.db.sql(
		f"""
		select name, posting_date, workflow_state, approved_by, approval_date,
			total_requested, total_approved, total_funded, outstanding
		from `tabFunding Request`
		{where}
		order by posting_date desc, name desc
		""",
		values,
		as_dict=True,
	)
	return columns, data
