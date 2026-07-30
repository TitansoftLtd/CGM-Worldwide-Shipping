# Copyright (c) 2026, Titansoft Limited and contributors

"""SHIF (ex NHIF) contribution schedule, matching ``files/SHIF Template.xlsx``.

The portal still labels the member number column ``NHIF NO``; it is sourced from
the Employee's SHIF No. field. ``IDENTITY TYPE`` accepts National ID, Refugee ID,
Alien ID or Passport Number -- resolved per employee below.
"""

from __future__ import annotations

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.services.payroll_statutory import (
	COMPONENT_SHIF,
	component,
	get_salary_slips,
	no_slips_message,
	payroll_number,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	slips = get_salary_slips(filters)
	if not slips:
		frappe.msgprint(no_slips_message(filters), indicator="orange", title=_("No Payroll Data"))
		return get_columns(), []

	data = []
	for slip in slips:
		employee = slip.employee_doc
		national_id = (employee.get("custom_id_number") or "").strip()
		passport = (employee.get("passport_number") or "").strip()

		data.append(
			{
				"payroll_number": payroll_number(employee),
				"firstname": employee.get("first_name") or "",
				"lastname": employee.get("last_name") or "",
				"identity_type": "National ID" if national_id else ("Passport Number" if passport else ""),
				"id_no": national_id or passport,
				"kra_pin": employee.get("custom_kra_pin") or "",
				"nhif_no": employee.get("custom_shif_no") or "",
				"contribution_amount": component(slip, COMPONENT_SHIF),
				"phone": employee.get("cell_number") or "",
				"employee": slip.employee,
				"salary_slip": slip.name,
			}
		)

	warn_on_missing_numbers(slips)
	return get_columns(), data


def warn_on_missing_numbers(slips) -> None:
	incomplete = [
		slip.employee_name for slip in slips if not (slip.employee_doc.get("custom_shif_no") or "").strip()
	]
	if incomplete:
		frappe.msgprint(
			_("{0} employee(s) have no SHIF No. and will be rejected on upload: {1}").format(
				len(incomplete), ", ".join(incomplete)
			),
			indicator="red",
			title=_("Incomplete SHIF Details"),
		)


def get_columns():
	return [
		{"fieldname": "payroll_number", "label": _("Payroll Number"), "fieldtype": "Data", "width": 130},
		{"fieldname": "firstname", "label": _("First Name"), "fieldtype": "Data", "width": 160},
		{"fieldname": "lastname", "label": _("Last Name"), "fieldtype": "Data", "width": 160},
		{"fieldname": "identity_type", "label": _("Identity Type"), "fieldtype": "Data", "width": 140},
		{"fieldname": "id_no", "label": _("ID Number"), "fieldtype": "Data", "width": 120},
		{"fieldname": "kra_pin", "label": _("KRA PIN"), "fieldtype": "Data", "width": 140},
		{"fieldname": "nhif_no", "label": _("NHIF Number"), "fieldtype": "Data", "width": 150},
		{
			"fieldname": "contribution_amount",
			"label": _("Contribution Amount"),
			"fieldtype": "Currency",
			"width": 190,
		},
		{"fieldname": "phone", "label": _("Phone"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "salary_slip",
			"label": _("Salary Slip"),
			"fieldtype": "Link",
			"options": "Salary Slip",
			"width": 150,
		},
	]
