# Copyright (c) 2026, Titansoft Limited and contributors

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	CLIENT_PAID_BY_FIELD,
	CLIENT_PAID_FIELD,
	CLIENT_PAID_ON_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
	sync_client_paid_to_application_task,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
	can_complete_finance_permit_task,
	task_has_recorded_payment,
)

TASK_MODULE = "cgm_shipping.cgm_worldwide_shipping.customizations.task"


class _Meta:
	def has_field(self, _fieldname):
		return True


class TestClientPaidMirror(unittest.TestCase):
	def _finance_task(self, paid=1):
		task = frappe._dict(
			name="TASK-FIN-1",
			project="PROJ-1",
			custom_sequence_no=6,
			**{
				CLIENT_PAID_FIELD: paid,
				CLIENT_PAID_BY_FIELD: "finance@example.com" if paid else None,
				CLIENT_PAID_ON_FIELD: "2026-07-30 17:49:30" if paid else None,
			},
		)
		task.meta = _Meta()
		return task

	@patch(f"{TASK_MODULE}.frappe.publish_realtime")
	@patch(f"{TASK_MODULE}.frappe.clear_document_cache")
	@patch(f"{TASK_MODULE}.frappe.db.set_value")
	@patch(f"{TASK_MODULE}.frappe.db.get_value", return_value={})
	@patch(f"{TASK_MODULE}.frappe.get_meta", return_value=_Meta())
	@patch(f"{TASK_MODULE}.paired_application_task_for_finance_task", return_value="TASK-APP-1")
	@patch(f"{TASK_MODULE}.is_sea_finance_payment_task", return_value=True)
	def test_confirmation_is_copied_to_application_task(
		self, _is_finance, _paired, _meta, _get_value, set_value, *_mocks
	):
		self.assertEqual(
			sync_client_paid_to_application_task(self._finance_task()), "TASK-APP-1"
		)
		_doctype, name, values = set_value.call_args.args
		self.assertEqual(name, "TASK-APP-1")
		self.assertEqual(values[CLIENT_PAID_FIELD], 1)
		self.assertEqual(values[CLIENT_PAID_BY_FIELD], "finance@example.com")

	@patch(f"{TASK_MODULE}.frappe.publish_realtime")
	@patch(f"{TASK_MODULE}.frappe.clear_document_cache")
	@patch(f"{TASK_MODULE}.frappe.db.set_value")
	@patch(
		f"{TASK_MODULE}.frappe.db.get_value",
		return_value={
			CLIENT_PAID_FIELD: 1,
			CLIENT_PAID_BY_FIELD: "finance@example.com",
			CLIENT_PAID_ON_FIELD: "2026-07-30 17:49:30",
		},
	)
	@patch(f"{TASK_MODULE}.frappe.get_meta", return_value=_Meta())
	@patch(f"{TASK_MODULE}.paired_application_task_for_finance_task", return_value="TASK-APP-1")
	@patch(f"{TASK_MODULE}.is_sea_finance_payment_task", return_value=True)
	def test_no_write_when_application_task_already_matches(
		self, _is_finance, _paired, _meta, _get_value, set_value, *_mocks
	):
		self.assertIsNone(sync_client_paid_to_application_task(self._finance_task()))
		set_value.assert_not_called()

	@patch(f"{TASK_MODULE}.frappe.publish_realtime")
	@patch(f"{TASK_MODULE}.frappe.clear_document_cache")
	@patch(f"{TASK_MODULE}.frappe.db.set_value")
	@patch(f"{TASK_MODULE}.frappe.db.get_value", return_value={CLIENT_PAID_FIELD: 1})
	@patch(f"{TASK_MODULE}.frappe.get_meta", return_value=_Meta())
	@patch(f"{TASK_MODULE}.paired_application_task_for_finance_task", return_value="TASK-APP-1")
	@patch(f"{TASK_MODULE}.is_sea_finance_payment_task", return_value=True)
	def test_unticking_clears_the_application_task(
		self, _is_finance, _paired, _meta, _get_value, set_value, *_mocks
	):
		sync_client_paid_to_application_task(self._finance_task(paid=0))
		_doctype, _name, values = set_value.call_args.args
		self.assertEqual(values[CLIENT_PAID_FIELD], 0)
		self.assertIsNone(values[CLIENT_PAID_BY_FIELD])

	@patch(f"{TASK_MODULE}.frappe.db.set_value")
	@patch(f"{TASK_MODULE}.is_sea_finance_payment_task", return_value=False)
	def test_application_tasks_do_not_push_their_mirrored_value_back(
		self, _is_finance, set_value
	):
		self.assertIsNone(sync_client_paid_to_application_task(self._finance_task()))
		set_value.assert_not_called()


