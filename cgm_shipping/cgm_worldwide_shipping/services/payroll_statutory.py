# Copyright (c) 2026, Titansoft Limited and contributors

"""Shared data access for the Kenyan statutory payroll exports.

Four reports build on this module, each mirroring a filing template supplied by
finance (``apps/cgm_shipping/files``):

* ``DTB Salary Payment Schedule`` -- Diamond Trust Bank bulk payment upload
* ``NSSF Monthly Return``         -- NSSF byproduct return
* ``PAYE Monthly Return``         -- KRA iTax P10 CSV
* ``SHIF Monthly Return``         -- SHIF (ex NHIF) contribution schedule

Every report exports the template's columns in the template's order, so
``Menu > Export`` produces a file that can be uploaded to the portal without
being reshaped by hand.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_months, get_first_day, get_last_day, getdate

# Salary Component names this site uses for the statutory deductions. Keep these
# in sync with the Salary Component list if finance ever renames a component.
COMPONENT_PAYE = "PAYE"
COMPONENT_NSSF = "NSSF"
COMPONENT_SHIF = "SHIF"
COMPONENT_HOUSING_LEVY = "Housing Levy"
COMPONENT_PERSONAL_RELIEF = "Personal Relief"

# Statutory monthly personal relief (KES). Kenya Finance Act rate.
MONTHLY_PERSONAL_RELIEF = 2400.0

# DTB branch codes, as seen on the supplied DTB template. Finance can extend
# this map as more branches are used; an unmapped branch exports blank rather
# than guessing a code, since a wrong code misroutes the payment.
DTB_BRANCH_CODES = {
	"koinange street": "069",
	"thika": "012",
}


def get_period(filters) -> tuple[str, str]:
	"""Resolve the reporting period, defaulting to the previous calendar month."""
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")

	if not from_date or not to_date:
		last_month = add_months(getdate(), -1)
		from_date = from_date or get_first_day(last_month)
		to_date = to_date or get_last_day(last_month)

	return getdate(from_date), getdate(to_date)


def get_salary_slips(filters) -> list[frappe._dict]:
	"""Submitted salary slips for the period, with the employee identity fields.

	Slips are matched on ``start_date`` falling inside the period so a single
	month is picked up exactly once, even when the filter spans a wider range.
	"""
	filters = frappe._dict(filters or {})
	from_date, to_date = get_period(filters)

	conditions = {
		"docstatus": 1,
		"start_date": ["between", [from_date, to_date]],
	}
	if filters.get("company"):
		conditions["company"] = filters.company
	if filters.get("payroll_entry"):
		conditions["payroll_entry"] = filters.payroll_entry
	if filters.get("employee"):
		conditions["employee"] = filters.employee

	slips = frappe.get_all(
		"Salary Slip",
		filters=conditions,
		fields=[
			"name",
			"employee",
			"employee_name",
			"company",
			"start_date",
			"end_date",
			"gross_pay",
			"net_pay",
			"total_deduction",
		],
		order_by="employee_name",
	)
	if not slips:
		return []

	employees = {
		e.name: e
		for e in frappe.get_all(
			"Employee",
			filters={"name": ["in", [s.employee for s in slips]]},
			fields=[
				"name",
				"employee_name",
				"first_name",
				"middle_name",
				"last_name",
				"cell_number",
				"employee_number",
				"custom_id_number",
				"passport_number",
				"custom_kra_pin",
				"custom_nssf_no",
				"custom_shif_no",
				"bank_name",
				"custom_bank_branch",
				"bank_ac_no",
			],
		)
	}
	amounts = get_component_amounts([s.name for s in slips])

	for slip in slips:
		slip.employee_doc = employees.get(slip.employee, frappe._dict())
		slip.components = amounts.get(slip.name, {})

	return slips


def get_component_amounts(slip_names: list[str]) -> dict[str, dict[str, float]]:
	"""Map ``{salary slip: {salary component: amount}}`` across earnings and deductions."""
	if not slip_names:
		return {}

	rows = frappe.get_all(
		"Salary Detail",
		filters={"parenttype": "Salary Slip", "parent": ["in", slip_names]},
		fields=["parent", "salary_component", "amount"],
	)

	amounts: dict[str, dict[str, float]] = {}
	for row in rows:
		amounts.setdefault(row.parent, {})[row.salary_component] = flt_amount(row.amount)
	return amounts


def component(slip, name: str) -> float:
	"""Amount of ``name`` on ``slip``, or 0 when the component is not on the slip."""
	return flt_amount(slip.components.get(name))


def flt_amount(value) -> float:
	return round(float(value or 0), 2)


def payroll_number(employee) -> str:
	"""The employee's payroll number -- their Employee Number, not a row counter.

	Falls back to the Employee ID, which on this site is the same value.
	"""
	return (employee.get("employee_number") or employee.get("name") or "").strip()


def other_names(employee) -> str:
	"""First + middle name, as the NSSF return separates surname from the rest."""
	parts = [employee.get("first_name"), employee.get("middle_name")]
	return " ".join(p.strip() for p in parts if p and p.strip())


def period_narrative(from_date) -> str:
	"""``Salary June 2026`` -- the narrative finance writes on the DTB schedule."""
	return f"Salary {getdate(from_date).strftime('%B %Y')}"


def dtb_branch_code(branch: str | None) -> str:
	return DTB_BRANCH_CODES.get((branch or "").strip().lower(), "")


def no_slips_message(filters) -> str:
	from_date, to_date = get_period(filters)
	return frappe._(
		"No submitted Salary Slips found between {0} and {1}. Run and submit payroll for the period first."
	).format(frappe.format(from_date, "Date"), frappe.format(to_date, "Date"))
