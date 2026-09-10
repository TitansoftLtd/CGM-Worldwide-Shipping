"""Shipment status gates live on each CGM Task Template.

They were in CGM Shipping Settings (Sea Import) and in Python tables for the
other workflows, away from the task steps they point at. Each template now has a
Shipment Status Gates table; these checks keep the seeds, the doctype and the
readers agreeing.
"""

import json
import os
import unittest
from unittest.mock import patch

import frappe

import cgm_shipping
from cgm_shipping.cgm_worldwide_shipping.customizations import template_gates as tg
from cgm_shipping.cgm_worldwide_shipping.customizations import workflow_tasks as wt
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SHIPMENT_STATUSES
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
	AIR_EXPORT_TEMPLATE,
	AIR_IMPORT_TEMPLATE,
	ROAD_TRANSIT_INBOUND_TEMPLATE,
	SEA_EXPORT_TEMPLATE,
	SEA_IMPORT_TEMPLATE,
	SEA_TRANSIT_IMPORT_TEMPLATE,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
	TEMPLATE_DEFINITIONS,
)

DOCTYPE_DIR = os.path.join(os.path.dirname(cgm_shipping.__file__), "cgm_worldwide_shipping", "doctype")

# Seeded gates whose task is not in the seeded plan, so the status is never
# reached. Copied as they were when the gates moved, so the move changed nothing;
# fix them on the template.
KNOWN_MISSING_STEPS = {(SEA_IMPORT_TEMPLATE, "Client Inspection")}

ROWS = (
	{"shipment_workflow_state": "Documents Received", "min_completed_task_seq": 1, "gate_rule": None},
	{"shipment_workflow_state": "Completed", "min_completed_task_seq": 9, "gate_rule": "All Sea Tasks Complete"},
)


def _fields(doctype_dir):
	with open(os.path.join(DOCTYPE_DIR, doctype_dir, f"{doctype_dir}.json")) as f:
		return {d["fieldname"]: d for d in json.load(f)["fields"]}


class TestGateDoctype(unittest.TestCase):
	def test_status_options_are_the_shipment_statuses(self):
		options = _fields("cgm_task_template_gate")["shipment_workflow_state"]["options"]
		self.assertEqual(options.split("\n"), [s for s in SHIPMENT_STATUSES if s != "Draft"])

	def test_rule_options_are_the_enforced_rules(self):
		options = _fields("cgm_task_template_gate")["gate_rule"]["options"]
		self.assertEqual(tuple(options.split("\n")), tg.GATE_RULES)

	def test_template_has_the_table(self):
		self.assertEqual(_fields("cgm_task_template")["gates"]["options"], tg.GATE_DOCTYPE)

	def test_settings_no_longer_has_the_table(self):
		self.assertNotIn("custom_sea_workflow_task_gates", _fields("cgm_shipping_settings"))


class TestSeededGates(unittest.TestCase):
	def test_gate_tasks_are_in_their_plan(self):
		for definition in TEMPLATE_DEFINITIONS:
			sequences = {row["sequence_no"] for row in definition["tasks"]}
			for row in definition.get("gates") or []:
				key = (definition["template_name"], row["shipment_workflow_state"])
				with self.subTest(template=key[0], state=key[1]):
					if key in KNOWN_MISSING_STEPS:
						self.assertNotIn(row["min_completed_task_seq"], sequences)
					else:
						self.assertIn(row["min_completed_task_seq"], sequences)

	def test_each_status_once_per_template(self):
		for definition in TEMPLATE_DEFINITIONS:
			states = [row["shipment_workflow_state"] for row in definition.get("gates") or []]
			with self.subTest(template=definition["template_name"]):
				self.assertEqual(len(states), len(set(states)))

	def test_the_clearance_workflows_have_gates(self):
		"""The five workflows that had gate tables before the move still do."""
		self.assertEqual(
			{d["template_name"] for d in TEMPLATE_DEFINITIONS if d.get("gates")},
			{
				SEA_IMPORT_TEMPLATE,
				SEA_TRANSIT_IMPORT_TEMPLATE,
				ROAD_TRANSIT_INBOUND_TEMPLATE,
				AIR_IMPORT_TEMPLATE,
				AIR_EXPORT_TEMPLATE,
			},
		)

	def test_rules_are_known(self):
		for definition in TEMPLATE_DEFINITIONS:
			for row in definition.get("gates") or []:
				self.assertIn(row.get("gate_rule") or tg.GATE_RULE_STANDARD, tg.GATE_RULES)


