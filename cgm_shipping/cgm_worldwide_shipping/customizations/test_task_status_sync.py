# Copyright (c) 2026, Titansoft Limited and contributors

import unittest
from unittest.mock import MagicMock, patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
	preserve_completed_status_against_stale_save,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import mark_task_completed


class TestTaskStatusSync(unittest.TestCase):
	def test_mark_task_completed_updates_memory_and_db(self):
		task = frappe._dict(
			name="TASK-STATUS-1",
			status="Open",
			progress=0,
			completed_by=None,
			completed_on=None,
		)
		task.set = lambda field, value: task.update({field: value})

		with (
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.frappe.db.exists",
				return_value=True,
			),
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.frappe.db.set_value"
			) as set_value,
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.frappe.clear_document_cache"
			),
		):
			mark_task_completed(task)

		self.assertEqual(task.status, "Completed")
		self.assertEqual(task.progress, 100)
		self.assertTrue(task.completed_by)
		set_value.assert_called_once()

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.task.is_sea_finance_payment_task",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.task.frappe.db.get_value",
		return_value="Completed",
	)
	def test_stale_open_save_cannot_overwrite_completed(self, *_mocks):
		task = MagicMock()
		task.is_new.return_value = False
		task.name = "TASK-STATUS-2"
		task.status = "Open"
		task.progress = 0
		task.completed_by = None
		task.completed_on = None
		preserve_completed_status_against_stale_save(task)
		self.assertEqual(task.status, "Completed")
		self.assertEqual(task.progress, 100)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.is_application_workflow_task",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.task_has_finance_table",
		return_value=True,
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.seed_application_finance_lines",
	)
	def test_application_finance_line_seed_inserts_without_parent_save(self, seed, *_mocks):
		"""Missing finance lines are inserted as children; Task.modified is not bumped."""
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			APPLICATION_FINANCE_PROFILES,
			ensure_application_finance_lines_saved,
		)

		profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
		new_row = MagicMock()
		new_row.payment_item = profile.payment_item
		new_row.line_type = "Invoice"
		new_row.line_label = profile.invoice_label
		new_row.get = lambda key, default=None: None if key == "name" else getattr(new_row, key, default)
		new_row.name = None
		new_row.attachment = None

		task = MagicMock()
		task.name = "TASK-TEST"
		task.project = "PROJ-1"
		task.company = "CWSCL"
		task.get.side_effect = lambda key, default=None: {
			"custom_sequence_no": 13,
			"custom_task_finance_lines": [new_row],
		}.get(key, default)
		task.custom_sequence_no = 13

		child_doc = MagicMock()
		child_doc.name = "TFL-NEW"

		with (
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance._finance_lines_snapshot",
				side_effect=[("before",), ("after",)],
			),
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.frappe.get_doc",
				return_value=child_doc,
			) as get_doc,
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.frappe.publish_realtime"
			),
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.frappe.clear_document_cache"
			),
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.is_application_finance_task",
				return_value=False,
			),
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.task.task_finance_line_has_item_code",
				return_value=False,
			),
		):
			self.assertTrue(ensure_application_finance_lines_saved(task, profile))
			get_doc.assert_called_once()
			child_doc.insert.assert_called_once_with(ignore_permissions=True)
			task.save.assert_not_called()
