"""Intake auto-complete comes from the template; Sea Import checks stay on Sea Import.

Which tasks complete at project creation, when the client's documents are
already in, came from code: step 1 for Road Transit Inbound and Sea Import's
steps for everything else - so Sea Transit Import's step 2 (Request shipping
line charges from B/L) was completed on every project. The template marks the
intake tasks now.

Sea Import's status gates and closure check ran on every Sea shipment. On a Sea
Transit project they looked for Sea Import tasks that do not exist and refused
the change. They now run only on the Sea Import plan.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping import task_engine
from cgm_shipping.cgm_worldwide_shipping.customizations import project as project_module
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
	ROAD_TRANSIT_INBOUND_TEMPLATE,
	SEA_IMPORT_TEMPLATE,
	SEA_TRANSIT_IMPORT_TEMPLATE,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
	TEMPLATE_DEFINITIONS,
)

WORKFLOW_TEMPLATE_NAME = (
	"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks.get_workflow_template_name"
)


class TestIntakeTasksFromTemplate(unittest.TestCase):
	def test_seeded_intake_tasks(self):
		marked = {
			d["template_name"]: [r["sequence_no"] for r in d["tasks"] if r.get("completes_on_intake")]
			for d in TEMPLATE_DEFINITIONS
		}
		self.assertEqual(
			{name: seqs for name, seqs in marked.items() if seqs},
			{
				SEA_IMPORT_TEMPLATE: [1, 2],
				ROAD_TRANSIT_INBOUND_TEMPLATE: [1],
				SEA_TRANSIT_IMPORT_TEMPLATE: [1],
			},
		)

	def test_intake_sequences_read_the_template(self):
		items = [
			{"sequence_no": 3, "completes_on_intake": True},
			{"sequence_no": 2, "completes_on_intake": False},
			{"sequence_no": 1, "completes_on_intake": True},
		]
		with patch.object(task_engine, "frappe"), patch.object(
			task_engine, "_collect_items", return_value=items
		):
			self.assertEqual(task_engine.intake_sequences("Any Workflow"), [1, 3])

	def test_template_without_intake_tasks_does_nothing(self):
		with patch.object(task_engine, "intake_sequences", return_value=[]), patch.object(
			task_engine, "frappe"
		) as mock_frappe:
			task_engine._run_post_create_automation("PROJ-TEST", "Air Import Workflow")
		mock_frappe.get_doc.assert_not_called()


class _Project(frappe._dict):
	def get_doc_before_save(self):
		return self.prev


def _project(prev_status, new_status, mode="Sea"):
	return _Project(
		name="PROJ-TEST",
		custom_shipment_status=new_status,
		custom_mode_of_transport=mode,
		prev=frappe._dict(custom_shipment_status=prev_status),
	)


class TestSeaImportGuards(unittest.TestCase):
	def test_plan_decides_not_the_mode(self):
		with patch(WORKFLOW_TEMPLATE_NAME, return_value=SEA_TRANSIT_IMPORT_TEMPLATE):
			self.assertFalse(project_module.runs_sea_import_workflow(_project("Draft", "Entry Lodged")))
		with patch(WORKFLOW_TEMPLATE_NAME, return_value=SEA_IMPORT_TEMPLATE):
			self.assertTrue(project_module.runs_sea_import_workflow(_project("Draft", "Entry Lodged")))

	def test_sea_transit_skips_the_sea_import_gates(self):
		with patch(WORKFLOW_TEMPLATE_NAME, return_value=SEA_TRANSIT_IMPORT_TEMPLATE), patch.object(
			project_module, "enforce_workflow_task_gate"
		) as gate:
			project_module.enforce_sea_workflow_task_gates(_project("Documents Received", "Entry Lodged"))
		gate.assert_not_called()

	def test_sea_import_is_still_gated(self):
		with patch(WORKFLOW_TEMPLATE_NAME, return_value=SEA_IMPORT_TEMPLATE), patch.object(
			project_module, "enforce_workflow_task_gate"
		) as gate:
			project_module.enforce_sea_workflow_task_gates(_project("Documents Received", "Entry Lodged"))
		gate.assert_called_once_with("PROJ-TEST", "Entry Lodged")
