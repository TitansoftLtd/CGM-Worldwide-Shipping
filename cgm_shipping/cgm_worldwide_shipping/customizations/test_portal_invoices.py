# Copyright (c) 2026, Titansoft Limited and contributors

import unittest

from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
	invoice_outstanding_in_invoice_currency,
	outstanding_totals_by_currency,
)


class TestPortalInvoiceCurrency(unittest.TestCase):
	def test_outstanding_stays_when_currencies_match(self):
		row = {
			"outstanding_amount": 8790,
			"currency": "KES",
			"party_account_currency": "KES",
			"conversion_rate": 1,
		}
		self.assertEqual(invoice_outstanding_in_invoice_currency(row), 8790)

	def test_outstanding_converts_from_party_account_currency(self):
		row = {
			"outstanding_amount": 371607.96,
			"currency": "USD",
			"party_account_currency": "KES",
			"conversion_rate": 129.21,
		}
		converted = invoice_outstanding_in_invoice_currency(row)
		self.assertAlmostEqual(converted, 2876.0, places=1)

	def test_outstanding_totals_group_by_invoice_currency(self):
		rows = [
			{"currency": "KES", "outstanding_in_currency": 500},
			{"currency": "USD", "outstanding_in_currency": 2876},
			{"currency": "KES", "outstanding_in_currency": 8790},
			{"currency": "USD", "outstanding_in_currency": 0},
		]
		totals = outstanding_totals_by_currency(rows)
		by_currency = {t["currency"]: t["amount"] for t in totals}
		self.assertEqual(by_currency["KES"], 9290)
		self.assertEqual(by_currency["USD"], 2876)