class TestPermitClientPaid(unittest.TestCase):
	def _permit_finance_task(self, paid=1, rows=None):
		return frappe._dict(
			name="TASK-FIN-PERMIT",
			status="Open",
			custom_task_permits=rows or [],
			**{CLIENT_PAID_FIELD: paid},
		)

	def _permit_app_task(self, paid=1, rows=None):
		task = frappe._dict(
			name="TASK-APP-PERMIT",
			project="PROJ-1",
			status="Open",
			custom_sequence_no=5,
			custom_task_permits=rows or [],
			**{CLIENT_PAID_FIELD: paid},
		)
		task.meta = _Meta()
		return task

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.permit_finance_rows",
		return_value=[
			frappe._dict(
				permit_type="DVS",
				origin="Local",
				invoice_verified=1,
			)
		],
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.is_permit_finance_task_doc",
		return_value=True,
	)
	def test_permit_payment_is_satisfied_by_client_settlement(self, *_mocks):
		task = self._permit_finance_task()
		self.assertTrue(task_has_recorded_payment(task))
		self.assertTrue(can_complete_finance_permit_task(task))

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.permit_finance_rows",
		return_value=[frappe._dict(permit_type="DVS", origin="Local", invoice_verified=0)],
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.is_permit_finance_task_doc",
		return_value=True,
	)
	def test_client_pays_still_needs_invoice_verified(self, *_mocks):
		self.assertFalse(task_has_recorded_payment(self._permit_finance_task()))
		self.assertFalse(can_complete_finance_permit_task(self._permit_finance_task()))

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.permit_finance_rows",
		return_value=[
			frappe._dict(
				permit_type="DVS",
				origin="Local",
				invoice_verified=1,
				journal_entry="JE-1",
			)
		],
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.is_permit_finance_task_doc",
		return_value=True,
	)
	def test_company_pays_completes_with_je_without_receipt(self, *_mocks):
		task = self._permit_finance_task(paid=0)
		self.assertTrue(can_complete_finance_permit_task(task))

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.permit_finance_rows",
		return_value=[frappe._dict(permit_type="DVS", origin="Local")],
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.is_permit_finance_task_doc",
		return_value=True,
	)
	def test_permit_rows_still_need_journal_entries_without_confirmation(self, *_mocks):
		self.assertFalse(task_has_recorded_payment(self._permit_finance_task(paid=0)))

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.finance_payment_completed",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.is_permit_application_task",
		return_value=True,
	)
	def test_application_completes_with_certificate_when_client_paid(self, *_mocks):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			validate_permit_application_can_complete,
		)

		rows = [
			frappe._dict(
				permit_type="DVS",
				origin="Local",
				payment_invoice="inv.pdf",
				permit_document="cert.pdf",
			)
		]
		task = self._permit_app_task(rows=rows)
		task.custom_permit_invoices_submitted = 1
		validate_permit_application_can_complete(task)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.is_permit_application_task",
		return_value=True,
	)
	def test_application_completes_with_no_rows_when_client_paid(self, _is_app):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			validate_permit_application_can_complete,
		)

		validate_permit_application_can_complete(self._permit_app_task(rows=[]))

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.finance_payment_completed",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.is_permit_application_task",
		return_value=True,
	)
	def test_application_still_needs_certificate_when_client_paid(self, *_mocks):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			validate_permit_application_can_complete,
		)

		rows = [
			frappe._dict(
				permit_type="DVS",
				origin="Local",
				payment_invoice="inv.pdf",
				permit_document=None,
			)
		]
		task = self._permit_app_task(rows=rows)
		task.custom_permit_invoices_submitted = 1
		with self.assertRaises(frappe.ValidationError):
			validate_permit_application_can_complete(task)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.task_client_paid_directly",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.is_permit_finance_task_doc",
		return_value=True,
	)
	def test_client_paid_does_not_auto_close_application_task(self, *_mocks):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			close_permit_application_when_finance_done,
		)

		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.get_permit_application_task_for_finance"
		) as get_app:
			close_permit_application_when_finance_done(
				frappe._dict(status="Completed", **{CLIENT_PAID_FIELD: 1})
			)
			get_app.assert_not_called()