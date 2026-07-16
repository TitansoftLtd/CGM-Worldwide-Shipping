# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.item_pricing import (
	CALCULATION_FIXED,
	CALCULATION_PERCENTAGE,
	calculate_item_pricing_for_item,
	calculate_rule_amount,
)


class TestItemPricing(IntegrationTestCase):
	def setUp(self):
		self.company = frappe.defaults.get_global_default("company") or frappe.db.get_single_value(
			"Global Defaults", "default_company"
		)
		self.company_currency = frappe.db.get_value("Company", self.company, "default_currency")

	def _amount(self, rule: dict, custom_value: float, **kwargs):
		defaults = {
			"quotation_currency": "USD",
			"company_currency": self.company_currency,
			"conversion_rate": 130.0,
		}
		defaults.update(kwargs)
		return calculate_rule_amount(custom_value, rule, **defaults)

	def _item(self, rules: list[dict], custom_value: float, **kwargs):
		defaults = {
			"quotation_currency": "USD",
			"company_currency": self.company_currency,
			"conversion_rate": 130.0,
		}
		defaults.update(kwargs)
		return calculate_item_pricing_for_item(custom_value, rules, **defaults)

	def test_percentage_rule(self):
		amount = self._amount(
			{
				"currency": "USD",
				"calculation_type": CALCULATION_PERCENTAGE,
				"percentage_rate": 5,
				"fixed_rate": 0,
			},
			409_909.70,
		)
		self.assertEqual(amount, 20_495.485)

	def test_fixed_rate_in_quotation_currency(self):
		amount = self._amount(
			{
				"currency": "USD",
				"calculation_type": CALCULATION_FIXED,
				"percentage_rate": 0,
				"fixed_rate": 300,
			},
			50_000,
		)
		self.assertEqual(amount, 300)

	def test_fixed_rate_in_company_currency(self):
		amount = self._amount(
			{
				"currency": self.company_currency,
				"calculation_type": CALCULATION_FIXED,
				"percentage_rate": 0,
				"fixed_rate": 39_000,
			},
			50_000,
			quotation_currency="USD",
			conversion_rate=130.0,
		)
		self.assertEqual(amount, 300)

	def test_multi_rule_selects_highest_amount(self):
		rules = [
			{
				"currency": "USD",
				"calculation_type": CALCULATION_PERCENTAGE,
				"percentage_rate": 5,
				"fixed_rate": 0,
			},
			{
				"currency": "USD",
				"calculation_type": CALCULATION_PERCENTAGE,
				"percentage_rate": 0.6,
				"fixed_rate": 0,
			},
			{
				"currency": "USD",
				"calculation_type": CALCULATION_FIXED,
				"percentage_rate": 0,
				"fixed_rate": 300,
			},
		]

		audit_row, winning_rate = self._item(rules, 90_000)

		self.assertEqual(winning_rate, 4_500)
		self.assertIsNotNone(audit_row)
		self.assertEqual(audit_row["rule_type"], CALCULATION_PERCENTAGE)
		self.assertEqual(audit_row["calculated_amount"], 4_500)
		self.assertEqual(audit_row["final_applied_rate"], 4_500)
		self.assertEqual(audit_row["exchange_rate_used"], 130.0)

	def test_fixed_rule_wins_over_percentage(self):
		rules = [
			{
				"currency": "USD",
				"calculation_type": CALCULATION_PERCENTAGE,
				"percentage_rate": 1,
				"fixed_rate": 0,
			},
			{
				"currency": "USD",
				"calculation_type": CALCULATION_FIXED,
				"percentage_rate": 0,
				"fixed_rate": 500,
			},
		]

		audit_row, winning_rate = self._item(rules, 10_000)

		self.assertEqual(winning_rate, 500)
		self.assertEqual(audit_row["rule_type"], "Fixed Rate")

	def test_zero_customs_value_still_returns_rule_row(self):
		"""Item Pricing table must show a row even before customs value is set."""
		rules = [
			{
				"currency": "USD",
				"calculation_type": CALCULATION_PERCENTAGE,
				"percentage_rate": 5,
				"fixed_rate": 0,
			},
			{
				"currency": "USD",
				"calculation_type": CALCULATION_FIXED,
				"percentage_rate": 0,
				"fixed_rate": 300,
				"fx_to_quotation": 130,
			},
		]

		audit_row, winning_rate = self._item(rules, 0, quotation_currency="KES")

		self.assertIsNotNone(audit_row)
		self.assertEqual(winning_rate, 39_000)
		self.assertEqual(audit_row["rule_type"], "Fixed Rate")
