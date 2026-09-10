"""Container steps come from the Container Step stamp, not the step number.

The container grid's columns, tracker updates and completion checks were keyed
on step numbers from CGM Shipping Settings. When the Sea Import template was
renumbered the grid's column conditions were not, so every transport task showed
the previous step's columns and Interchange's never appeared. The stamp on each
Task now decides.
"""

import json
import os
import unittest
from unittest.mock import patch

import frappe

import cgm_shipping
from cgm_shipping.cgm_worldwide_shipping.customizations import container_tracker as ct
from cgm_shipping.cgm_worldwide_shipping.customizations import task_container_updates as tcu
from cgm_shipping.cgm_worldwide_shipping.customizations import task_template_seed_data as seed
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	CONTAINER_STEP_BY_SEQ_FIELD,
	CONTAINER_STEPS,
	CONTAINER_UPDATE_STEPS,
	CONTAINER_UPDATES_DEPENDS_ON,
)

MODULE_DIR = os.path.join(os.path.dirname(cgm_shipping.__file__), "cgm_worldwide_shipping")


def _json(*parts):
	with open(os.path.join(MODULE_DIR, *parts)) as f:
		return json.load(f)


def _task(**fields):
	base = {
		"name": "TASK-TEST",
		"custom_task_flow_key": "Sea Import Workflow",
		"custom_task_role": "Standard",
		"custom_sequence_no": 0,
		"custom_container_step": "",
	}
	base.update(fields)
	return frappe._dict(base)


def _settings_numbers(fieldname):
	return list(CONTAINER_STEP_BY_SEQ_FIELD).index(fieldname) + 100


class TestContainerStepForTask(unittest.TestCase):
	def test_stamp_decides_not_the_step_number(self):
		task = _task(custom_container_step="Gate Out", custom_sequence_no=7)
		self.assertEqual(ct.container_step_for_task(task), "Gate Out")

	def test_stamped_task_without_a_step_is_not_one(self):
		with patch.object(frappe, "get_meta") as meta:
			meta.return_value.has_field.return_value = True
			self.assertEqual(ct.container_step_for_task(_task(custom_sequence_no=21)), "")

	def test_unstamped_sea_task_falls_back_to_the_settings_number(self):
		with patch.object(ct, "get_container_task_sequence", side_effect=_settings_numbers):
			task = _task(custom_task_role="", custom_sequence_no=_settings_numbers("custom_gate_out_task_seq"))
			self.assertEqual(ct.container_step_for_task(task), "Gate Out")

	def test_every_step_has_its_own_key(self):
		with patch.object(ct, "get_container_task_sequence", side_effect=_settings_numbers):
			keys = {ct.container_step_sequence(step) for step in CONTAINER_STEPS}
			self.assertEqual(len(keys), len(CONTAINER_STEPS))
			self.assertEqual(ct.container_step_sequence("Not a step"), 0)


class TestContainerUpdateGrid(unittest.TestCase):
	def test_container_steps_show_the_grid(self):
		self.assertTrue(tcu.is_container_update_task(_task(custom_container_step="Book Trucks")))
		self.assertTrue(tcu.is_container_update_task(_task(custom_container_step="Interchange")))

	def test_eta_refresh_does_not(self):
		self.assertFalse(tcu.is_container_update_task(_task(custom_container_step="ETA Refresh")))

	def test_shipping_line_deposit_steps_do(self):
		task = _task(custom_task_role="Finance Payment", custom_payment_kind="Shipping Line")
		self.assertTrue(tcu.is_container_update_task(task))

	def test_other_workflows_do_not(self):
		task = _task(custom_container_step="Book Trucks", custom_task_flow_key="Air Import Workflow")
		self.assertFalse(tcu.is_container_update_task(task))


class TestConditionsAgree(unittest.TestCase):
	def test_grid_columns_follow_the_stamp(self):
		fields = _json("doctype", "task_container_update", "task_container_update.json")["fields"]
		conditions = [
			f.get(key) for f in fields for key in ("depends_on", "mandatory_depends_on") if f.get(key)
		]
		self.assertTrue(conditions)
		for condition in conditions:
			with self.subTest(condition=condition):
				self.assertIn("custom_container_step", condition)
				self.assertNotIn("custom_sequence_no", condition)
		used = {step for step in CONTAINER_STEPS for c in conditions if f"'{step}'" in c}
		# KPA Paid shows the grid with only the shared container columns.
		self.assertEqual(used, set(CONTAINER_UPDATE_STEPS) - {"KPA Paid"})

	def test_task_fields_follow_the_stamp(self):
		by_name = {f["fieldname"]: f for f in _json("custom", "task.json")["custom_fields"]}
		for fieldname in ("custom_container_updates", "custom_section_container_updates"):
			self.assertEqual(by_name[fieldname]["depends_on"], CONTAINER_UPDATES_DEPENDS_ON)
		self.assertIn("'Book Trucks'", by_name["custom_not_emptied_reason"]["depends_on"])
		self.assertIn("'Field Clearance'", by_name["custom_section_field_clearance"]["depends_on"])

	def test_template_options_are_the_steps(self):
		fields = _json("doctype", "cgm_task_template_item", "cgm_task_template_item.json")["fields"]
		options = next(f for f in fields if f["fieldname"] == "container_step")["options"]
		self.assertEqual([o for o in options.split("\n") if o], list(CONTAINER_STEPS))

	def test_sea_import_seed_marks_every_step_once(self):
		steps = [row["container_step"] for row in seed.sea_import_tasks() if row.get("container_step")]
		self.assertEqual(sorted(steps), sorted(CONTAINER_STEPS))
