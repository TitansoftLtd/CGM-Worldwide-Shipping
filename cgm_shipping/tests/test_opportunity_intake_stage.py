"""Opportunity intake stage is judged on the document being saved.

before_save used to re-read the Opportunity from the database, which still
holds the previous version there. A save that verified the last document
stored the old stage; the wizard then worked out the new one after the save,
and writing it back marked the just-saved form Not Saved.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import documents
from cgm_shipping.cgm_worldwide_shipping.customizations import opportunity_intake_wizard as wizard
from cgm_shipping.cgm_worldwide_shipping.customizations import opportunity_shipment as shipment

DOCS_FIELD = "custom_clients_documents"
REQUIRED = "Commercial Invoice"


class _Opportunity(frappe._dict):
	"""In-memory Opportunity: enough of Document for the stage and readiness code."""

	meta = MagicMock(has_field=lambda fieldname: True)

	def has_value_changed(self, fieldname):
		return False


def _opportunity(*, verified):
	return _Opportunity(
		name="CRM-OPP-TEST",
		custom_shipment_type="Sea Import",
		custom_mode_of_transport="Sea",
		custom_bill_of_lading="BL-TEST",
		workflow_state="Pending Approval",
		**{DOCS_FIELD: [frappe._dict(document_type=REQUIRED, attachment="/files/ci.pdf", verified=verified)]},
	)


def _not_reloaded(*args, **kwargs):
	raise AssertionError("readiness re-read the Opportunity instead of using the doc being saved")


class TestReadinessUsesDocBeingSaved(unittest.TestCase):
	def _readiness(self, doc):
		with (
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(frappe, "get_doc", _not_reloaded),
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(shipment, "get_shipment_type_flags", return_value={}),
			patch.object(shipment, "get_transport_documents_with_links", return_value=[]),
			patch.object(shipment, "has_required_transport_documents", return_value=True),
			patch.object(shipment, "has_any_transport_document", return_value=True),
			patch.object(shipment, "transport_documents_deferred", return_value=False),
			patch.object(shipment, "_opportunity_is_air", return_value=False),
			patch.object(shipment, "get_required_intake_documents", return_value=[{"document_type": REQUIRED}]),
			patch.object(documents, "get_opportunity_documents_field", return_value=DOCS_FIELD),
			patch.object(documents, "document_types_match", side_effect=lambda a, b: a == b),
			patch.object(documents, "primary_attachment", side_effect=lambda row: row.get("attachment")),
			patch.object(documents, "is_shipment_document_verified", side_effect=lambda row: bool(row.get("verified"))),
		):
			return shipment.evaluate_start_shipment_readiness(doc.name, doc=doc)

	def test_verified_in_this_save_counts(self):
		self.assertTrue(self._readiness(_opportunity(verified=1))["ok"])

	def test_unverified_in_this_save_blocks(self):
		readiness = self._readiness(_opportunity(verified=0))
		self.assertFalse(readiness["ok"])
		self.assertEqual(readiness["unverified_documents"], [REQUIRED])


class TestStageSyncHandsOverTheDoc(unittest.TestCase):
	def _stage(self, ready):
		doc = _opportunity(verified=int(ready))
		readiness = MagicMock(return_value={"ok": ready})
		with (
			patch.object(wizard, "get_shipment_type_flags", return_value={}),
			patch.object(wizard, "has_any_transport_document", return_value=True),
			patch.object(wizard, "transport_documents_deferred", return_value=False),
			patch.object(wizard, "evaluate_start_shipment_readiness", readiness),
		):
			wizard.sync_opportunity_intake_stage(doc)
		readiness.assert_called_once_with(doc.name, doc=doc)
		return doc.custom_intake_stage

	def test_ready_moves_to_authorization(self):
		self.assertEqual(self._stage(True), wizard.STAGE_AUTHORIZATION)

	def test_not_ready_stays_on_documents(self):
		self.assertEqual(self._stage(False), wizard.STAGE_DOCUMENTS)
