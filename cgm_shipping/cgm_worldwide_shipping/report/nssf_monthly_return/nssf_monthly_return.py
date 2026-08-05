# Copyright (c) 2026, Titansoft Limited and contributors

"""NSSF byproduct return, matching ``files/Nssf Template.xlsx``."""

from __future__ import annotations

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.services.payroll_statutory import (
	get_salary_slips,
	no_slips_message,
	other_names,
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
		data.append(
			{
				"payroll_number": payroll_number(employee),
				"surname": employee.get("last_name") or "",
				"other_names": other_names(employee),
				"id_no": employee.get("custom_id_number") or "",
				"kra_pin": employee.get("custom_kra_pin") or "",
				"nssf_no": employee.get("custom_nssf_no") or "",
				"gross_pay": slip.gross_pay,
				"voluntary": "",
				"employee": slip.employee,
				"salary_slip": slip.name,
			}
		)

	warn_on_missing_numbers(slips)
	return get_columns(), data


def warn_on_missing_numbers(slips) -> None:
	incomplete = [
		slip.employee_name for slip in slips if not (slip.employee_doc.get("custom_nssf_no") or "").strip()
	]
	if incomplete:
		frappe.msgprint(
			_("{0} employee(s) have no NSSF No. and will be rejected on upload: {1}").format(
				len(incomplete), ", ".join(incomplete)
			),
			indicator="red",
			title=_("Incomplete NSSF Details"),
		)


def get_columns():
	return [
		{"fieldname": "payroll_number", "label": _("Payroll Number"), "fieldtype": "Data", "width": 130},
		{"fieldname": "surname", "label": _("Surname"), "fieldtype": "Data", "width": 160},
		{"fieldname": "other_names", "label": _("Other Names"), "fieldtype": "Data", "width": 200},
		{"fieldname": "id_no", "label": _("ID Number"), "fieldtype": "Data", "width": 120},
		{"fieldname": "kra_pin", "label": _("KRA PIN"), "fieldtype": "Data", "width": 140},
		{"fieldname": "nssf_no", "label": _("NSSF Number"), "fieldtype": "Data", "width": 140},
		{"fieldname": "gross_pay", "label": _("Gross Pay"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "voluntary", "label": _("Voluntary"), "fieldtype": "Data", "width": 120},
		{
			"fieldname": "salary_slip",
			"label": _("Salary Slip"),
			"fieldtype": "Link",
			"options": "Salary Slip",
			"width": 150,
		},
	]
