# """Quotation import-cost and customs tax calculations."""

# from __future__ import annotations

# import frappe
# from erpnext import get_company_currency
# from erpnext.selling.doctype.quotation.quotation import Quotation
# from erpnext.setup.utils import get_exchange_rate
# from frappe.utils import flt, round_based_on_smallest_currency_fraction

# IMPORT_COST_TABLE = "custom_import_cost_component"
# CUSTOMS_TAX_TABLE = "custom_customs_taxes"
# USD_CURRENCY = "USD"

# DEFAULT_RATE_TAX_TYPES = frozenset({"VAT", "IDF", "RDL"})
# MANUAL_RATE_TAX_TYPES = frozenset({"Duty", "Excise Duty"})
# FIXED_AMOUNT_TAX_TYPES = frozenset({"MSS Levy"})


# class CGMQuotation(Quotation):
# 	def validate(self):
# 		super().validate()
# 		self._calculate_import_customs_taxes()

# 	def _calculate_import_customs_taxes(self):
# 		if not self.meta.has_field(IMPORT_COST_TABLE):
# 			return

# 		company_currency = get_company_currency(self.company)
# 		rows = self.get(IMPORT_COST_TABLE) or []

# 		customs_value_kes = 0.0

# 		for row in rows:
# 			self._normalize_import_cost_row(row, company_currency)
# 			row.amount_kes = self._amount_in_kes(row, company_currency)
# 			customs_value_kes += flt(row.amount_kes)

# 		customs_value_kes = self._money(customs_value_kes, "custom_customs_value_kes")
# 		customs_value_usd = self._money(
# 			self._calculate_customs_value_usd(rows, company_currency),
# 			"custom_customs_value_usd",
# 		)
# 		self.custom_customs_value_kes = customs_value_kes
# 		self.custom_customs_value_usd = customs_value_usd

# 		if not self.meta.has_field(CUSTOMS_TAX_TABLE):
# 			return

# 		usd_to_kes_rate = self._get_usd_to_kes_rate(rows, company_currency)
# 		total_taxes_kes = 0.0
# 		total_taxes_usd = 0.0
# 		seen_tax_types: set[str] = set()

# 		for tax_row in self.get(CUSTOMS_TAX_TABLE) or []:
# 			tax_type = tax_row.tax_type
# 			if not tax_type:
# 				continue
# 			if tax_type in seen_tax_types:
# 				frappe.throw(
# 					frappe._("Duplicate customs tax type {0} is not allowed.").format(tax_type)
# 				)
# 			seen_tax_types.add(tax_type)

# 			calculation_type = frappe.db.get_value(
# 				"Customs Tax Type", tax_type, "calculation_type"
# 			)
# 			if calculation_type == "Fixed Amount":
# 				amount_kes = self._money(flt(tax_row.fixed_amount_kes), "amount_kes", tax_row)
# 			else:
# 				amount_kes = self._money(
# 					customs_value_kes * (flt(tax_row.rate) / 100),
# 					"amount_kes",
# 					tax_row,
# 				)

# 			amount_usd = self._money(
# 				flt(amount_kes / usd_to_kes_rate) if usd_to_kes_rate else 0.0,
# 				"amount_usd",
# 				tax_row,
# 			)
# 			tax_row.amount_kes = amount_kes
# 			tax_row.amount_usd = amount_usd
# 			total_taxes_kes += flt(amount_kes)
# 			total_taxes_usd += flt(amount_usd)

# 		total_taxes_kes = self._money(total_taxes_kes, "custom_total_taxes_kes")
# 		total_taxes_usd = self._money(total_taxes_usd, "custom_total_taxes_usd")
# 		self.custom_total_taxes_kes = total_taxes_kes
# 		if self.meta.has_field("custom_total_taxes_usd"):
# 			self.custom_total_taxes_usd = total_taxes_usd
# 		self._apply_customs_to_standard_totals(total_taxes_kes)

# 	def _apply_customs_to_standard_totals(self, total_taxes_kes: float) -> None:
# 		"""Reflect import/customs taxes in ERPNext standard total fields."""
# 		customs_taxes = self._customs_taxes_in_doc_currency(total_taxes_kes)
# 		if not customs_taxes:
# 			return

# 		self.total_taxes_and_charges = self._money(
# 			flt(self.total_taxes_and_charges) + customs_taxes,
# 			"total_taxes_and_charges",
# 		)
# 		self.base_total_taxes_and_charges = self._money(
# 			flt(self.base_total_taxes_and_charges) + flt(total_taxes_kes),
# 			"base_total_taxes_and_charges",
# 		)
# 		self.grand_total = self._money(
# 			flt(self.net_total) + flt(self.total_taxes_and_charges),
# 			"grand_total",
# 		)
# 		self.base_grand_total = self._money(
# 			flt(self.grand_total) * flt(self.conversion_rate),
# 			"base_grand_total",
# 		)
# 		self._set_rounded_totals()
# 		self.set_total_in_words()

