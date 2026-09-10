"""Sea task behaviour comes from Task Role stamps, not step numbers.

rows_by_sequence() - the layer most sea helpers read - builds its behaviour rows
from the Sea Import template's stamps; Settings supplies only evidence rows
(Document codes, Light Proof). Task-level checks ask the task's own stamps, so a
Road or Air task follows its own template instead of Sea Import's step numbers.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import document_responsibilities as dr
from cgm_shipping.cgm_worldwide_shipping.customizations import task as t
from cgm_shipping.cgm_worldwide_shipping.customizations import task_behaviour as tb
from cgm_shipping.cgm_worldwide_shipping.customizations import workflow as wf

UTILS = "cgm_shipping.cgm_worldwide_shipping.customizations.utils"

TEMPLATE_ROWS = [
	{"sequence_no": 3, "task_role": "Application", "payment_kind": "UCR", "permit_stage": ""},
	{"sequence_no": 4, "task_role": "Finance Payment", "payment_kind": "UCR", "permit_stage": ""},
	{"sequence_no": 5, "task_role": "Permit Application", "payment_kind": "", "permit_stage": "Pre-clearance"},
	{"sequence_no": 6, "task_role": "Permit Finance", "payment_kind": "Permit", "permit_stage": "Pre-clearance"},
	{"sequence_no": 12, "task_role": "Application", "payment_kind": "ENTRY_SLIP", "permit_stage": ""},
	{"sequence_no": 13, "task_role": "Finance Payment", "payment_kind": "ENTRY_SLIP", "permit_stage": ""},
	{"sequence_no": 14, "task_role": "Document", "payment_kind": "", "permit_stage": ""},
]

SETTINGS_ROWS = [
	# A stale behaviour row the template contradicts - must be ignored.
	frappe._dict(sequence_no=3, requirement_type="Entry Application", value=""),
	frappe._dict(sequence_no=14, requirement_type="Document", value="DO"),
	frappe._dict(sequence_no=20, requirement_type="Light Proof", value=""),
]


def _types(rows):
	return sorted((r.requirement_type, r.value or "") for r in rows)


class TestRequirementRowsFromTemplate(unittest.TestCase):
	def _template_rows(self):
		with (
			patch.object(frappe.db, "exists", return_value=True),
			patch(f"{UTILS}.load_sea_task_template", return_value=TEMPLATE_ROWS),
		):
			rows = t._template_requirement_rows()
		grouped = {}
		for row in rows:
			grouped.setdefault(row.sequence_no, []).append(row)
		return grouped

	def test_each_role_becomes_its_requirement(self):
		rows = self._template_rows()
		self.assertEqual(_types(rows[3]), [("UCR Application", "")])
		self.assertEqual(_types(rows[4]), [("Finance Payment", "UCR")])
		self.assertEqual(_types(rows[5]), [("Permit Application", ""), ("Permit Stage", "Pre-clearance")])
		self.assertEqual(_types(rows[6]), [("Finance Payment", "Permit")])
		self.assertEqual(_types(rows[12]), [("Entry Application", "")])
		self.assertEqual(_types(rows[13]), [("Finance Payment", "Entry Slip")])
		self.assertNotIn(14, rows)

	def _grouped(self, template_rows):
		settings = MagicMock()
		settings.meta.has_field.return_value = True
		settings.get.return_value = SETTINGS_ROWS
		with (
			patch(f"{UTILS}.get_cgm_shipping_settings", return_value=settings),
			patch.object(t, "_template_requirement_rows", return_value=template_rows),
		):
			return t.rows_by_sequence.__wrapped__()

	def test_settings_supply_only_evidence(self):
		grouped = self._grouped([frappe._dict(sequence_no=3, requirement_type="UCR Application", value="")])
		self.assertEqual(_types(grouped[3]), [("UCR Application", "")])
		self.assertEqual(_types(grouped[14]), [("Document", "DO")])
		self.assertEqual(_types(grouped[20]), [("Light Proof", "")])

	def test_without_template_settings_are_used_in_full(self):
		grouped = self._grouped(None)
		self.assertEqual(_types(grouped[3]), [("Entry Application", "")])


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
		with patch.object(t, "permit_stage_by_sequence", return_value={}):
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
