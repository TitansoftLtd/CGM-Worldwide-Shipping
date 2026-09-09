# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import UnitTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_upload_metadata import (
	stamp_row_attachment_metadata,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
	derive_permit_clearance_phase,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
	has_all_payable_permit_invoices,
	has_all_permit_invoices,
	payable_permit_rows,
	permit_finance_rows,
)
from cgm_shipping.cgm_worldwide_shipping.doctype.permit_register.permit_register import (
	permit_requires_payment,
	permit_row_ready_for_application,
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


class TestPermitOriginPaymentRules(UnitTestCase):
	def test_local_requires_payment(self):
		self.assertTrue(permit_requires_payment(frappe._dict(origin="Local")))
		self.assertTrue(permit_requires_payment(frappe._dict(origin="")))
		self.assertTrue(permit_requires_payment(frappe._dict()))

	def test_foreign_skips_payment(self):
		self.assertFalse(permit_requires_payment(frappe._dict(origin="Foreign")))

	def test_local_ready_needs_invoice(self):
		row = frappe._dict(permit_type="KEBS", origin="Local", payment_invoice="")
		self.assertFalse(permit_row_ready_for_application(row))
		row.payment_invoice = "/files/inv.pdf"
		self.assertTrue(permit_row_ready_for_application(row))

	def test_foreign_ready_needs_certificate_only(self):
		row = frappe._dict(permit_type="KEBS", origin="Foreign", permit_document="")
		self.assertFalse(permit_row_ready_for_application(row))
		row.permit_document = "/files/cert.pdf"
		self.assertTrue(permit_row_ready_for_application(row))

	def test_foreign_certificate_is_post_cleared(self):
		row = frappe._dict(origin="Foreign", permit_document="/files/kebs.pdf")
		self.assertEqual(derive_permit_clearance_phase(row), "Post-Cleared")

	def test_foreign_without_certificate_not_started(self):
		row = frappe._dict(origin="Foreign", permit_document="")
		self.assertEqual(derive_permit_clearance_phase(row), "Not Started")

	def test_local_invoice_is_pre_cleared(self):
		row = frappe._dict(origin="Local", payment_invoice="/files/inv.pdf")
		self.assertEqual(derive_permit_clearance_phase(row), "Pre-Cleared")

	def test_has_all_permit_invoices_mixed_rows(self):
		task = frappe._dict(
			custom_task_permits=[
				frappe._dict(
					permit_type="KEBS",
					origin="Foreign",
					permit_document="/files/kebs.pdf",
				),
				frappe._dict(
					permit_type="ACA",
					origin="Local",
					payment_invoice="/files/aca.pdf",
				),
			]
		)
		self.assertTrue(has_all_permit_invoices(task))
		self.assertEqual(len(payable_permit_rows(task)), 1)
		self.assertEqual(payable_permit_rows(task)[0].permit_type, "ACA")
		self.assertTrue(has_all_payable_permit_invoices(task))

	def test_all_foreign_rows_ready_without_invoices(self):
		task = frappe._dict(
			custom_task_permits=[
				frappe._dict(
					permit_type="KEBS",
					origin="Foreign",
					permit_document="/files/kebs.pdf",
				),
			]
		)
		self.assertTrue(has_all_permit_invoices(task))
		self.assertEqual(payable_permit_rows(task), [])
		self.assertFalse(has_all_payable_permit_invoices(task))
		self.assertEqual(permit_finance_rows(task), [])

	def test_local_without_invoice_not_ready(self):
		task = frappe._dict(
			custom_task_permits=[
				frappe._dict(permit_type="KEBS", origin="Local", payment_invoice=""),
			]
		)
		self.assertFalse(has_all_permit_invoices(task))
