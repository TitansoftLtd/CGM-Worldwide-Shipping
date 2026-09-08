# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from frappe.tests import UnitTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
	derive_workflow_progress_from_tasks,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_transit_import_workflow import (
	DEFAULT_SEA_TRANSIT_IMPORT_WORKFLOW_GATES,
	DEFAULT_SEA_TRANSIT_IMPORT_WORKFLOW_STATES,
	get_sea_transit_import_workflow_gates,
	get_sea_transit_import_workflow_states,
)


def _gates() -> dict[str, dict]:
	return get_sea_transit_import_workflow_gates()


class TestSeaTransitImportWorkflowProgress(UnitTestCase):
	def setUp(self):
		self.states = get_sea_transit_import_workflow_states()
		self.gates = _gates()

	def test_chart_excludes_manifest_requested(self):
		self.assertNotIn("Manifest Requested", self.states)
		self.assertNotIn("Manifest Requested", self.gates)
		self.assertNotIn("UCR Applied", self.states)
		self.assertNotIn("Final Docs Received", self.states)

	def test_expected_state_count(self):
		self.assertEqual(len(self.states), len(DEFAULT_SEA_TRANSIT_IMPORT_WORKFLOW_STATES))
		self.assertEqual(len(self.gates), len(DEFAULT_SEA_TRANSIT_IMPORT_WORKFLOW_GATES))

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
