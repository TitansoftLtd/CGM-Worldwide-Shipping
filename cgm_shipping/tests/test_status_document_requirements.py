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
