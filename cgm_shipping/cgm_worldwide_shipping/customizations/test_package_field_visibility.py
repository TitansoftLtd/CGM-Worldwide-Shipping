# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations import package_field_visibility as vis


class TestPackageFieldVisibilityExpressions(UnitTestCase):
	def test_generated_expression_uses_configured_values(self):
		expr = vis.build_opportunity_depends_on(["Road"], ["Breakbulk"])
		self.assertIn("doc.custom_mode_of_transport=='Road'", expr)
		self.assertIn("doc.custom_cargo_type_=='Breakbulk'", expr)
		self.assertIn("doc.custom_cargo_type=='Breakbulk'", expr)
		self.assertIn("doc.custom_air_waybill", expr)

	def test_project_expression_uses_project_cargo_field(self):
		expr = vis.build_project_depends_on(["Rail"], ["Breakbulk"])
		self.assertIn("doc.custom_mode_of_transport=='Rail'", expr)
		self.assertIn("doc.custom_cargo_type=='Breakbulk'", expr)
		self.assertNotIn("custom_cargo_type_", expr)

	def test_empty_config_hides_fields(self):
		self.assertEqual(vis.build_depends_on(modes=[], cargo_types=[]), "eval:0")

	def test_changing_config_changes_expression(self):
		before = vis.build_opportunity_depends_on(["Road"], ["Breakbulk"])
		after = vis.build_opportunity_depends_on(["Rail"], ["FCL"])
		self.assertNotEqual(before, after)
		self.assertIn("=='Rail'", after)
		self.assertIn("=='FCL'", after)
		self.assertNotIn("=='Road'", after)
		self.assertNotIn("=='Breakbulk'", after)

	def test_managed_depends_on_accepts_generated_and_legacy_eval(self):
		generated = vis.build_opportunity_depends_on(["Road"], ["Breakbulk"])
		self.assertTrue(vis._is_managed_depends_on(generated))
		self.assertTrue(vis._is_managed_depends_on(""))
		self.assertTrue(vis._is_managed_depends_on("eval:0"))
		self.assertTrue(
			vis._is_managed_depends_on(
				"eval:doc.custom_mode_of_transport=='Road' || doc.custom_cargo_type_=='Breakbulk'"
			)
		)
		self.assertFalse(vis._is_managed_depends_on("eval:doc.something_else==1"))

	def test_python_module_does_not_hard_code_transport_or_cargo_names(self):
		source = Path(vis.__file__).read_text()
		self.assertNotIn("'Air'", source)
		self.assertNotIn('"Air"', source)
		self.assertNotIn("'LCL'", source)
		self.assertNotIn('"LCL"', source)


class TestPackageFieldVisibilityApply(IntegrationTestCase):
	def setUp(self):
		self._orig_depends = {
			name: frappe.db.get_value("Custom Field", name, "depends_on")
			for name, _dt in vis.PACKAGE_FIELDS
			if frappe.db.exists("Custom Field", name)
		}

	def tearDown(self):
		for fieldname, depends_on in self._orig_depends.items():
			frappe.db.set_value(
				"Custom Field", fieldname, "depends_on", depends_on, update_modified=False
			)

	def test_changing_config_rewrites_package_field_depends_on(self):
		if not frappe.db.exists("Custom Field", "Opportunity-custom_number_of_packages"):
			self.skipTest("Opportunity package Custom Field is missing")

		with patch.object(
			vis,
			"get_package_visibility_config",
			return_value={"modes": ["Road"], "cargo_types": ["Breakbulk"]},
		):
			vis.apply_package_field_depends_on(force=True)

		opportunity = frappe.db.get_value(
			"Custom Field", "Opportunity-custom_number_of_packages", "depends_on"
		)
		project = frappe.db.get_value(
			"Custom Field", "Project-custom_number_of_packages", "depends_on"
		)
		self.assertIn("doc.custom_mode_of_transport=='Road'", opportunity)
		self.assertIn("doc.custom_cargo_type_=='Breakbulk'", opportunity)
		self.assertIn("doc.custom_air_waybill", opportunity)
		self.assertIn("doc.custom_mode_of_transport=='Road'", project)
		self.assertIn("doc.custom_cargo_type=='Breakbulk'", project)

		with patch.object(
			vis,
			"get_package_visibility_config",
			return_value={"modes": ["Rail"], "cargo_types": ["FCL"]},
		):
			vis.apply_package_field_depends_on(force=True)

		opportunity = frappe.db.get_value(
			"Custom Field", "Opportunity-custom_package_type", "depends_on"
		)
		self.assertIn("doc.custom_mode_of_transport=='Rail'", opportunity)
		self.assertIn("doc.custom_cargo_type_=='FCL'", opportunity)
		self.assertNotIn("=='Road'", opportunity)
		self.assertNotIn("=='Breakbulk'", opportunity)

	def test_unmanaged_custom_field_depends_on_is_left_alone(self):
		fieldname = "Opportunity-custom_number_of_packages"
		if not frappe.db.exists("Custom Field", fieldname):
			self.skipTest("Opportunity package Custom Field is missing")
		custom = "eval:doc.party_name"
		frappe.db.set_value("Custom Field", fieldname, "depends_on", custom, update_modified=False)

		with patch.object(
			vis,
			"get_package_visibility_config",
			return_value={"modes": ["Road"], "cargo_types": []},
		):
			vis.apply_package_field_depends_on()

		self.assertEqual(
			frappe.db.get_value("Custom Field", fieldname, "depends_on"),
			custom,
		)


