# Copyright (c) 2026, Titansoft Limited and contributors

"""KRA iTax P10 monthly PAYE return, matching ``files/PAYE Template.xls``.

Three columns are deliberately left blank -- ``Total Gross Pay``, ``Taxable Pay``
and ``PAYE Tax``. The iTax sheet computes those itself from the columns around
them, and the supplied template leaves them empty; filling them in causes iTax to
flag a mismatch. ``Self Assessed PAYE Tax`` carries the PAYE actually deducted.
"""

from __future__ import annotations

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.services.payroll_statutory import (
	COMPONENT_HOUSING_LEVY,
	COMPONENT_NSSF,
	COMPONENT_PAYE,
	COMPONENT_SHIF,
	MONTHLY_PERSONAL_RELIEF,
	component,
	get_salary_slips,
	no_slips_message,
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
				"pin_of_employee": employee.get("custom_kra_pin") or "",
				"name_of_employee": (slip.employee_name or "").upper(),
				"resident_status": "Resident",
				"type_of_employee": "Primary Employee",
				"person_with_disability": "No",
				"exemption_certificate_number": "",
				"total_cash_pay": slip.gross_pay,
				"value_of_car": 0.0,
				"value_of_meals": 0.0,
				"non_cash_benefits": 0.0,
				"type_of_housing": "Benefit not given",
				"housing_benefits": "",
				"other_benefits": 0.0,
				"total_gross_pay": "",  # computed by iTax
				"shif": component(slip, COMPONENT_SHIF),
				"nssf": component(slip, COMPONENT_NSSF),
				"other_premium_contribution": 0.0,
				"post_retirement_medical": 0.0,
				"mortgage_interest": 0.0,
				"housing_levy": component(slip, COMPONENT_HOUSING_LEVY),
				"taxable_pay": "",  # computed by iTax
				"monthly_personal_relief": MONTHLY_PERSONAL_RELIEF,
				"insurance_relief": 0.0,
				"paye_tax": "",  # computed by iTax
				"self_assessed_paye_tax": component(slip, COMPONENT_PAYE),
				"employee": slip.employee,
				"salary_slip": slip.name,
			}
		)

	warn_on_missing_pins(slips)
	return get_columns(), data


def warn_on_missing_pins(slips) -> None:
	"""iTax keys every row on the KRA PIN, so a blank PIN fails the whole upload."""
	incomplete = [
		slip.employee_name for slip in slips if not (slip.employee_doc.get("custom_kra_pin") or "").strip()
	]
	if incomplete:
		frappe.msgprint(
			_("{0} employee(s) have no KRA PIN and will be rejected by iTax: {1}").format(
				len(incomplete), ", ".join(incomplete)
			),
			indicator="red",
			title=_("Incomplete KRA Details"),
		)


def get_columns():
	def currency(fieldname, label, width=140):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": "Currency", "width": width}

	def data(fieldname, label, width=150):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": "Data", "width": width}

	return [
		data("pin_of_employee", "PIN of Employee", 140),
		data("name_of_employee", "Name of Employee", 200),
		data("resident_status", "Resident Status", 130),
		data("type_of_employee", "Type of Employee", 150),
		data("person_with_disability", "Person with Disability (PWD)", 200),
		data("exemption_certificate_number", "Exemption Certificate Number", 220),
		currency("total_cash_pay", "Total Cash Pay"),
		currency("value_of_car", "Value of Car", 120),
		currency("value_of_meals", "Value of Meals", 130),
		currency("non_cash_benefits", "Non Cash Benefits", 150),
		data("type_of_housing", "Type of Housing", 160),
		data("housing_benefits", "Housing Benefits", 140),
		currency("other_benefits", "Other Benefits", 130),
		data("total_gross_pay", "Total Gross Pay", 140),
		currency("shif", "SHIF", 110),
		currency("nssf", "NSSF", 110),
		currency("other_premium_contribution", "Other Premium Contribution", 210),
		currency("post_retirement_medical", "Post Retirement Medical", 190),
		currency("mortgage_interest", "Mortgage Interest", 150),
		currency("housing_levy", "Housing Levy", 130),
		data("taxable_pay", "Taxable Pay", 120),
		currency("monthly_personal_relief", "Monthly Personal Relief", 190),
		currency("insurance_relief", "Insurance Relief", 140),
		data("paye_tax", "PAYE Tax", 120),
		currency("self_assessed_paye_tax", "Self Assessed PAYE Tax", 180),
		{
			"fieldname": "salary_slip",
			"label": _("Salary Slip"),
			"fieldtype": "Link",
			"options": "Salary Slip",
			"width": 150,
		},
	]
