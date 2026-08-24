# Copyright (c) 2026, Titansoft Limited and contributors

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{
			"fieldname": "name",
			"label": _("Material Request"),
			"fieldtype": "Link",
			"options": "Material Request",
			"width": 150,
		},
		{
			"fieldname": "item_code",
			"label": _("Item"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 160,
		},
		{
			"fieldname": "item_name",
			"label": _("Item Name"),
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"fieldname": "material_request_type",
			"label": _("Request Type"),
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"fieldname": "custom_project",
			"label": _("Project / Shipment"),
			"fieldtype": "Link",
			"options": "Project",
			"width": 140,
		},
		{
			"fieldname": "qty",
			"label": _("Qty"),
			"fieldtype": "Float",
			"width": 80,
		},
		{
			"fieldname": "rate",
			"label": _("Rate"),
			"fieldtype": "Currency",
			"width": 100,
		},
		{
			"fieldname": "requested_amount",
			"label": _("Requested Amount"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "approved_amount",
			"label": _("Approved Amount"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "variance",
			"label": _("Variance"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"fieldname": "workflow_state",
			"label": _("Funding Status"),
			"fieldtype": "Link",
			"options": "Workflow State",
			"width": 160,
		},
		{
			"fieldname": "funded_amount",
			"label": _("Funded Amount"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "custom_funding_request",
			"label": _("Funding Request"),
			"fieldtype": "Link",
			"options": "Funding Request",
			"width": 150,
		},
	]
	conditions = ["mr.docstatus < 2"]
	values = {}
	if filters.get("company"):
		conditions.append("mr.company = %(company)s")
		values["company"] = filters.company
	if filters.get("project"):
		conditions.append(
			"COALESCE(NULLIF(mri.project, ''), mr.custom_project) = %(project)s"
		)
		values["project"] = filters.project
	if filters.get("item"):
		conditions.append("mri.item_code = %(item)s")
		values["item"] = filters.item
	if filters.get("from_date"):
		conditions.append("mr.transaction_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("mr.transaction_date <= %(to_date)s")
		values["to_date"] = filters.to_date
	where = " where " + " and ".join(conditions)
	rows = frappe.db.sql(
		f"""
		select
			mr.name,
			mr.material_request_type,
			mr.custom_project,
			mr.custom_funding_request,
			mr.workflow_state,
			mr.custom_approved_amount as mr_approved,
			mri.item_code,
			mri.item_name,
			mri.qty,
			mri.rate,
			mri.amount as requested_amount
		from `tabMaterial Request Item` mri
		inner join `tabMaterial Request` mr on mr.name = mri.parent
		{where}
		order by mr.transaction_date desc, mr.name desc, mri.idx asc
		""",
		values,
		as_dict=True,
	)
	mr_totals: dict[str, float] = {}
	for row in rows:
		mr_totals[row.name] = flt(mr_totals.get(row.name)) + flt(row.requested_amount)

	funded_by_mr = _funded_amount_by_material_request(
		[row.custom_funding_request for row in rows if row.custom_funding_request]
	)

	data = []
	for row in rows:
		mr_total = flt(mr_totals.get(row.name))
		share = (flt(row.requested_amount) / mr_total) if mr_total else 0
		approved = flt(row.mr_approved) * share
		funded = flt(funded_by_mr.get(row.name)) * share
		data.append(
			{
				"name": row.name,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"material_request_type": row.material_request_type,
				"custom_project": row.custom_project,
				"qty": row.qty,
				"rate": row.rate,
				"requested_amount": flt(row.requested_amount),
				"approved_amount": approved,
				"variance": approved - flt(row.requested_amount),
				"workflow_state": row.workflow_state,
				"funded_amount": funded,
				"custom_funding_request": row.custom_funding_request,
			}
		)
	return columns, data


def _funded_amount_by_material_request(funding_requests: list[str]) -> dict[str, float]:
	parents = list({name for name in funding_requests if name})
	if not parents:
		return {}
	rows = frappe.get_all(
		"Funding Request Material Request",
		filters={"parent": ["in", parents], "material_request": ["is", "set"]},
		fields=["material_request", "funded_amount"],
	)
	out: dict[str, float] = {}
	for row in rows:
		out[row.material_request] = flt(out.get(row.material_request)) + flt(row.funded_amount)
	return out
