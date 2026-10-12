"""Sea task behaviour comes from Task Role stamps, not step numbers.

Task-level checks ask the task's own stamps, so a Road or Air task follows its
own template instead of Sea Import's step numbers.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import document_responsibilities as dr
from cgm_shipping.cgm_worldwide_shipping.customizations import task_behaviour as tb
from cgm_shipping.cgm_worldwide_shipping.customizations import workflow as wf

def _task(role, kind="", stage="", seq=0, flow="Air Import Workflow"):
	return frappe._dict(
		name="TASK-TEST",
		custom_task_role=role,
		custom_payment_kind=kind,
		custom_permit_stage=stage,
		custom_sequence_no=seq,
		custom_task_flow_key=flow,
	)


class TestTaskLevelChecksUseStamps(unittest.TestCase):
	def test_flow_follows_the_stamp_not_the_step(self):
		# Air Import step 11 is an entry application; Sea Import's step 11 is Shipping Line.
		self.assertEqual(dr.flow_for_task(_task("Application", "ENTRY_SLIP", seq=11)), dr.FLOW_ENTRY)
		self.assertEqual(dr.flow_for_task(_task("Permit Finance", "Permit", seq=5)), dr.FLOW_PERMIT)
		self.assertEqual(dr.flow_for_task(_task("Standard", seq=4)), dr.FLOW_CLEARANCE_DOCUMENT)

	def test_application_predicates(self):
		self.assertTrue(tb.task_is_shipping_line_application(_task("Application", "Shipping Line", seq=3)))
		self.assertFalse(tb.task_is_shipping_line_application(_task("Finance Payment", "Shipping Line")))
		self.assertTrue(tb.task_is_kpa_application(_task("Application", "KPA", seq=2)))

	def test_permit_stage_from_stamp_else_default(self):
		self.assertEqual(tb.task_permit_stage(_task("Permit Finance", "Permit", "Post-clearance")), "Post-clearance")
		self.assertEqual(tb.task_permit_stage(_task("Permit Finance", seq=99), "Pre-clearance"), "Pre-clearance")


class TestPermitPairingByStamp(unittest.TestCase):
	def test_application_finds_its_finance_step(self):
		app = _task("Permit Application", stage="Pre-clearance", seq=5)
		app.project = "PROJ"
		with patch.object(tb, "get_permit_finance_for_behaviour", return_value="FIN-1"):
			self.assertEqual(wf.finance_permit_task_for_application(app), "FIN-1")

	def test_a_finance_step_is_not_its_own_pair(self):
		fin = _task("Permit Finance", "Permit", "Pre-clearance", seq=6)
		fin.project = "PROJ"
		with patch.object(tb, "get_permit_finance_for_behaviour", return_value="TASK-TEST"):
			self.assertIsNone(wf.finance_permit_task_for_application(fin))
