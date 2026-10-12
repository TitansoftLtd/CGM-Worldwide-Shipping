"""Paired-task visibility is decided by Task Role stamps, not step numbers.

The rules themselves did not change - a per-user comparison of every task list
and form check on a production copy came out identical. What changed is that
they no longer break when a template row is moved or a step is inserted.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import permissions as p

RESPONSIBILITY = (
	"cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities.user_has_responsibility"
)


class TestLinkedTaskSql(unittest.TestCase):
	def _sql(self, stems):
		with (
			patch.object(p, "_linked_application_department_stems", return_value=frozenset({"Declaration"})),
			patch.object(p, "_linked_finance_department_stems", return_value=frozenset({"Finance"})),
		):
			return p._build_linked_sea_task_sql(set(stems))

	def test_matches_on_stamps_never_numbers(self):
		sql = self._sql({"Declaration", "Finance"})
		self.assertIn("custom_task_role", sql)
		self.assertIn("custom_permit_stage", sql)
		self.assertNotIn("custom_sequence_no", sql)

	def test_application_side_sees_finance_steps(self):
		sql = self._sql({"Declaration"})
		self.assertIn("`tabTask`.`custom_task_role` = 'Finance Payment'", sql)
		self.assertIn("`tabTask`.`custom_task_role` = 'Permit Finance'", sql)
		self.assertNotIn("`tabTask`.`custom_task_role` = 'Application'", sql)

	def test_finance_side_sees_application_steps(self):
		sql = self._sql({"Finance"})
		self.assertIn("`tabTask`.`custom_task_role` = 'Application'", sql)
		self.assertIn("`tabTask`.`custom_task_role` = 'Permit Application'", sql)

	def test_only_linked_payment_kinds(self):
		self.assertIn("IN ('UCR', 'Shipping Line')", self._sql({"Declaration"}))

	def test_unrelated_department_gets_nothing(self):
		self.assertIsNone(self._sql({"Transport"}))


class TestLinkedTaskForm(unittest.TestCase):
	def _can(self, role, *, kind=None, stage=None, finance=False, declarant=False, receipt=False, paired=True):
		doc = frappe._dict(
			name="T",
			project="PROJ",
			custom_task_role=role,
			custom_payment_kind=kind,
			custom_permit_stage=stage,
		)
		with (
			patch.object(p, "is_sea_import_task", return_value=True),
			patch.object(p, "user_has_finance_department_access", return_value=finance),
			patch.object(p, "user_has_declarant_department_access", return_value=declarant),
			patch.object(p, "_project_has_linked_task", return_value=paired),
			patch(RESPONSIBILITY, return_value=receipt),
		):
			return p._user_can_access_linked_sea_project_task(doc, "user@example.com")

	def test_finance_opens_permit_application(self):
		self.assertTrue(self._can("Permit Application", stage="Pre-clearance", finance=True))

	def test_finance_opens_ucr_application_only_when_paired(self):
		self.assertTrue(self._can("Application", kind="UCR", finance=True))
		self.assertFalse(self._can("Application", kind="UCR", finance=True, paired=False))

	def test_finance_does_not_open_unlinked_applications(self):
		self.assertFalse(self._can("Application", kind="KPA", finance=True))

	def test_declarant_with_receipt_duty_opens_permit_finance(self):
		self.assertTrue(self._can("Permit Finance", stage="Post-clearance", declarant=True, receipt=True))
		self.assertFalse(self._can("Permit Finance", stage="Post-clearance", declarant=True))

	def test_shipping_line_receipt_owner_opens_shipping_line_finance(self):
		self.assertTrue(self._can("Finance Payment", kind="Shipping Line", receipt=True))
		self.assertFalse(self._can("Finance Payment", kind="Shipping Line"))


class TestFinanceStepByRole(unittest.TestCase):
	def _can(self, role, department="Finance - CWSCL"):
		doc = frappe._dict(name="T", custom_task_role=role, department=department)
		with patch.object(p, "user_has_finance_department_access", return_value=True):
			return p._user_can_access_sea_payment_task_by_role(doc, "user@example.com")

	def test_finance_roles_count(self):
		self.assertTrue(self._can("Finance Payment"))
		self.assertTrue(self._can("Permit Finance"))

	def test_other_roles_do_not(self):
		self.assertFalse(self._can("Application"))

	def test_finance_step_outside_finance_department_does_not(self):
		self.assertFalse(self._can("Finance Payment", department="Operations - CWSCL"))


class TestStampsOnSqlRows(unittest.TestCase):
	def test_row_without_stamps_reads_them(self):
		stored = {"custom_task_role": "Permit Finance", "custom_payment_kind": "Permit", "custom_permit_stage": "Pre-clearance"}
		with patch.object(frappe.db, "get_value", return_value=stored) as get_value:
			stamps = p._task_stamps(frappe._dict(name="TASK-1", department="Finance"))
		get_value.assert_called_once()
		self.assertEqual(stamps.custom_task_role, "Permit Finance")

	def test_row_with_stamps_is_not_reread(self):
		with patch.object(frappe.db, "get_value") as get_value:
			stamps = p._task_stamps(frappe._dict(name="TASK-1", custom_task_role="Application", custom_payment_kind="UCR"))
		get_value.assert_not_called()
		self.assertEqual(stamps.custom_payment_kind, "UCR")
