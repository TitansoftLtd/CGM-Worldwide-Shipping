"""A Project keeps edits to fields it got from its Bill of Lading.

before_save copied the BL's vessel, shipping line, weights and goods description
back onto the Project on every save, so editing any of them on a Project with a
BL and clicking Save silently restored the BL value (PROJ-0078 / PROJ-0079 /
PROJ-0080). BL values now land when the BL is first linked or swapped.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import shipment


class _Doc(frappe._dict):
	def __init__(self, doctype, bl, bl_changed):
		super().__init__(doctype=doctype, custom_bill_of_lading=bl)
		self._bl_changed = bl_changed

	def has_value_changed(self, fieldname):
		return self._bl_changed if fieldname == "custom_bill_of_lading" else False


class TestBlFieldsOnSave(unittest.TestCase):
	def _save(self, doc):
		with (
			patch.object(
				shipment,
				"get_bl_config",
				return_value={"opportunity_bl_field": "custom_bill_of_lading"},
			),
			patch.object(shipment, "sync_cargo_type_from_linked_bl"),
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe, "get_doc", return_value=frappe._dict(name="BL-1")),
			patch.object(shipment, "apply_bl_fields_to_doc") as apply,
		):
			shipment.sync_preshipment_containers_from_bl(doc)
		return apply.called

	def test_project_save_keeps_edited_bl_fields(self):
		self.assertFalse(self._save(_Doc("Project", "BL-1", bl_changed=False)))

	def test_linking_or_swapping_the_bl_pulls_its_values(self):
		# Also covers a new Project: has_value_changed is True with no saved copy.
		self.assertTrue(self._save(_Doc("Project", "BL-1", bl_changed=True)))

	def test_opportunity_still_follows_its_bl(self):
		self.assertTrue(self._save(_Doc("Opportunity", "BL-1", bl_changed=False)))
