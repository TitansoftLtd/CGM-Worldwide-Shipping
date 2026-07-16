# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import UnitTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_upload_metadata import (
	stamp_row_attachment_metadata,
)


class TestPermitRegisterUploadMetadata(UnitTestCase):
	def _stamp(self, row, prev_row=None, **kwargs):
		defaults = {
			"attach_field": "permit_document",
			"on_field": "certificate_uploaded_on",
			"by_field": "certificate_uploaded_by",
		}
		defaults.update(kwargs)
		stamp_row_attachment_metadata(row, prev_row, **defaults)

	def test_new_certificate_upload_sets_metadata(self):
		row = frappe._dict(permit_document="/files/permit.pdf")
		self._stamp(row)
		self.assertEqual(row.certificate_uploaded_by, "Administrator")
		self.assertIsNotNone(row.certificate_uploaded_on)

	def test_unchanged_certificate_keeps_metadata(self):
		row = frappe._dict(
			permit_document="/files/permit.pdf",
			certificate_uploaded_by="user@example.com",
			certificate_uploaded_on="2026-01-01 10:00:00",
		)
		prev = frappe._dict(permit_document="/files/permit.pdf")
		self._stamp(row, prev)
		self.assertEqual(row.certificate_uploaded_by, "user@example.com")
		self.assertEqual(row.certificate_uploaded_on, "2026-01-01 10:00:00")

	def test_replaced_certificate_refreshes_metadata(self):
		row = frappe._dict(
			permit_document="/files/permit-v2.pdf",
			certificate_uploaded_by="user@example.com",
			certificate_uploaded_on="2026-01-01 10:00:00",
		)
		prev = frappe._dict(permit_document="/files/permit.pdf")
		self._stamp(row, prev)
		self.assertEqual(row.certificate_uploaded_by, "Administrator")
		self.assertNotEqual(row.certificate_uploaded_on, "2026-01-01 10:00:00")

	def test_removed_certificate_clears_metadata(self):
		row = frappe._dict(
			permit_document="",
			certificate_uploaded_by="user@example.com",
			certificate_uploaded_on="2026-01-01 10:00:00",
		)
		prev = frappe._dict(permit_document="/files/permit.pdf")
		self._stamp(row, prev)
		self.assertIsNone(row.certificate_uploaded_by)
		self.assertIsNone(row.certificate_uploaded_on)

	def test_new_invoice_upload_sets_metadata(self):
		row = frappe._dict(payment_invoice="/files/invoice.pdf")
		self._stamp(
			row,
			attach_field="payment_invoice",
			on_field="invoice_uploaded_on",
			by_field="invoice_uploaded_by",
		)
		self.assertEqual(row.invoice_uploaded_by, "Administrator")
		self.assertIsNotNone(row.invoice_uploaded_on)

	def test_unchanged_invoice_keeps_metadata(self):
		row = frappe._dict(
			payment_invoice="/files/invoice.pdf",
			invoice_uploaded_by="user@example.com",
			invoice_uploaded_on="2026-01-01 10:00:00",
		)
		prev = frappe._dict(payment_invoice="/files/invoice.pdf")
		self._stamp(
			row,
			prev,
			attach_field="payment_invoice",
			on_field="invoice_uploaded_on",
			by_field="invoice_uploaded_by",
		)
		self.assertEqual(row.invoice_uploaded_by, "user@example.com")
		self.assertEqual(row.invoice_uploaded_on, "2026-01-01 10:00:00")

	def test_no_attachment_leaves_empty_metadata(self):
		row = frappe._dict(
			permit_document="",
			certificate_uploaded_by=None,
			certificate_uploaded_on=None,
		)
		self._stamp(row)
		self.assertIsNone(row.certificate_uploaded_by)
		self.assertIsNone(row.certificate_uploaded_on)
