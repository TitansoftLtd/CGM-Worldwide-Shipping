"""Quotation import-cost and customs tax calculations."""

from __future__ import annotations

from erpnext import get_company_currency
from erpnext.selling.doctype.quotation.quotation import Quotation
from erpnext.setup.utils import get_exchange_rate
from frappe.utils import flt, round_based_on_smallest_currency_fraction

IMPORT_COST_TABLE = "custom_import_cost_component"
USD_CURRENCY = "USD"


class CGMQuotation(Quotation):
	def validate(self):
		super().validate()
		self._calculate_import_customs_taxes()

	def _calculate_import_customs_taxes(self):
		if not self.meta.has_field(IMPORT_COST_TABLE):
			return

		company_currency = get_company_currency(self.company)
		rows = self.get(IMPORT_COST_TABLE) or []

		customs_value_kes = 0.0

		for row in rows:
			self._normalize_import_cost_row(row, company_currency)
			row.amount_kes = self._amount_in_kes(row, company_currency)
			customs_value_kes += flt(row.amount_kes)

		customs_value_kes = self._money(customs_value_kes, "custom_customs_value_kes")
		customs_value_usd = self._money(
			self._calculate_customs_value_usd(rows, company_currency),
			"custom_customs_value_usd",
		)
		self.custom_customs_value_kes = customs_value_kes
		self.custom_customs_value_usd = customs_value_usd

		duty_amount = self._set_percent_of(
			customs_value_kes, "custom_duty_rate_", "custom_duty_amount_kes"
		)
		idf_amount = self._set_percent_of(customs_value_kes, "custom_idf_rate_", "custom_idf_amount_kes")
		rdl_amount = self._set_percent_of(customs_value_kes, "custom_rdl_rate_", "custom_rdl_amount_kes")
		excise_amount = self._set_percent_of(
			customs_value_kes + duty_amount,
			"custom_excise_duty_rate_",
			"custom_excise_duty_amount_kes",
		)
		vat_base = customs_value_kes + duty_amount + excise_amount + idf_amount + rdl_amount
		vat_amount = self._set_percent_of(vat_base, "custom_vat_rate_", "custom_vat_amount_kes")

		mss_levy = self._money(self.custom_mss_levy_kes, "custom_mss_levy_kes")
		total_taxes = self._money(
			duty_amount + excise_amount + vat_amount + idf_amount + rdl_amount + mss_levy,
			"custom_total_taxes_kes",
		)
		self.custom_total_taxes_kes = total_taxes
		self._apply_customs_to_standard_totals(total_taxes)

	def _apply_customs_to_standard_totals(self, total_taxes_kes: float) -> None:
		"""Reflect import/customs taxes in ERPNext standard total fields."""
		customs_taxes = self._customs_taxes_in_doc_currency(total_taxes_kes)
		if not customs_taxes:
			return

		self.total_taxes_and_charges = self._money(
			flt(self.total_taxes_and_charges) + customs_taxes,
			"total_taxes_and_charges",
		)
		self.base_total_taxes_and_charges = self._money(
			flt(self.base_total_taxes_and_charges) + flt(total_taxes_kes),
			"base_total_taxes_and_charges",
		)
		self.grand_total = self._money(
			flt(self.net_total) + flt(self.total_taxes_and_charges),
			"grand_total",
		)
		self.base_grand_total = self._money(
			flt(self.grand_total) * flt(self.conversion_rate),
			"base_grand_total",
		)
		self._set_rounded_totals()
		self.set_total_in_words()

	def _customs_taxes_in_doc_currency(self, total_taxes_kes: float) -> float:
		company_currency = get_company_currency(self.company)
		if self.currency == company_currency:
			return flt(total_taxes_kes)

		conversion_rate = flt(self.conversion_rate)
		if not conversion_rate:
			return 0.0

		return flt(
			total_taxes_kes / conversion_rate,
			self.precision("total_taxes_and_charges"),
		)

	def _set_rounded_totals(self) -> None:
		if self.is_rounded_total_disabled():
			self.rounded_total = 0.0
			self.rounding_adjustment = 0.0
			self.base_rounded_total = 0.0
			self.base_rounding_adjustment = 0.0
			return

		self.rounded_total = round_based_on_smallest_currency_fraction(
			self.grand_total,
			self.currency,
			self.precision("rounded_total"),
		)
		self.rounding_adjustment = self._money(
			self.rounded_total - self.grand_total,
			"rounding_adjustment",
		)
		self.base_rounded_total = self._money(
			self.rounded_total * flt(self.conversion_rate),
			"base_rounded_total",
		)
		self.base_rounding_adjustment = self._money(
			self.base_rounded_total - self.base_grand_total,
			"base_rounding_adjustment",
		)

	def _normalize_import_cost_row(self, row, company_currency: str) -> None:
		if row.currency == company_currency:
			row.exchange_rate = 1

	def _amount_in_kes(self, row, company_currency: str) -> float:
		amount = flt(row.amount)
		if row.currency == company_currency:
			return amount

		return flt(amount * flt(row.exchange_rate), row.precision("amount_kes"))

	def _calculate_customs_value_usd(self, rows, company_currency: str) -> float:
		"""Sum USD rows directly; sum KES (and other foreign) in KES, then convert once to USD."""
		usd_total = 0.0
		kes_total = 0.0

		for row in rows:
			currency = row.currency
			amount = flt(row.amount)

			if currency == USD_CURRENCY:
				usd_total += amount
			elif currency == company_currency:
				kes_total += amount
			else:
				kes_total += flt(row.amount_kes)

		usd_to_kes_rate = self._get_usd_to_kes_rate(rows, company_currency)
		kes_in_usd = flt(kes_total / usd_to_kes_rate) if usd_to_kes_rate else 0.0

		return usd_total + kes_in_usd

	def _get_usd_to_kes_rate(self, rows, company_currency: str) -> float:
		"""KES per 1 USD from USD import-cost rows, else ERPNext exchange rate."""
		for row in rows:
			if row.currency == USD_CURRENCY and flt(row.exchange_rate):
				return flt(row.exchange_rate)

		return flt(get_exchange_rate(USD_CURRENCY, company_currency, self.transaction_date) or 0)

	def _money(self, value, fieldname: str) -> float:
		return flt(value, self.precision(fieldname))

	def _rate(self, fieldname: str) -> float:
		return flt(self.get(fieldname))

	def _set_percent_of(self, base: float, rate_field: str, amount_field: str) -> float:
		amount = self._money(base * (self._rate(rate_field) / 100), amount_field)
		self.set(amount_field, amount)
		return amount