class TestPackageFieldVisibilitySettings(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.reload_doc("cgm_worldwide_shipping", "doctype", "cargo_type_item", force=True)
		frappe.reload_doc("cgm_worldwide_shipping", "doctype", "cgm_shipping_settings", force=True)
		frappe.clear_cache(doctype="CGM Shipping Settings")

	def setUp(self):
		if not frappe.get_meta("CGM Shipping Settings").has_field("package_visibility_modes"):
			self.skipTest("CGM Shipping Settings package visibility fields are not migrated")
		self.settings = frappe.get_single("CGM Shipping Settings")
		self._orig_modes = [
			row.mode_of_transport
			for row in (self.settings.get("package_visibility_modes") or [])
			if row.mode_of_transport
		]
		self._orig_cargos = [
			row.cargo_type
			for row in (self.settings.get("package_visibility_cargo_types") or [])
			if row.cargo_type
		]
		self._orig_depends = {
			name: frappe.db.get_value("Custom Field", name, "depends_on")
			for name, _dt in vis.PACKAGE_FIELDS
			if frappe.db.exists("Custom Field", name)
		}

	def tearDown(self):
		if not getattr(self, "_orig_depends", None):
			return
		settings = frappe.get_single("CGM Shipping Settings")
		settings.set("package_visibility_modes", [])
		settings.set("package_visibility_cargo_types", [])
		for name in self._orig_modes:
			settings.append("package_visibility_modes", {"mode_of_transport": name})
		for name in self._orig_cargos:
			settings.append("package_visibility_cargo_types", {"cargo_type": name})
		settings.flags.skip_package_visibility_apply = True
		settings.save(ignore_permissions=True)
		for fieldname, depends_on in self._orig_depends.items():
			frappe.db.set_value(
				"Custom Field", fieldname, "depends_on", depends_on, update_modified=False
			)

	def _ensure_master(self, doctype: str, fieldname: str, value: str) -> None:
		if frappe.db.exists(doctype, value):
			return
		frappe.get_doc({"doctype": doctype, fieldname: value}).insert(ignore_permissions=True)

	def _set_visibility(self, modes: list[str], cargo_types: list[str]) -> None:
		settings = frappe.get_single("CGM Shipping Settings")
		settings.set("package_visibility_modes", [])
		settings.set("package_visibility_cargo_types", [])
		for name in modes:
			settings.append("package_visibility_modes", {"mode_of_transport": name})
		for name in cargo_types:
			settings.append("package_visibility_cargo_types", {"cargo_type": name})
		settings.save(ignore_permissions=True)

	def test_saving_settings_rewrites_package_field_depends_on(self):
		self._ensure_master("Mode of Transport", "mode", "Road")
		self._ensure_master("Cargo Type", "cargo_type", "Breakbulk")
		self._set_visibility(["Road"], ["Breakbulk"])

		opportunity = frappe.db.get_value(
			"Custom Field", "Opportunity-custom_number_of_packages", "depends_on"
		)
		self.assertIn("doc.custom_mode_of_transport=='Road'", opportunity)
		self.assertIn("doc.custom_cargo_type_=='Breakbulk'", opportunity)

		self._ensure_master("Mode of Transport", "mode", "Rail")
		self._ensure_master("Cargo Type", "cargo_type", "FCL")
		self._set_visibility(["Rail"], ["FCL"])

		opportunity = frappe.db.get_value(
			"Custom Field", "Opportunity-custom_package_type", "depends_on"
		)
		self.assertIn("doc.custom_mode_of_transport=='Rail'", opportunity)
		self.assertIn("doc.custom_cargo_type_=='FCL'", opportunity)
		self.assertNotIn("=='Road'", opportunity)
		self.assertNotIn("=='Breakbulk'", opportunity)
