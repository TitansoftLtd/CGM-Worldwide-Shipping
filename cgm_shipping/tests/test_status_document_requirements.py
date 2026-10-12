"""Documents a shipment needs before a status come from Settings, not code.

Documents Received used to require CI and PKL from a hardcoded list. It now uses
Settings > Shipment status documents: a status maps to Document Type stages, and
each row says whether the documents must also be verified.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import project as p


def _project(rows):
	return frappe._dict(custom_mode_of_transport="Sea", custom_shipment_documents=[frappe._dict(r) for r in rows])


def _missing(rows, requirements, types=("CI", "PKL")):
	with (
		patch.object(p, "get_stage_requirements", return_value=requirements),
		patch.object(p, "_required_document_types", return_value=list(types)),
		patch.object(p, "get_documents", side_effect=lambda doc: doc.custom_shipment_documents),
	):
		return p.documents_missing_for_status(_project(rows), "Documents Received")


class TestDocumentsMissingForStatus(unittest.TestCase):
	def test_no_settings_row_means_no_requirement(self):
		self.assertEqual(_missing([], {}), ([], []))

	def test_attached_unverified_is_enough_when_verification_is_off(self):
		rows = [
			{"document_type": "CI", "attachment": "/files/ci.pdf", "status": "Uploaded"},
			{"document_type": "PKL", "attachment": "/files/pkl.pdf", "status": "Uploaded"},
		]
		self.assertEqual(_missing(rows, {"Documents Received": [("Client documents", False)]}), ([], []))

	def test_missing_and_unverified_documents_are_reported(self):
		rows = [
			{"document_type": "CI", "attachment": "/files/ci.pdf", "status": "Uploaded"},
			{"document_type": "PKL", "attachment": "", "status": "Missing"},
		]
		self.assertEqual(
			_missing(rows, {"Documents Received": [("Client documents", True)]}), (["PKL"], ["CI"])
		)

	def test_other_statuses_are_not_affected(self):
		with patch.object(p, "get_stage_requirements", return_value={"Pre-clearance": [("IDF & UCR", True)]}):
			self.assertEqual(p.documents_missing_for_status(_project([]), "Documents Received"), ([], []))


class TestProjectClosureDocuments(unittest.TestCase):
	"""Closure uses the Completed rows in Settings, not every Default Required type."""

	def _close(self, missing):
		doc = frappe._dict(name="PROJ-TEST", custom_shipment_status="Completed", custom_permit_register=[])
		doc.get_doc_before_save = lambda: frappe._dict(custom_shipment_status="Containers Returned")
		doc.meta = frappe._dict(has_field=lambda field: False)
		with (
			patch.object(p, "runs_sea_import_workflow", return_value=False),
			patch.object(frappe, "get_all", return_value=[]),
			patch.object(p, "documents_missing_for_status", return_value=missing) as docs,
			patch.object(frappe.db, "exists", return_value=True),
		):
			p.enforce_project_closure_on_workflow_change(doc)
		docs.assert_called_once_with(doc, "Completed")

	def test_closes_when_settings_documents_are_in(self):
		self._close(([], []))

	def test_lists_missing_documents_with_other_blockers(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self._close((["BL"], ["CI"]))
		self.assertIn("Attach documents: BL", str(caught.exception))
		self.assertIn("Verify documents: CI", str(caught.exception))

	def test_status_gate_leaves_completed_to_closure(self):
		doc = frappe._dict(custom_shipment_status="Completed")
		doc.get_doc_before_save = lambda: frappe._dict(custom_shipment_status="Containers Returned")
		with patch.object(p, "documents_missing_for_status") as docs:
			p.enforce_document_gate_on_workflow_change(doc)
		docs.assert_not_called()
