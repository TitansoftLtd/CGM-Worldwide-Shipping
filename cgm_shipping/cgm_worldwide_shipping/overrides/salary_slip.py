# Copyright (c) 2026, Titansoft Limited and contributors
"""Salary Slip override: add net-pay-only components into Net Pay."""

from __future__ import annotations

import frappe
from frappe.utils import flt, rounded
from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip

from cgm_shipping.cgm_worldwide_shipping.overrides.salary_component import (
	get_net_pay_only_components,
)


class CGMSalarySlip(SalarySlip):
	def net_pay_only_total(self, based_on_payment_days: bool = True) -> float:
		"""Sum of earning rows flagged Include in Net Pay Only.

		`based_on_payment_days` mirrors how the caller built Gross Pay, so the
		add-back is exactly the amount that would have been in Gross had the flag
		not been set - and matches the row amount the payroll JE and bank entry use.
		"""
		components = get_net_pay_only_components()
		if not components:
			return 0.0

		total = 0.0
		for row in self.earnings or []:
			if row.salary_component not in components:
				continue
			if not row.do_not_include_in_total:
				# Gross already counted this row, so adding it to Net would pay it
				# twice. Happens when the flag is ticked on a component that is
				# already in a Salary Structure: the structure snapshots the flags
				# when the component is added and HRMS never propagates a later
				# change, so the slip row is stale. Degrade to stock behaviour -
				# the component stays in Gross - rather than overpay.
				continue
			if based_on_payment_days:
				total += flt(self.get_amount_based_on_payment_days(row)[0])
			else:
				total += flt(row.amount, row.precision("amount"))

		return total

	def set_net_pay(self):
		# Core: net_pay = gross_pay - deductions - loans, and gross_pay already
		# skips these rows (do_not_include_in_total), so add them straight to net.
		super().set_net_pay()

		add_back = self.net_pay_only_total()
		if not add_back:
			return

		self.net_pay = flt(self.net_pay) + add_back
		self.rounded_total = rounded(self.net_pay)
		self.base_net_pay = flt(flt(self.net_pay) * flt(self.exchange_rate), self.precision("base_net_pay"))
		self.base_rounded_total = flt(rounded(self.base_net_pay), self.precision("base_net_pay"))
		self.set_net_total_in_words()

	@frappe.whitelist()
	def set_totals(self) -> None:
		super().set_totals()

		add_back = self.net_pay_only_total(based_on_payment_days=False)
		if not add_back:
			return

		self.gross_pay = flt(self.gross_pay) - add_back
		self.set_base_totals()
