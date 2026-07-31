# Copyright (c) 2026, Titansoft Limited and contributors

"""Diamond Trust Bank bulk salary upload, matching ``files/DTB TEMPLATE.xls``.

Columns are emitted in the bank's order so an export can be uploaded as-is.
"""

from __future__ import annotations

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.services.payroll_statutory import (
	dtb_branch_code,
	get_period,
	get_salary_slips,
	no_slips_message,
	period_narrative,
)

# The bank rejects a file whose purpose fields are not its own codes.
REMITTANCE_PURPOSE_CODE = "SALA"
REMITTANCE_PURPOSE_DETAILS = "SalaryPayment"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	slips = get_salary_slips(filters)
	if not slips:
		frappe.msgprint(no_slips_message(filters), indicator="orange", title=_("No Payroll Data"))
		return get_columns(), []

	from_date, _to_date = get_period(filters)
	narrative = filters.get("narrative") or period_narrative(from_date)
	address = filters.get("beneficiary_address") or "NAIROBI, KENYA"
	debit_account = filters.get("debit_account_no") or ""

	data = []
	for idx, slip in enumerate(slips, start=1):
		employee = slip.employee_doc
		bank = (employee.get("bank_name") or "").strip()
		# Transfers inside DTB settle internally; anything else leaves the bank.
		is_internal = bank.upper().startswith("DTB") or "DIAMOND TRUST" in bank.upper()

		data.append(
			{
				"additional_info_1": idx,
				"beneficiary_name": (slip.employee_name or "").upper(),
				"beneficiary_address": address,
				"bic_swift_code": "",
				"branch": employee.get("custom_bank_branch") or "",
				"beneficiary_bank_name": bank,
				"dtb_branch_code": dtb_branch_code(employee),
				"beneficiary_account": employee.get("bank_ac_no") or "",
				"payable_amount": slip.net_pay,
				"payment_method": "Internal funds transfer" if is_internal else "EFT",
				"additional_info_2": narrative,
				"payable_currency": "KES",
				"debit_account_no": debit_account,
				"payment_instructions_1": narrative,
				"mobile_service_provider_code": "",
				"bene_mobile_number": "",
				"execution_date": "",
				"supporting_document_name": "",
				"email": "",
				"charge_bourned_by": "",
				"remittance_purpose_code": REMITTANCE_PURPOSE_CODE,
				"remittance_purpose_details": REMITTANCE_PURPOSE_DETAILS,
				"employee": slip.employee,
				"salary_slip": slip.name,
			}
		)

	warn_on_missing_bank_details(slips)
	return get_columns(), data


def warn_on_missing_bank_details(slips) -> None:
	"""The bank rejects the whole file on a blank account number, so surface it early."""
	incomplete = [
		slip.employee_name
		for slip in slips
		if not (slip.employee_doc.get("bank_ac_no") or "").strip()
	]
	if incomplete:
		frappe.msgprint(
			_("{0} employee(s) have no Bank A/C No. and will be rejected by the bank: {1}").format(
				len(incomplete), ", ".join(incomplete)
			),
			indicator="red",
			title=_("Incomplete Bank Details"),
		)


def get_columns():
	return [
		{"fieldname": "additional_info_1", "label": _("Additional Info 1"), "fieldtype": "Int", "width": 130},
		{"fieldname": "beneficiary_name", "label": _("Beneficiary Name"), "fieldtype": "Data", "width": 200},
		{
			"fieldname": "beneficiary_address",
			"label": _("Beneficiary Address"),
			"fieldtype": "Data",
			"width": 160,
		},
		{"fieldname": "bic_swift_code", "label": _("BIC / SWIFT Code"), "fieldtype": "Data", "width": 130},
		{"fieldname": "branch", "label": _("Branch"), "fieldtype": "Data", "width": 140},
		{
			"fieldname": "beneficiary_bank_name",
			"label": _("Beneficiary Bank Name"),
			"fieldtype": "Data",
			"width": 170,
		},
		{"fieldname": "dtb_branch_code", "label": _("DTB Branch Code"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "beneficiary_account",
			"label": _("Beneficiary Account"),
			"fieldtype": "Data",
			"width": 150,
		},
		{"fieldname": "payable_amount", "label": _("Payable Amount"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "payment_method", "label": _("Payment Method"), "fieldtype": "Data", "width": 170},
		{"fieldname": "additional_info_2", "label": _("Additional Info 2"), "fieldtype": "Data", "width": 150},
		{"fieldname": "payable_currency", "label": _("Payable Currency"), "fieldtype": "Data", "width": 120},
		{"fieldname": "debit_account_no", "label": _("Debit Account No"), "fieldtype": "Data", "width": 140},
		{
			"fieldname": "payment_instructions_1",
			"label": _("Payment Instructions 1"),
			"fieldtype": "Data",
			"width": 170,
		},
		{
			"fieldname": "mobile_service_provider_code",
			"label": _("Mobile Service Provider Code"),
			"fieldtype": "Data",
			"width": 200,
		},
		{"fieldname": "bene_mobile_number", "label": _("Bene Mobile Number"), "fieldtype": "Data", "width": 160},
		{"fieldname": "execution_date", "label": _("Execution Date"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "supporting_document_name",
			"label": _("Supporting Document Name"),
			"fieldtype": "Data",
			"width": 190,
		},
		{"fieldname": "email", "label": _("Email"), "fieldtype": "Data", "width": 140},
		{"fieldname": "charge_bourned_by", "label": _("Charge Bourned By"), "fieldtype": "Data", "width": 150},
		{
			"fieldname": "remittance_purpose_code",
			"label": _("Remittance Purpose Code"),
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"fieldname": "remittance_purpose_details",
			"label": _("Remittance Purpose Details"),
			"fieldtype": "Data",
			"width": 190,
		},
		{
			"fieldname": "salary_slip",
			"label": _("Salary Slip"),
			"fieldtype": "Link",
			"options": "Salary Slip",
			"width": 150,
		},
	]
