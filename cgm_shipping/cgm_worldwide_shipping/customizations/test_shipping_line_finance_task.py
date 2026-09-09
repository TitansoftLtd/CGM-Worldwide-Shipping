# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import UnitTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
	APPLICATION_FINANCE_PROFILES,
	purge_foreign_finance_lines,
	seed_application_finance_lines,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_FINANCE_FIELD
from cgm_shipping.cgm_worldwide_shipping.customizations.task import seed_ucr_finance_lines
from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
	task_is_shipping_line_finance,
	task_is_ucr_workflow,
)


class _TaskStub(frappe._dict):
	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.meta = frappe._dict(has_field=lambda _f: True)
		if TASK_FINANCE_FIELD not in self:
			self[TASK_FINANCE_FIELD] = []

	def append(self, fieldname, row):
		self.setdefault(fieldname, []).append(frappe._dict(row))

	def remove(self, row):
		self.get(TASK_FINANCE_FIELD, []).remove(row)


def _shipping_line_finance_task(seq: int = 14) -> _TaskStub:
	return _TaskStub(
		name="TASK-TEST-SL",
		custom_task_role="Finance Payment",
		custom_payment_kind="Shipping Line",
		custom_sequence_no=seq,
		project="PROJ-TEST",
	)


class TestShippingLineFinanceTask(UnitTestCase):
	def test_task_is_shipping_line_finance_uses_stamped_kind_not_seq(self):
		# Seq 4 is UCR finance in default Sea settings; template stamp should win.
		task = _shipping_line_finance_task(seq=4)
		self.assertTrue(task_is_shipping_line_finance(task))
		self.assertFalse(task_is_ucr_workflow(task))

	def test_seed_ucr_finance_lines_skips_shipping_line_task(self):
		task = _shipping_line_finance_task(seq=4)
		task.append(
			TASK_FINANCE_FIELD,
			{"line_type": "Invoice", "payment_item": "Shipping Line", "line_label": "Shipping Line Invoice"},
		)
		seed_ucr_finance_lines(task)
		items = {row.payment_item for row in task.get(TASK_FINANCE_FIELD) or []}
		self.assertEqual(items, {"Shipping Line"})

	def test_purge_foreign_finance_lines_removes_ucr_from_shipping_line_task(self):
		task = _shipping_line_finance_task()
		task.append(
			TASK_FINANCE_FIELD,
			{"line_type": "Invoice", "payment_item": "Shipping Line", "line_label": "Shipping Line Invoice"},
		)
		task.append(
			TASK_FINANCE_FIELD,
			{"line_type": "Invoice", "payment_item": "UCR", "line_label": "UCR invoice"},
		)
		self.assertTrue(purge_foreign_finance_lines(task))
		items = {row.payment_item for row in task.get(TASK_FINANCE_FIELD) or []}
		self.assertEqual(items, {"Shipping Line"})

	def test_prepare_seeds_only_shipping_line_rows(self):
		task = _shipping_line_finance_task()
		profile = APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
		seed_application_finance_lines(task, profile)
		items = {row.payment_item for row in task.get(TASK_FINANCE_FIELD) or []}
		self.assertEqual(items, {"Shipping Line"})
		line_types = {row.line_type for row in task.get(TASK_FINANCE_FIELD) or []}
		self.assertEqual(line_types, {"Invoice", "POP", "Receipt"})
