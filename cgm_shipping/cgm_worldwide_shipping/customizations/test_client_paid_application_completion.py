# Copyright (c) 2026, Titansoft Limited and contributors

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
	APPLICATION_FINANCE_PROFILES,
	can_complete_application_finance_task,
	can_complete_application_task,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
	can_complete_ucr_create_task,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
	validate_application_not_manually_completed,
)


class TestClientPaidApplicationCompletion(unittest.TestCase):
	def _task(self, seq=12):
		return frappe._dict(
			custom_sequence_no=seq,
			project="PROJ-1",
			status="Open",
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.client_paid_settlement_ready",
		return_value=False,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_client_paid_directly",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.is_application_finance_task",
		return_value=True,
	)
	def test_finance_task_does_not_complete_from_confirmation_alone(self, *_mocks):
		profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
		self.assertFalse(
			can_complete_application_finance_task(self._task(13), profile)
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.client_paid_settlement_ready",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_client_paid_directly",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.is_application_finance_task",
		return_value=True,
	)
	def test_finance_task_completes_when_client_settlement_ready(self, *_mocks):
		profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
		self.assertTrue(
			can_complete_application_finance_task(self._task(13), profile)
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_has_recorded_payment",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.invoice_verified",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.project_has_submitted_invoice",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_client_paid_directly",
		return_value=False,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.is_application_finance_task",
		return_value=True,
	)
	def test_entry_finance_completes_without_receipt_when_company_paid(self, *_mocks):
		profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
		self.assertTrue(
			can_complete_application_finance_task(self._task(13), profile)
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_client_paid_directly",
		return_value=False,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.project_has_submitted_invoice",
		return_value=False,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.is_application_finance_task",
		return_value=True,
	)
	def test_normal_finance_path_still_requires_invoice_handoff(self, *_mocks):
		profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
		self.assertFalse(
			can_complete_application_finance_task(self._task(13), profile)
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.invoice_verified_for_application_task",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.invoice_attached",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_client_paid_directly",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.certificate_uploaded",
		return_value=False,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.is_application_task",
		return_value=True,
	)
	def test_entry_completes_when_invoice_verified_without_certificate(self, *_mocks):
		profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
		finance_task = frappe._dict(custom_client_paid_directly=1)
		self.assertTrue(
			can_complete_application_task(self._task(), profile, finance_task)
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.invoice_verified_for_application_task",
		return_value=False,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.invoice_attached",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_client_paid_directly",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.is_application_task",
		return_value=True,
	)
	def test_entry_stays_open_until_invoice_verified(self, *_mocks):
		profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
		finance_task = frappe._dict(custom_client_paid_directly=1)
		self.assertFalse(
			can_complete_application_task(self._task(), profile, finance_task)
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.invoice_verified_for_application_task",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.invoice_attached",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_client_paid_directly",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.is_application_task",
		return_value=True,
	)
	def test_no_certificate_profile_does_not_auto_complete(self, *_mocks):
		profile = APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
		finance_task = frappe._dict(custom_client_paid_directly=1)
		self.assertFalse(
			can_complete_application_task(self._task(10), profile, finance_task)
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.ucr_invoice_verified_for_create_task",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.ucr_invoice_attached",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_client_paid_directly",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.idf_certificate_uploaded",
		return_value=False,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.is_ucr_create_task",
		return_value=True,
	)
	def test_ucr_stays_open_until_idf_certificate_attached(self, *_mocks):
		finance_task = frappe._dict(custom_client_paid_directly=1)
		self.assertFalse(
			can_complete_ucr_create_task(self._task(3), finance_task)
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.ucr_invoice_verified_for_create_task",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.ucr_invoice_attached",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_client_paid_directly",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.idf_certificate_uploaded",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.is_ucr_create_task",
		return_value=True,
	)
	def test_ucr_completes_after_idf_certificate_attached(self, *_mocks):
		finance_task = frappe._dict(custom_client_paid_directly=1)
		self.assertTrue(
			can_complete_ucr_create_task(self._task(3), finance_task)
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.client_paid_settlement_ready",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_client_paid_directly",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.is_application_finance_task",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.pop_attached",
		return_value=False,
	)
	def test_shipping_line_needs_pop_even_when_client_settled(self, *_mocks):
		profile = APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
		self.assertTrue(profile.requires_pop)
		self.assertFalse(
			can_complete_application_finance_task(self._task(11), profile)
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.client_paid_settlement_ready",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_client_paid_directly",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.is_application_finance_task",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.pop_attached",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.receipt_attached_for_payment_workflow",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.receipt_verified",
		return_value=True,
	)
	def test_shipping_line_completes_with_pop_and_verified_receipt(self, *_mocks):
		profile = APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
		self.assertTrue(
			can_complete_application_finance_task(self._task(11), profile)
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.can_complete_application_task",
		return_value=False,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.is_application_create_task",
		return_value=True,
	)
	def test_shipping_line_blocks_manual_complete_before_receipt_verify(self, *_mocks):
		profile = APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
		task = self._task(10)
		task.status = "Completed"
		with self.assertRaises(frappe.ValidationError):
			validate_application_not_manually_completed(task, profile)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.invoice_verified_for_application_task",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.invoice_attached",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.pop_attached",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.receipt_verified",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.is_application_task",
		return_value=True,
	)
	def test_shipping_line_application_completes_after_receipt_verified(self, *_mocks):
		profile = APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
		finance_task = frappe._dict(custom_client_paid_directly=0)
		self.assertTrue(
			can_complete_application_task(self._task(10), profile, finance_task)
		)