# 	def _customs_taxes_in_doc_currency(self, total_taxes_kes: float) -> float:
# 		company_currency = get_company_currency(self.company)
# 		if self.currency == company_currency:
# 			return flt(total_taxes_kes)

# 		conversion_rate = flt(self.conversion_rate)
# 		if not conversion_rate:
# 			return 0.0

# 		return flt(
# 			total_taxes_kes / conversion_rate,
# 			self.precision("total_taxes_and_charges"),
# 		)

# 	def _set_rounded_totals(self) -> None:
# 		if self.is_rounded_total_disabled():
# 			self.rounded_total = 0.0
# 			self.rounding_adjustment = 0.0
# 			self.base_rounded_total = 0.0
# 			self.base_rounding_adjustment = 0.0
# 			return

# 		self.rounded_total = round_based_on_smallest_currency_fraction(
# 			self.grand_total,
# 			self.currency,
# 			self.precision("rounded_total"),
# 		)
# 		self.rounding_adjustment = self._money(
# 			self.rounded_total - self.grand_total,
# 			"rounding_adjustment",
# 		)
# 		self.base_rounded_total = self._money(
# 			self.rounded_total * flt(self.conversion_rate),
# 			"base_rounded_total",
# 		)
# 		self.base_rounding_adjustment = self._money(
# 			self.base_rounded_total - self.base_grand_total,
# 			"base_rounding_adjustment",
# 		)

# 	def _normalize_import_cost_row(self, row, company_currency: str) -> None:
# 		if row.currency == company_currency:
# 			row.exchange_rate = 1

# 	def _amount_in_kes(self, row, company_currency: str) -> float:
# 		amount = flt(row.amount)
# 		if row.currency == company_currency:
# 			return amount

# 		return flt(amount * flt(row.exchange_rate), row.precision("amount_kes"))

# 	def _calculate_customs_value_usd(self, rows, company_currency: str) -> float:
# 		"""Sum USD rows directly; sum KES (and other foreign) in KES, then convert once to USD."""
# 		usd_total = 0.0
# 		kes_total = 0.0

# 		for row in rows:
# 			currency = row.currency
# 			amount = flt(row.amount)

# 			if currency == USD_CURRENCY:
# 				usd_total += amount
# 			elif currency == company_currency:
# 				kes_total += amount
# 			else:
# 				kes_total += flt(row.amount_kes)

# 		usd_to_kes_rate = self._get_usd_to_kes_rate(rows, company_currency)
# 		kes_in_usd = flt(kes_total / usd_to_kes_rate) if usd_to_kes_rate else 0.0

# 		return usd_total + kes_in_usd

# 	def _get_usd_to_kes_rate(self, rows, company_currency: str) -> float:
# 		"""KES per 1 USD from USD import-cost rows, else ERPNext exchange rate."""
# 		for row in rows:
# 			if row.currency == USD_CURRENCY and flt(row.exchange_rate):
# 				return flt(row.exchange_rate)

# 		return flt(get_exchange_rate(USD_CURRENCY, company_currency, self.transaction_date) or 0)

# 	def _money(self, value, fieldname: str, row=None) -> float:
# 		if row is not None:
# 			return flt(value, row.precision(fieldname))
# 		return flt(value, self.precision(fieldname))


# @frappe.whitelist()
# def get_customs_tax_type_info(tax_type: str) -> dict:
# 	"""Return calculation type and default rate for a customs tax row."""
# 	if not tax_type:
# 		return {}

# 	calculation_type = frappe.db.get_value("Customs Tax Type", tax_type, "calculation_type")
# 	default_rate = None

# 	if tax_type in DEFAULT_RATE_TAX_TYPES:
# 		default_rate = frappe.db.get_value(
# 			"Default Customs Tax",
# 			{"parent": "CGM Shipping Settings", "parenttype": "CGM Shipping Settings", "tax_type": tax_type},
# 			"default_rate",
# 		)

# 	return {
# 		"calculation_type": calculation_type,
# 		"default_rate": default_rate,
# 		"uses_default_rate": tax_type in DEFAULT_RATE_TAX_TYPES,
# 		"uses_manual_rate": tax_type in MANUAL_RATE_TAX_TYPES,
# 		"uses_fixed_amount": tax_type in FIXED_AMOUNT_TAX_TYPES
# 		or calculation_type == "Fixed Amount",
# 	}
