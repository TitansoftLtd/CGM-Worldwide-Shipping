# Copyright (c) 2026, Titansoft Limited and Contributors

from frappe.tests import IntegrationTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.air_clearance import (
	get_air_export_workflow_gates,
	get_air_export_workflow_states,
	get_air_import_workflow_gates,
	get_air_import_workflow_states,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
	air_export_tasks,
	air_import_tasks,
)


class TestAirClearanceWorkflow(IntegrationTestCase):
	def test_air_import_gates_cover_last_task(self):
		last_seq = max(row["sequence_no"] for row in air_import_tasks())
		states = get_air_import_workflow_states()
		self.assertEqual(states[0], "Draft")
		self.assertEqual(states[-1], "Completed")
		self.assertEqual(get_air_import_workflow_gates()["Completed"]["min_completed_task_seq"], last_seq)

	def test_air_export_gates_cover_last_task(self):
		last_seq = max(row["sequence_no"] for row in air_export_tasks())
		self.assertEqual(get_air_export_workflow_states()[-1], "Completed")
		self.assertEqual(get_air_export_workflow_gates()["Completed"]["min_completed_task_seq"], last_seq)
