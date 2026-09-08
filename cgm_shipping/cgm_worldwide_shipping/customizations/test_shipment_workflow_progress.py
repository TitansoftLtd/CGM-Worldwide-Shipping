# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from frappe.tests import UnitTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
	all_clearance_tasks_completed,
	derive_workflow_passed_states,
	derive_workflow_progress_from_tasks,
	effective_completed_task_seqs,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	DEFAULT_SEA_IMPORT_WORKFLOW_STATES,
	DEFAULT_SEA_WORKFLOW_TASK_GATES,
)


def _gates() -> dict[str, dict]:
	return {
		row["shipment_workflow_state"]: {
			"min_completed_task_seq": row["min_completed_task_seq"],
			"gate_rule": row.get("gate_rule") or "Standard",
		}
		for row in DEFAULT_SEA_WORKFLOW_TASK_GATES
	}


class TestWorkflowProgressFromTasks(UnitTestCase):
	def setUp(self):
		self.states = list(DEFAULT_SEA_IMPORT_WORKFLOW_STATES)
		self.gates = _gates()

	def test_all_tasks_completed_shows_completed(self):
		tasks = [
			{"custom_sequence_no": i, "status": "Completed"}
			for i in range(1, 26)
		]
		status, index = derive_workflow_progress_from_tasks(
			tasks, states=self.states, gates=self.gates
		)
		self.assertEqual(status, "Completed")
		self.assertEqual(index, self.states.index("Completed"))
		self.assertTrue(all_clearance_tasks_completed(tasks))

	def test_draft_passes_with_documents_received(self):
		tasks = [{"custom_sequence_no": 1, "status": "Completed"}]
		passed = derive_workflow_passed_states(tasks, states=self.states, gates=self.gates)
		self.assertIn("Documents Received", passed)
		self.assertIn("Draft", passed)

	def test_draft_stays_open_before_documents_received(self):
		passed = derive_workflow_passed_states([], states=self.states, gates=self.gates)
		self.assertNotIn("Draft", passed)
		self.assertNotIn("Documents Received", passed)

	def test_open_middle_task_blocks_completed_even_when_later_tasks_done(self):
		"""Task 17 open while 18–25 complete must not show Completed."""
		tasks = [
			{"custom_sequence_no": i, "status": "Completed" if i != 17 else "Open"}
			for i in range(1, 26)
		]
		status, _index = derive_workflow_progress_from_tasks(
			tasks, states=self.states, gates=self.gates
		)
		passed = derive_workflow_passed_states(tasks, states=self.states, gates=self.gates)
		self.assertNotEqual(status, "Completed")
		self.assertNotIn("Completed", passed)
		self.assertNotIn("Field Clearance", passed)
		self.assertFalse(all_clearance_tasks_completed(tasks))
		self.assertEqual(status, "Containers Returned")

	def test_out_of_order_shipping_line_shows_line_paid(self):
		"""Shipping Line finance (seq 14) done while UCR Paid (seq 4) still open."""
		tasks = [
			{"custom_sequence_no": 1, "status": "Completed"},
			{"custom_sequence_no": 2, "status": "Completed"},
			{"custom_sequence_no": 3, "status": "Completed"},
			{"custom_sequence_no": 4, "status": "Open"},
			{"custom_sequence_no": 14, "status": "Completed"},
		]
		status, _index = derive_workflow_progress_from_tasks(
			tasks, states=self.states, gates=self.gates
		)
		self.assertEqual(status, "Line Paid & DO Lodged")
		passed = derive_workflow_passed_states(tasks, states=self.states, gates=self.gates)
		self.assertIn("Line Paid & DO Lodged", passed)
		self.assertIn("UCR Applied", passed)
		self.assertNotIn("UCR Paid", passed)

	def test_contiguous_gap_no_longer_blocks_later_gates(self):
		"""Seq 4 missing no longer caps chart at UCR Applied when seq 14 is done."""
		tasks = [
			{"custom_sequence_no": 1, "status": "Completed"},
			{"custom_sequence_no": 2, "status": "Completed"},
			{"custom_sequence_no": 3, "status": "Completed"},
			{"custom_sequence_no": 14, "status": "Completed"},
			{"custom_sequence_no": 15, "status": "Open"},
		]
		status, _index = derive_workflow_progress_from_tasks(
			tasks, states=self.states, gates=self.gates
		)
		self.assertNotEqual(status, "UCR Applied")
		self.assertEqual(status, "Line Paid & DO Lodged")

	def test_permit_invoices_submitted_counts_for_gate(self):
		tasks = [
			{
				"custom_sequence_no": 5,
				"status": "Open",
				"custom_permit_invoices_submitted": 1,
			},
		]
		seqs = effective_completed_task_seqs(tasks)
		self.assertIn(5, seqs)
		status, _index = derive_workflow_progress_from_tasks(
			tasks, states=self.states, gates=self.gates
		)
		self.assertEqual(status, "Pre-clearance")

	def test_no_tasks_starts_at_draft(self):
		status, index = derive_workflow_progress_from_tasks(
			[], states=self.states, gates=self.gates
		)
		self.assertEqual(status, "Draft")
		self.assertEqual(index, 0)
