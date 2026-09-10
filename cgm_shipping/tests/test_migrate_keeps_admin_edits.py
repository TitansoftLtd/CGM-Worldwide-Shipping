"""Migrate tops up config from code but never overwrites what an admin edited.

Both of these used to be rebuilt from code on every migrate, silently undoing
desk edits: the Sales Invoice workflow's states and transitions, and the sea
clearance task requirements table in CGM Shipping Settings.
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import sea_settings_seed_data as sea_seed
from cgm_shipping.patches import ensure_sales_invoice_workflow as si_workflow

REQUIREMENTS = "custom_sea_clearance_task_requirements"


class _Workflow:
	def __init__(self, states=(), transitions=()):
		self.states = [frappe._dict(row) for row in states]
		self.transitions = [frappe._dict(row) for row in transitions]
		self.save = MagicMock()
		self.insert = MagicMock()

	def append(self, fieldname, row):
		getattr(self, fieldname).append(frappe._dict(row))


class TestSalesInvoiceWorkflowSync(unittest.TestCase):
	def _sync(self, workflow, *, exists=True):
		with (
			patch.object(si_workflow, "_ensure_workflow_states"),
			patch.object(frappe.db, "exists", return_value=exists),
			patch.object(frappe, "get_doc", return_value=workflow),
			patch.object(frappe, "new_doc", return_value=workflow),
		):
			si_workflow._sync_workflow()

	def test_desk_edit_survives(self):
		transitions = si_workflow._workflow_transitions()
		approve = next(t for t in transitions if t["action"] == si_workflow.SALES_INVOICE_WORKFLOW_ACTION_APPROVE)
		approve["allowed"] = "Finance Manager"
		workflow = _Workflow(si_workflow._workflow_states(), transitions)

		self._sync(workflow)

		workflow.save.assert_not_called()
		kept = next(t for t in workflow.transitions if t.action == approve["action"])
		self.assertEqual(kept.allowed, "Finance Manager")

	def test_missing_code_row_added_and_extra_row_kept(self):
		transitions = [
			t
			for t in si_workflow._workflow_transitions()
			if t["action"] != si_workflow.SALES_INVOICE_WORKFLOW_ACTION_CANCEL
		]
		transitions.append({"state": "Pending Approval", "action": "Escalate", "next_state": "Draft", "allowed": "CFO"})
		workflow = _Workflow(si_workflow._workflow_states(), transitions)

		self._sync(workflow)

		workflow.save.assert_called_once()
		actions = {t.action for t in workflow.transitions}
		self.assertIn(si_workflow.SALES_INVOICE_WORKFLOW_ACTION_CANCEL, actions)
		self.assertIn("Escalate", actions)

	def test_new_site_gets_the_full_workflow(self):
		workflow = _Workflow()

		self._sync(workflow, exists=False)

		workflow.insert.assert_called_once()
		self.assertEqual(len(workflow.states), len(si_workflow._workflow_states()))
		self.assertEqual(len(workflow.transitions), len(si_workflow._workflow_transitions()))
		self.assertEqual(workflow.override_status, 1)


class TestSeaRequirementsTopUp(unittest.TestCase):
	def setUp(self):
		self.settings = frappe.new_doc("CGM Shipping Settings")
		if not self.settings.meta.has_field(REQUIREMENTS):
			self.skipTest("CGM Shipping Settings has no sea requirements table on this site")

	def _top_up(self):
		out = io.StringIO()
		with redirect_stdout(out):
			changed = sea_seed.top_up_sea_clearance_task_requirements(self.settings)
		return changed, out.getvalue()

	def test_empty_table_is_seeded(self):
		changed, _ = self._top_up()
		self.assertTrue(changed)
		self.assertEqual(len(self.settings.get(REQUIREMENTS)), len(sea_seed.build_requirement_seed_rows()))

	def test_defaults_are_left_quietly(self):
		self._top_up()
		changed, printed = self._top_up()
		self.assertFalse(changed)
		self.assertEqual(printed, "")

	def test_edited_table_is_kept_and_reported(self):
		self._top_up()
		row = self.settings.get(REQUIREMENTS)[0]
		row.sequence_no = 99

		changed, printed = self._top_up()

		self.assertFalse(changed)
		self.assertEqual(self.settings.get(REQUIREMENTS)[0].sequence_no, 99)
		self.assertIn("left as edited", printed)
