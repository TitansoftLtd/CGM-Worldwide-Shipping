# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.item_pricing import (
	CALCULATION_FIXED,
	CALCULATION_PERCENTAGE,
	calculate_item_pricing_for_item,
	calculate_item_pricing_row,
)


class TestItemPricing(IntegrationTestCase):
	def setUp(self):
		self.company = frappe.defaults.get_global_default("company") or frappe.db.get_single_value(
			"Global Defaults", "default_company"
		)

	def _row(self, rule: dict, custom_value: float, **kwargs):
		defaults = {
			"company": self.company,
			"quotation_currency": "USD",
			"conversion_rate": 130.0,
			"transaction_date": "2026-06-26",
		}
		defaults.update(kwargs)
		return calculate_item_pricing_row(custom_value, rule, **defaults)

	def _item(self, rules: list[dict], custom_value: float, **kwargs):
		defaults = {
			"company": self.company,
			"quotation_currency": "USD",
			"conversion_rate": 130.0,
			"transaction_date": "2026-06-26",
		}
		defaults.update(kwargs)
		return calculate_item_pricing_for_item(custom_value, rules, **defaults)

	def test_percentage_above_floor(self):
		"""Computed amount exceeds floor — candidate equals computed."""
		result = self._row(
			{
				"currency": "USD",
				"calculation_type": CALCULATION_PERCENTAGE,
				"percentage_rate": 5,
				"fixed_rate": 0,
				"floor_rate": 300,
			},
			409_909.70,
		)

		self.assertEqual(result["computed_amount"], 20_495.485)
		self.assertEqual(result["candidate_amount"], 20_495.485)
		self.assertEqual(result["company_amount"], 20_495.485 * 130.0)

	def test_percentage_below_floor(self):
		"""Floor rate is used when computed amount is lower."""
		result = self._row(
			{
				"currency": "USD",
				"calculation_type": CALCULATION_PERCENTAGE,
				"percentage_rate": 5,
				"fixed_rate": 0,
				"floor_rate": 300,
			},
			2_000,
		)

		self.assertEqual(result["computed_amount"], 100)
		self.assertEqual(result["candidate_amount"], 300)
		self.assertEqual(result["company_amount"], 300 * 130.0)

	def test_fixed_rate(self):
		"""Fixed rate ignores percentage."""
		result = self._row(
			{
				"currency": "EUR",
				"calculation_type": CALCULATION_FIXED,
				"percentage_rate": 99,
				"fixed_rate": 20,
				"floor_rate": 0,
			},
			50_000,
			quotation_currency="EUR",
			conversion_rate=145.0,
		)

		self.assertEqual(result["computed_amount"], 0)
		self.assertEqual(result["candidate_amount"], 20)
		self.assertEqual(result["company_amount"], 20 * 145.0)

	def test_fixed_rate_cross_currency_quotation(self):
		"""Fixed EUR rule with KES quotation uses ERPNext exchange lookup."""
		result = calculate_item_pricing_row(
			50_000,
			{
				"currency": "EUR",
				"calculation_type": CALCULATION_FIXED,
				"percentage_rate": 0,
				"fixed_rate": 20,
				"floor_rate": 0,
			},
			company=self.company,
			quotation_currency="KES",
			conversion_rate=1,
			transaction_date="2026-06-26",
		)

		self.assertEqual(result["candidate_amount"], 20)
		self.assertGreaterEqual(result["company_amount"], 0)

	def test_multi_rule_selects_highest_candidate(self):
		"""All active rules are evaluated; highest candidate wins."""
		rules = [
			{
				"currency": "USD",
				"calculation_type": CALCULATION_PERCENTAGE,
				"percentage_rate": 5,
				"fixed_rate": 0,
				"floor_rate": 300,
			},
			{
				"currency": "USD",
				"calculation_type": CALCULATION_PERCENTAGE,
				"percentage_rate": 0.6,
				"fixed_rate": 0,
				"floor_rate": 300,
			},
			{
				"currency": "USD",
				"calculation_type": CALCULATION_FIXED,
				"percentage_rate": 0,
				"fixed_rate": 300,
				"floor_rate": 0,
			},
		]

		pricing_rows, winning_rate = self._item(rules, 90_000)

		self.assertEqual(winning_rate, 4_500)
		self.assertEqual(len(pricing_rows), 3)
		self.assertEqual(sum(row["winning_rule"] for row in pricing_rows), 1)
		self.assertEqual(pricing_rows[0]["candidate_amount"], 4_500)
		self.assertEqual(pricing_rows[0]["winning_rule"], 1)

	def test_multi_rule_all_floor_bound(self):
		"""When every candidate hits the floor, the floor amount wins."""
		rules = [
			{
				"currency": "USD",
				"calculation_type": CALCULATION_PERCENTAGE,
				"percentage_rate": 5,
				"fixed_rate": 0,
				"floor_rate": 300,
			},
			{
				"currency": "USD",
				"calculation_type": CALCULATION_PERCENTAGE,
				"percentage_rate": 0.6,
				"fixed_rate": 0,
				"floor_rate": 300,
			},
			{
				"currency": "USD",
				"calculation_type": CALCULATION_FIXED,
				"percentage_rate": 0,
				"fixed_rate": 300,
				"floor_rate": 0,
			},
		]

		pricing_rows, winning_rate = self._item(rules, 2_000)

		self.assertEqual(winning_rate, 300)
		self.assertTrue(all(row["candidate_amount"] == 300 for row in pricing_rows))
		self.assertEqual(sum(row["winning_rule"] for row in pricing_rows), 3)
