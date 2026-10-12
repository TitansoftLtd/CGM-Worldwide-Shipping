"""Sea Import LCL: its own task plan, run under the Sea Import rules (files/LCL WORKFLOW.docx).

LCL cargo clears like Sea Import, then pays CFS charges (instead of KPA) and is
delivered to the client with the transporter's delivery note (no containers).
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import task_template_registry as reg
from cgm_shipping.cgm_worldwide_shipping.customizations import task_template_seed_data as seed


class TestSeaImportFamily(unittest.TestCase):
	def test_lcl_tasks_run_the_sea_import_rules(self):
		self.assertTrue(reg.is_sea_import_task(frappe._dict(custom_task_flow_key=reg.SEA_IMPORT_LCL_TEMPLATE)))
		self.assertTrue(reg.is_sea_import_template(reg.SEA_IMPORT_LCL_TEMPLATE))
		self.assertFalse(reg.is_sea_import_template(reg.SEA_TRANSIT_IMPORT_TEMPLATE))

	def test_flow_key_filters_cover_fcl_and_lcl(self):
		keys = reg.task_flow_key_in_filter()[1]
		self.assertIn(reg.SEA_IMPORT_TEMPLATE, keys)
		self.assertIn(reg.SEA_IMPORT_LCL_TEMPLATE, keys)
		self.assertEqual(reg.task_flow_key_in_filter(reg.SEA_IMPORT_LCL_TEMPLATE), ["in", [reg.SEA_IMPORT_LCL_TEMPLATE]])


class TestLclTemplateSeed(unittest.TestCase):
	def setUp(self):
		self.rows = {row["sequence_no"]: row for row in seed.sea_import_lcl_tasks()}

	def test_follows_the_document(self):
		self.assertEqual(len(self.rows), 20)
		self.assertEqual(self.rows[16]["subject"], "Supervisor gets CFS charges")
		self.assertEqual(self.rows[20]["subject"], "Delivery note from the transporter after delivery")

	def test_cfs_pair_is_an_application_and_its_payment(self):
		self.assertEqual((self.rows[16]["task_role"], self.rows[16]["payment_kind"]), ("Application", "CFS"))
		self.assertEqual((self.rows[17]["task_role"], self.rows[17]["payment_kind"]), ("Finance Payment", "CFS"))
		self.assertEqual(self.rows[17]["depends_on_sequences"], "16")

	def test_no_container_steps_after_field_clearance(self):
		for seq in range(16, 21):
			self.assertEqual(self.rows[seq]["container_step"], "", seq)

	def test_delivery_note_is_required_to_complete(self):
		self.assertEqual(self.rows[20]["required_document_types"], "Delivery Note")

	def test_gates_point_at_steps_in_the_plan(self):
		for gate in seed.SEA_IMPORT_LCL_GATES:
			self.assertIn(gate["min_completed_task_seq"], self.rows, gate)
		states = [g["shipment_workflow_state"] for g in seed.SEA_IMPORT_LCL_GATES]
		self.assertIn("CFS Paid", states)
		self.assertNotIn("KPA Paid", states)
		self.assertNotIn("Containers Returned", states)


class TestCfsProfile(unittest.TestCase):
	def test_cfs_payment_kind_has_a_profile(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import profile_for_payment_kind

		profile = profile_for_payment_kind("CFS")
		self.assertEqual((profile.key, profile.gate_rule), ("cfs", "CFS Finance Complete"))

	def test_cfs_paid_gate_rule_is_known(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations.template_gates import GATE_RULES

		self.assertIn("CFS Finance Complete", GATE_RULES)


class TestPlanByCargoType(unittest.TestCase):
	def test_cargo_type_row_wins_over_the_shipment_type_template(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import shipment

		record = frappe._dict(name="Sea Import", task_template=reg.SEA_IMPORT_TEMPLATE)
		with (
			patch.object(shipment, "get_shipment_type_record", return_value=record),
			patch.object(shipment, "_shipment_type_field_queryable", return_value=True),
			patch.object(frappe.db, "table_exists", return_value=True),
			patch.object(
				frappe.db, "get_value", side_effect=lambda dt, filters, field: reg.SEA_IMPORT_LCL_TEMPLATE
				if filters.get("cargo_type") == "LCL" else None
			),
		):
			self.assertEqual(shipment.get_task_template_for_shipment_type("Sea Import", "LCL"), reg.SEA_IMPORT_LCL_TEMPLATE)
			self.assertEqual(shipment.get_task_template_for_shipment_type("Sea Import", "FCL"), reg.SEA_IMPORT_TEMPLATE)
			self.assertEqual(shipment.get_task_template_for_shipment_type("Sea Import"), reg.SEA_IMPORT_TEMPLATE)


class TestStatusChart(unittest.TestCase):
	def test_fcl_chart_leaves_out_lcl_only_statuses(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import sea_clearance
		from cgm_shipping.cgm_worldwide_shipping.customizations import template_gates
		from cgm_shipping.cgm_worldwide_shipping.customizations import workflow_tasks as wt

		gates = {
			reg.SEA_IMPORT_TEMPLATE: {"KPA Paid": {}, "Completed": {}},
			reg.SEA_IMPORT_LCL_TEMPLATE: {"CFS Paid": {}, "Completed": {}},
		}
		with (
			patch.object(wt, "gate_template_for_project", return_value=reg.SEA_IMPORT_TEMPLATE),
			patch.object(template_gates, "get_template_gates", side_effect=lambda t: gates[t]),
			patch.object(
				sea_clearance, "get_tracking_workflow_states",
				return_value=["Draft", "Client Inspection", "KPA Paid", "CFS Paid", "Completed"],
			),
		):
			self.assertEqual(
				wt.get_clearance_workflow_states_for_project("PROJ-TEST"),
				["Draft", "Client Inspection", "KPA Paid", "Completed"],
			)