class TestReaders(unittest.TestCase):
	def test_gate_map_keeps_order_and_defaults_the_rule(self):
		gates = tg.gate_map(ROWS)
		self.assertEqual(list(gates), ["Documents Received", "Completed"])
		self.assertEqual(
			gates["Documents Received"], {"min_completed_task_seq": 1, "gate_rule": "Standard"}
		)

	def test_states_start_with_draft(self):
		self.assertEqual(tg.gate_states(ROWS), ["Draft", "Documents Received", "Completed"])


class TestProjectDispatch(unittest.TestCase):
	def _template_for(self, template, templates_with_gates):
		with patch.object(wt, "get_workflow_template_name", return_value=template), patch.object(
			tg, "_template_gate_rows", side_effect=lambda name: ROWS if name in templates_with_gates else ()
		):
			return wt.gate_template_for_project("PROJ-TEST")

	def test_own_gates_are_used(self):
		self.assertEqual(
			self._template_for(ROAD_TRANSIT_INBOUND_TEMPLATE, {ROAD_TRANSIT_INBOUND_TEMPLATE, SEA_IMPORT_TEMPLATE}),
			ROAD_TRANSIT_INBOUND_TEMPLATE,
		)

	def test_template_without_gates_uses_sea_import(self):
		self.assertEqual(self._template_for(SEA_EXPORT_TEMPLATE, {SEA_IMPORT_TEMPLATE}), SEA_IMPORT_TEMPLATE)

	def test_chart_states_come_from_the_gates(self):
		with patch.object(wt, "gate_template_for_project", return_value=ROAD_TRANSIT_INBOUND_TEMPLATE), patch.object(
			tg, "_template_gate_rows", return_value=ROWS
		):
			self.assertEqual(
				wt.get_clearance_workflow_states_for_project("PROJ-TEST"),
				["Draft", "Documents Received", "Completed"],
			)

	def test_sea_import_chart_follows_its_workflow(self):
		with patch.object(wt, "gate_template_for_project", return_value=SEA_IMPORT_TEMPLATE), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance.get_tracking_workflow_states",
			return_value=["Draft", "Documents Received"],
		):
			self.assertEqual(
				wt.get_clearance_workflow_states_for_project("PROJ-TEST"), ["Draft", "Documents Received"]
			)


class TestTemplateValidation(unittest.TestCase):
	def _template(self, *gates):
		return frappe.get_doc(
			{
				"doctype": "CGM Task Template",
				"template_name": "Gate Test",
				"tasks": [
					{"sequence_no": 1, "subject": "Receive documents", "department_role": "Operations"},
					{"sequence_no": 2, "subject": "Deliver", "department_role": "Transport"},
				],
				"gates": [
					{"shipment_workflow_state": state, "min_completed_task_seq": seq, "gate_rule": "Standard"}
					for state, seq in gates
				],
			}
		)

	def test_task_subject_is_filled(self):
		doc = self._template(("Documents Received", 1), ("Completed", 2))
		doc.validate_gates()
		self.assertEqual([g.task_subject for g in doc.gates], ["Receive documents", "Deliver"])

	def test_same_status_twice_is_rejected(self):
		doc = self._template(("Documents Received", 1), ("Documents Received", 2))
		with self.assertRaises(frappe.ValidationError):
			doc.validate_gates()

	def test_task_not_in_the_plan_warns(self):
		doc = self._template(("Client Inspection", 7))
		with patch.object(frappe, "msgprint") as msgprint:
			doc.validate_gates()
		msgprint.assert_called_once()
		self.assertEqual(doc.gates[0].task_subject, "")
