"""Documents a step needs are set on the CGM Task Template, not in code.

Clearing Required Document Types on Create UCR used to fall back to a hardcoded
IDF certificate, and general finance tasks demanded a SUP_INV document that no
Document Type carries, so they could never be completed.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import application_finance as af
from cgm_shipping.cgm_worldwide_shipping.customizations import task as task_module
from cgm_shipping.cgm_worldwide_shipping.customizations import task_behaviour

UCR = af.APPLICATION_FINANCE_PROFILES["UCR Application"]


def _task(documents=()):
	return frappe._dict(name="TASK-TEST", custom_task_documents=list(documents))


def _behaviour(from_template):
	return patch.object(
		task_behaviour, "get_task_behaviour", return_value=frappe._dict(from_template=from_template)
	)


def _required(names):
	return patch.object(task_module, "get_effective_required_document_types", return_value=list(names))


class TestApplicationCertificate(unittest.TestCase):
	def test_template_listing_documents_requires_them(self):
		with _required(["IDF CERT"]), _behaviour(True):
			self.assertTrue(af.application_certificate_required(_task(), UCR))
			self.assertEqual(af.application_certificate_label(_task(), UCR), "IDF CERT")

	def test_blank_template_field_requires_nothing(self):
		with _required([]), _behaviour(True):
			self.assertFalse(af.application_certificate_required(_task(), UCR))
			self.assertEqual(af.application_certificate_label(_task(), UCR), "")
			self.assertTrue(af.certificate_uploaded(_task(), UCR))

	def test_task_from_before_templates_keeps_the_idf_certificate(self):
		with _required([]), _behaviour(False):
			self.assertTrue(af.application_certificate_required(_task(), UCR))
			self.assertEqual(af.application_certificate_label(_task(), UCR), "IDF CERT certificate")
			self.assertFalse(af.certificate_uploaded(_task(), UCR))

	def test_create_ucr_uses_the_same_rule(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import workflow

		with _required([]), _behaviour(True):
			self.assertTrue(workflow.idf_certificate_uploaded(_task()))


class TestFinanceTaskHasNoSupplierInvoiceRule(unittest.TestCase):
	def test_paid_finance_task_completes_without_a_supplier_invoice(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import workflow

		task = _task()
		with (
			patch.object(workflow, "task_client_paid_directly", return_value=False),
			patch.object(workflow, "task_has_recorded_payment", return_value=True),
		):
			task_module.validate_finance_task(task)

	def test_unpaid_finance_task_is_still_blocked(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import workflow

		with (
			patch.object(workflow, "task_client_paid_directly", return_value=False),
			patch.object(workflow, "task_has_recorded_payment", return_value=False),
			self.assertRaises(frappe.ValidationError),
		):
			task_module.validate_finance_task(_task())
