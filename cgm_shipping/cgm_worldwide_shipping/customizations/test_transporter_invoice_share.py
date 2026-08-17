# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import MagicMock, patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share import (
	SHARE_FIELD,
	_assert_shared_invoice_for_transporter,
	get_transporter_invoice_summary,
	list_shared_purchase_invoices,
	purchase_invoice_portal_status,
	validate_share_with_transporter,
)


def _pi_doc(**kwargs):
	values = {
		"supplier": "TRANS-1",
		"is_return": 0,
		SHARE_FIELD: 0,
		"custom_supplier_is_transporter": 1,
		"custom_shared_with_transporter_on": None,
	}
	values.update(kwargs)
	doc = frappe._dict(values)
	doc.meta = frappe._dict(
		has_field=lambda field, *_a, **_k: field
		in {
			SHARE_FIELD,
			"custom_supplier_is_transporter",
			"custom_shared_with_transporter_on",
			"is_return",
		}
	)
	doc.set = lambda field, value: doc.update({field: value})
	doc.get = lambda field, default=None: doc[field] if field in doc else default
	return doc


class TestTransporterInvoiceShare(unittest.TestCase):
	def test_unpaid_status_is_owed(self):
		status = purchase_invoice_portal_status("Unpaid", 15000)
		self.assertFalse(status["is_paid"])
		self.assertEqual(status["tone"], "active")
		self.assertIn("Unpaid", status["label"])

	def test_paid_when_outstanding_is_zero(self):
		status = purchase_invoice_portal_status("Unpaid", 0)
		self.assertTrue(status["is_paid"])
		self.assertEqual(status["tone"], "success")

	def test_paid_status_wins(self):
		status = purchase_invoice_portal_status("Paid", 0)
		self.assertTrue(status["is_paid"])

	def test_partly_paid_still_owed(self):
		status = purchase_invoice_portal_status("Partly Paid", 4000)
		self.assertFalse(status["is_paid"])
		self.assertEqual(status["tone"], "active")

	def test_overdue_tone(self):
		status = purchase_invoice_portal_status("Overdue", 8000)
		self.assertFalse(status["is_paid"])
		self.assertEqual(status["tone"], "danger")

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.supplier_is_transporter",
		return_value=False,
	)
	def test_cannot_share_non_transporter(self, _mock_is_transporter):
		doc = _pi_doc(custom_supplier_is_transporter=0, **{SHARE_FIELD: 1})
		with self.assertRaises(frappe.ValidationError):
			validate_share_with_transporter(doc)

	def test_cannot_share_return_invoice(self):
		doc = _pi_doc(is_return=1, **{SHARE_FIELD: 1})
		with self.assertRaises(frappe.ValidationError):
			validate_share_with_transporter(doc)

	def test_stamps_shared_on_when_checked(self):
		doc = _pi_doc(**{SHARE_FIELD: 1})
		validate_share_with_transporter(doc)
		self.assertTrue(doc.custom_shared_with_transporter_on)

	def test_clears_shared_on_when_unchecked(self):
		doc = _pi_doc(
			**{SHARE_FIELD: 0},
			custom_shared_with_transporter_on="2026-08-01 10:00:00",
		)
		validate_share_with_transporter(doc)
		self.assertIsNone(doc.custom_shared_with_transporter_on)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.frappe.db.exists",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.frappe.get_meta"
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.frappe.get_all"
	)
	def test_listing_only_shared_invoices(self, mock_get_all, mock_get_meta, _exists):
		mock_get_meta.return_value = MagicMock(
			has_field=lambda field: field in (SHARE_FIELD, "is_return")
		)
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "PINV-0001",
					"posting_date": "2026-08-01",
					"due_date": "2026-08-15",
					"status": "Unpaid",
					"grand_total": 20000,
					"outstanding_amount": 20000,
					"currency": "KES",
					"bill_no": "T-1",
					"project": None,
					"supplier_name": "Acme Transport",
				}
			)
		]
		rows = list_shared_purchase_invoices("TRANS-1")
		filters = mock_get_all.call_args.kwargs["filters"]
		self.assertEqual(filters["supplier"], "TRANS-1")
		self.assertEqual(filters["docstatus"], 1)
		self.assertEqual(filters[SHARE_FIELD], 1)
		self.assertEqual(filters["is_return"], 0)
		self.assertEqual(len(rows), 1)
		self.assertFalse(rows[0]["is_paid"])
		self.assertEqual(rows[0]["outstanding_amount"], 20000)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.frappe.db.exists",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.frappe.get_meta"
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.frappe.get_all"
	)
	def test_paid_invoice_shows_as_paid(self, mock_get_all, mock_get_meta, _exists):
		mock_get_meta.return_value = MagicMock(
			has_field=lambda field: field in (SHARE_FIELD, "is_return")
		)
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "PINV-0002",
					"posting_date": "2026-08-01",
					"due_date": "2026-08-15",
					"status": "Paid",
					"grand_total": 20000,
					"outstanding_amount": 0,
					"currency": "KES",
					"bill_no": "",
					"project": None,
					"supplier_name": "Acme Transport",
				}
			)
		]
		summary = get_transporter_invoice_summary("TRANS-1")
		self.assertEqual(summary["stat_paid_count"], 1)
		self.assertEqual(summary["stat_outstanding_count"], 0)
		self.assertEqual(summary["stat_outstanding_amount"], 0)
		self.assertTrue(summary["invoices"][0]["is_paid"])

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.frappe.db.exists",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.frappe.get_meta"
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.frappe.db.get_value"
	)
	def test_unshared_invoice_is_not_downloadable(self, mock_get_value, mock_get_meta, _exists):
		mock_get_meta.return_value = MagicMock(has_field=lambda field: True)
		mock_get_value.return_value = frappe._dict(
			name="PINV-0003",
			supplier="TRANS-1",
			docstatus=1,
			**{SHARE_FIELD: 0},
			is_return=0,
		)
		with self.assertRaises(frappe.PermissionError):
			_assert_shared_invoice_for_transporter("PINV-0003", "TRANS-1")

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.frappe.db.exists",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.frappe.get_meta"
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.frappe.db.get_value"
	)
	def test_other_transporter_cannot_access(self, mock_get_value, mock_get_meta, _exists):
		mock_get_meta.return_value = MagicMock(has_field=lambda field: True)
		mock_get_value.return_value = frappe._dict(
			name="PINV-0004",
			supplier="TRANS-OTHER",
			docstatus=1,
			**{SHARE_FIELD: 1},
			is_return=0,
		)
		with self.assertRaises(frappe.PermissionError):
			_assert_shared_invoice_for_transporter("PINV-0004", "TRANS-1")
