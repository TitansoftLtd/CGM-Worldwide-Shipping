# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from frappe.tests import UnitTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
	derive_workflow_progress_from_tasks,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
	SEA_TRANSIT_IMPORT_GATES,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.template_gates import (
	gate_map,
	gate_states,
)


class TestSeaTransitImportWorkflowProgress(UnitTestCase):
	def setUp(self):
		self.states = gate_states(SEA_TRANSIT_IMPORT_GATES)
		self.gates = gate_map(SEA_TRANSIT_IMPORT_GATES)

	def test_chart_excludes_manifest_requested(self):
		self.assertNotIn("Manifest Requested", self.states)
		self.assertNotIn("Manifest Requested", self.gates)
		self.assertNotIn("UCR Applied", self.states)
		self.assertNotIn("Final Docs Received", self.states)

	def test_expected_state_count(self):
		self.assertEqual(len(self.states), len(SEA_TRANSIT_IMPORT_GATES) + 1)
		self.assertEqual(len(self.gates), len(SEA_TRANSIT_IMPORT_GATES))

	def test_line_paid_after_delivery_order(self):
		tasks = [
			{"custom_sequence_no": i, "status": "Completed"}
			for i in range(1, 6)
		]
		status, _index = derive_workflow_progress_from_tasks(
			tasks, states=self.states, gates=self.gates
		)
		self.assertEqual(status, "Line Paid & DO Lodged")

	def test_entry_paid_after_transit_finance(self):
		tasks = [
			{"custom_sequence_no": i, "status": "Completed"}
			for i in range(1, 9)
		]
		status, _index = derive_workflow_progress_from_tasks(
			tasks, states=self.states, gates=self.gates
		)
		self.assertEqual(status, "Entry Paid")

	def test_all_tasks_completed(self):
		tasks = [
			{"custom_sequence_no": i, "status": "Completed"}
			for i in range(1, 16)
		]
		status, index = derive_workflow_progress_from_tasks(
			tasks, states=self.states, gates=self.gates
		)
		self.assertEqual(status, "Completed")
		self.assertEqual(index, self.states.index("Completed"))
