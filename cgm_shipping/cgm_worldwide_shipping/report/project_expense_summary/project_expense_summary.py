# Copyright (c) 2026, Titansoft Limited and contributors

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{
			"fieldname": "project",
			"label": _("Project"),
			"fieldtype": "Link",
			"options": "Project",
			"width": 160,
		},
		{"fieldname": "project_name", "label": _("Project Name"), "fieldtype": "Data", "width": 200},
		{
			"fieldname": "requested",
			"label": _("Requested"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "approved",
			"label": _("Approved"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "funded",
			"label": _("Funded"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "actual_expense",
			"label": _("Actual Expense"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "outstanding",
			"label": _("Outstanding"),
			"fieldtype": "Currency",
			"width": 120,
		},
	]
	projects = _project_names(filters)
	if not projects:
		return columns, []

	requested = {}
	item_rows = frappe.db.sql(
		"""
		select
			COALESCE(NULLIF(mri.project, ''), mr.custom_project) as project,
			sum(mri.amount) as requested
		from `tabMaterial Request Item` mri
		inner join `tabMaterial Request` mr on mr.name = mri.parent
		where mr.docstatus < 2
		  and COALESCE(NULLIF(mri.project, ''), mr.custom_project) in %(projects)s
		group by 1
		""",
		{"projects": projects},
		as_dict=True,
	)
	for row in item_rows:
		if row.project:
			requested[row.project] = flt(row.requested)
	approved = _sum_by_project(
		"Material Request",
		"custom_approved_amount",
		"custom_project",
		projects,
		{"docstatus": ["<", 2]},
	)
	funded = _sum_by_project(
		"Employee Advance",
		"paid_amount",
		"custom_project",
		projects,
		{"docstatus": 1},
	)
	invoices = _sum_by_project(
		"Purchase Invoice",
		"base_grand_total",
		"project",
		projects,
		{"docstatus": 1, "is_return": 0},
	)
	names = frappe.get_all(
		"Project",
		filters={"name": ["in", projects]},
		fields=["name", "project_name"],
	)
	name_map = {row.name: row.project_name for row in names}
	data = []
	for project in projects:
		req = flt(requested.get(project))
		app = flt(approved.get(project))
		fun = flt(funded.get(project))
		actual = flt(invoices.get(project)) + fun
		if not any((req, app, fun, actual)) and filters.get("project"):
			# Still show the selected shipment even with zeros.
			pass
		elif not any((req, app, fun, actual)):
			continue
		data.append(
			{
				"project": project,
				"project_name": name_map.get(project),
				"requested": req,
				"approved": app,
				"funded": fun,
				"actual_expense": actual,
				"outstanding": app - fun,
			}
		)
	data.sort(key=lambda row: row["project"])
	return columns, data


def _project_names(filters) -> list[str]:
	if filters.get("project"):
		return [filters.project]
	names = frappe.get_all(
		"Material Request",
		filters={"custom_project": ["is", "set"], "docstatus": ["<", 2]},
		pluck="custom_project",
		distinct=True,
	)
	return [name for name in names if name]


def _sum_by_project(doctype, amount_field, project_field, projects, extra_filters) -> dict[str, float]:
	meta = frappe.get_meta(doctype)
	if not meta.has_field(amount_field) or not meta.has_field(project_field):
		return {}
	filters = {project_field: ["in", projects], **extra_filters}
	rows = frappe.get_all(
		doctype,
		filters=filters,
		fields=[project_field, amount_field],
	)
	out: dict[str, float] = {}
	for row in rows:
		key = row.get(project_field)
		if not key:
			continue
		out[key] = flt(out.get(key)) + flt(row.get(amount_field))
	return out
