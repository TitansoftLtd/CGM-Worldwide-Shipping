# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import UnitTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
	APPLICATION_FINANCE_PROFILES,
	can_complete_application_finance_task,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_FINANCE_FIELD
from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
	block_premature_finance_completion,
	finance_payment_task_ready_to_complete,
)


class _FinanceTaskStub(frappe._dict):
	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.meta = frappe._dict(has_field=lambda _f: True)
		self.name = kwargs.get("name", "TASK-TEST")
		self.is_new = lambda: False
		if TASK_FINANCE_FIELD not in self:
			self[TASK_FINANCE_FIELD] = []

	def append(self, fieldname, row):
		self.setdefault(fieldname, []).append(frappe._dict(row))


class TestEntryFinanceCompletion(UnitTestCase):
	def setUp(self):
		self.profile = APPLICATION_FINANCE_PROFILES["Entry Application"]

	def _entry_finance_task(self) -> _FinanceTaskStub:
		return _FinanceTaskStub(
			name="TASK-ENTRY-FIN",
			custom_task_role="Finance Payment",
			custom_payment_kind="ENTRY_SLIP",
			custom_sequence_no=8,
			status="Open",
		)

	def test_entry_finance_requires_receipt_verification(self):
		self.assertTrue(self.profile.requires_receipt_verification)

	def test_paid_invoice_without_receipt_cannot_complete(self):
		task = self._entry_finance_task()
		task.append(
			TASK_FINANCE_FIELD,
			{
				"line_type": "Invoice",
				"line_label": "Entry Slip Invoice",
				"attachment": "/files/entry-invoice.pdf",
				"verified": 1,
				"journal_entry": "ACC-JV-2026-00001",
			},
		)
		task.append(
			TASK_FINANCE_FIELD,
			{
				"line_type": "Receipt",
				"line_label": "Entry Slip Receipt",
				"attachment": None,
				"verified": 0,
			},
		)
		self.assertFalse(can_complete_application_finance_task(task, self.profile))
		self.assertFalse(finance_payment_task_ready_to_complete(task))

	def test_paid_invoice_with_verified_receipt_can_complete(self):
		task = self._entry_finance_task()
		task.append(
			TASK_FINANCE_FIELD,
			{
				"line_type": "Invoice",
				"line_label": "Entry Slip Invoice",
				"attachment": "/files/entry-invoice.pdf",
				"verified": 1,
				"journal_entry": "ACC-JV-2026-00001",
			},
		)
		task.append(
			TASK_FINANCE_FIELD,
			{
				"line_type": "Receipt",
				"line_label": "Entry Slip Receipt",
				"attachment": "/files/entry-receipt.pdf",
				"verified": 1,
			},
		)
		self.assertTrue(can_complete_application_finance_task(task, self.profile))
		self.assertTrue(finance_payment_task_ready_to_complete(task))

	def test_block_premature_finance_completion_reverts_stale_completed(self):
		task = self._entry_finance_task()
		task.status = "Completed"
		task.progress = 100
		task.append(
			TASK_FINANCE_FIELD,
			{
				"line_type": "Invoice",
				"line_label": "Entry Slip Invoice",
				"attachment": "/files/entry-invoice.pdf",
				"verified": 1,
				"journal_entry": "ACC-JV-2026-00001",
			},
		)
		task.append(
			TASK_FINANCE_FIELD,
			{
				"line_type": "Receipt",
				"line_label": "Entry Slip Receipt",
				"attachment": None,
				"verified": 0,
			},
		)
		block_premature_finance_completion(task)
		self.assertEqual(task.status, "Open")
		self.assertEqual(task.progress, 0)
