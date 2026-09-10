"""Container task sequence numbers have one source: code defaults, overridable in Settings.

Settings and code had drifted apart: the ETA step was read under a fieldname
Settings does not have (so its setting did nothing), the Settings JSON carried
defaults that disagreed with the code (11/18/20... against 12/17/19...), and
some callers read the code defaults directly, ignoring Settings altogether.
"""

import json
import os
import unittest
from unittest.mock import patch

import frappe

import cgm_shipping
from cgm_shipping.cgm_worldwide_shipping.customizations import container_tracker, task_container_updates
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	BULK_CONTAINER_TASK_SEQ_FIELDS,
	CONTAINER_SPECIFIC_TASK_SEQ_FIELDS,
	CONTAINER_TASK_SEQ_DEFAULTS,
	CONTAINER_UPDATE_TASK_SEQ_FIELDS,
)

SETTINGS_JSON = os.path.join(
	os.path.dirname(cgm_shipping.__file__),
	"cgm_worldwide_shipping",
	"doctype",
	"cgm_shipping_settings",
	"cgm_shipping_settings.json",
)


def _settings_fields():
	with open(SETTINGS_JSON) as f:
		return {df["fieldname"]: df for df in json.load(f)["fields"]}


def _settings(**values):
	settings = frappe._dict(values)
	settings.meta = frappe._dict(has_field=lambda fieldname: fieldname in CONTAINER_TASK_SEQ_DEFAULTS)
	return settings


class TestSettingsFieldsMatchCode(unittest.TestCase):
	def test_every_sequence_key_is_a_settings_field(self):
		fields = _settings_fields()
		for fieldname in CONTAINER_TASK_SEQ_DEFAULTS:
			with self.subTest(fieldname=fieldname):
				self.assertIn(fieldname, fields)

	def test_settings_fields_carry_no_competing_default(self):
		fields = _settings_fields()
		for fieldname in CONTAINER_TASK_SEQ_DEFAULTS:
			with self.subTest(fieldname=fieldname):
				self.assertFalse(fields[fieldname].get("default"))

	def test_bulk_and_specific_cover_every_step_once(self):
		self.assertEqual(
			sorted(BULK_CONTAINER_TASK_SEQ_FIELDS + CONTAINER_SPECIFIC_TASK_SEQ_FIELDS),
			sorted(CONTAINER_TASK_SEQ_DEFAULTS),
		)


class TestSequenceLookup(unittest.TestCase):
	def _lookup(self, fieldname, settings):
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.utils.get_cgm_shipping_settings",
			return_value=settings,
		):
			return container_tracker.get_container_task_sequence(fieldname)

	def test_zero_falls_back_to_the_code_default(self):
		self.assertEqual(self._lookup("custom_track_eta_task_seq", _settings(custom_track_eta_task_seq=0)), 8)

	def test_setting_overrides_the_code_default(self):
		self.assertEqual(self._lookup("custom_track_eta_task_seq", _settings(custom_track_eta_task_seq=9)), 9)

