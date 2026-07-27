# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import unittest
import unittest.mock

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
	build_lp_project_reference,
	container_qty_size_segment,
	is_lp_project_reference,
	package_quantity_segment,
	project_reference_inputs_changed,
	refresh_project_reference_from_fields,
)


class TestProjectNaming(unittest.TestCase):
	def test_recognizes_legacy_and_new_formats(self):
		self.assertTrue(is_lp_project_reference("LP 3X20-1/0109"))
		self.assertTrue(is_lp_project_reference("PO-99 / 3X20 / 1"))
		self.assertTrue(is_lp_project_reference("PO-99 / 10 Cartons"))
		self.assertFalse(is_lp_project_reference("Shipment - Foo"))
		self.assertFalse(is_lp_project_reference(""))

	def test_fcl_reference_format(self):
		project = frappe._dict(
			custom_client_refrence_no="PO-99",
			custom_cargo_type="FCL",
			custom_quantity="3 x 20FT",
			custom_batch_no="1",
			custom_number_of_packages=None,
			custom_package_type=None,
			meta=frappe._dict(has_field=lambda *_a, **_k: False),
		)
		self.assertEqual(container_qty_size_segment(project), "3X20")
		self.assertEqual(build_lp_project_reference(project), "PO-99 / 3X20 / 1")
		self.assertEqual(build_lp_project_reference(project, sequence=2), "PO-99 / 3X20 / 1 / 2")

	def test_lcl_reference_format(self):
		project = frappe._dict(
			custom_client_refrence_no="PO-99",
			custom_cargo_type="LCL",
			custom_quantity=None,
			custom_batch_no=None,
			custom_number_of_packages="10",
			custom_package_type="Cartons",
			meta=frappe._dict(has_field=lambda *_a, **_k: False),
		)
		self.assertEqual(package_quantity_segment(project), "10 Cartons")
		self.assertEqual(build_lp_project_reference(project), "PO-99 / 10 Cartons")

	def test_requires_client_reference(self):
		project = frappe._dict(
			custom_client_refrence_no="",
			custom_cargo_type="FCL",
			custom_quantity="2 x 40FT",
			custom_batch_no="1",
			meta=frappe._dict(has_field=lambda *_a, **_k: False),
		)
		with self.assertRaises(frappe.ValidationError):
			build_lp_project_reference(project)

	def test_refresh_reference_when_batch_changes(self):
		project = frappe._dict(
			name="PROJ-TEST-1",
			is_new=lambda: False,
			custom_client_refrence_no="PO-99",
			custom_cargo_type="FCL",
			custom_quantity="3 x 20FT",
			custom_batch_no="5",
			custom_number_of_packages=None,
			custom_package_type=None,
			project_name="PO-99 / 3X20 / 1",
			custom_project_reference="PO-99 / 3X20 / 1",
			meta=frappe._dict(
				has_field=lambda field, *_a, **_k: field
				in {
					"custom_client_refrence_no",
					"custom_batch_no",
					"custom_cargo_type",
					"custom_quantity",
					"custom_number_of_packages",
					"custom_package_type",
					"custom_project_reference",
				}
			),
		)
		prev = frappe._dict(
			custom_client_refrence_no="PO-99",
			custom_batch_no="1",
			custom_cargo_type="FCL",
			custom_quantity="3 x 20FT",
			custom_number_of_packages=None,
			custom_package_type=None,
		)
		project.get_doc_before_save = lambda: prev
		project.has_value_changed = lambda field: field == "custom_batch_no"

		self.assertTrue(project_reference_inputs_changed(project))
		with unittest.mock.patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.project_naming.allocate_unique_lp_project_reference",
			return_value="PO-99 / 3X20 / 5",
		):
			reference = refresh_project_reference_from_fields(project)
		self.assertEqual(reference, "PO-99 / 3X20 / 5")
		self.assertEqual(project.project_name, "PO-99 / 3X20 / 5")
		self.assertEqual(project.custom_project_reference, "PO-99 / 3X20 / 5")
