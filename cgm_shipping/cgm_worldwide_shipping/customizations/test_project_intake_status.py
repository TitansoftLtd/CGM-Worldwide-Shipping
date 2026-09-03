# Copyright (c) 2026, Titansoft Limited and contributors

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
	cap_workflow_status_for_intake,
	find_shipment_row_for_intake_code,
	project_has_intake_documents,
)


STATES = [
	"Draft",
	"Documents Received",
	"UCR Applied",
	"UCR Paid",
]


class TestProjectIntakeStatus(unittest.TestCase):
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.project.project_ready_for_documents_received",
		return_value=False,
	)
	def test_cap_workflow_status_stays_draft_without_intake(self, *_mocks):
		project = frappe._dict(name="PROJ-INTAKE-1")
		self.assertEqual(
			cap_workflow_status_for_intake(project, "Documents Received", STATES),
			"Draft",
		)
		self.assertEqual(
			cap_workflow_status_for_intake(project, "UCR Applied", STATES),
			"Draft",
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.project.project_ready_for_documents_received",
		return_value=True,
	)
	def test_cap_workflow_status_allows_progress_with_intake(self, *_mocks):
		project = frappe._dict(name="PROJ-INTAKE-2")
		self.assertEqual(
			cap_workflow_status_for_intake(project, "Documents Received", STATES),
			"Documents Received",
		)

	def test_intake_documents_match_link_name_not_master_code(self):
		"""CI/PKL rows link by name while Document Type.code is the long label."""
		rows = [
			frappe._dict(
				document_type="CI",
				attachment="/files/invoice.pdf",
				status="Uploaded",
			),
			frappe._dict(
				document_type="PKL",
				attachment="/files/packing-list.pdf",
				status="Uploaded",
			),
		]
		project = frappe._dict(name="PROJ-INTAKE-3")
		with (
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.project.get_documents",
				return_value=rows,
			),
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.task.get_document_type_code",
				side_effect=lambda link: {
					"CI": "Commercial Invoice",
					"PKL": "Packing List",
				}.get(link),
			),
			patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.project.get_project_shipment_documents_field",
				return_value="custom_shipment_documents",
			),
		):
			project.meta = frappe._dict(has_field=lambda _field: True)
			self.assertTrue(project_has_intake_documents(project))
			self.assertIsNotNone(find_shipment_row_for_intake_code(project, "CI"))
			self.assertIsNotNone(find_shipment_row_for_intake_code(project, "PKL"))
