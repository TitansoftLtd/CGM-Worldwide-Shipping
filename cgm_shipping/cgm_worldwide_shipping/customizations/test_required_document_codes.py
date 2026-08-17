# Copyright (c) 2026, Titansoft Limited and contributors

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
	attached_document_codes,
	required_document_code_is_attached,
	validate_required_documents,
)


class TestRequiredDocumentCodeMatch(unittest.TestCase):
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.task.get_document_type_code",
		return_value="Inspect",
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.documents.primary_attachment",
		return_value="/files/inspect.docx",
	)
	def test_attached_codes_are_uppercased(self, *_mocks):
		task = frappe._dict(
			custom_task_documents=[frappe._dict(document_type="Inspect")],
		)
		self.assertEqual(attached_document_codes(task), {"INSPECT"})

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.task.get_document_type_code",
		return_value="Delivery Order",
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.documents.primary_attachment",
		return_value="/files/do.pdf",
	)
	def test_attached_includes_name_and_code_aliases(self, *_mocks):
		"""Settings require DO; master often uses name DO + code Delivery Order."""
		task = frappe._dict(
			custom_task_documents=[frappe._dict(document_type="DO")],
		)
		self.assertEqual(
			attached_document_codes(task),
			{"DO", "DELIVERY ORDER", "DELIVERYORDER"},
		)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.task.get_document_type_code",
		side_effect=lambda link: {
			"DO": "Delivery Order",
			"MANIFEST": "MANIFEST",
			"IDF_CERT": "IDF_CERT",
		}.get(link),
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.documents.get_document_type_link_name",
		side_effect=lambda code: {
			"DO": "DO",
			"Delivery Order": "DO",
			"MANIFEST": "MANIFEST",
			"IDF CERT": "IDF_CERT",
			"IDF_CERT": "IDF_CERT",
		}.get((code or "").strip()),
	)
	def test_required_do_matches_delivery_order_tokens(self, *_mocks):
		attached = {"DO", "DELIVERY ORDER"}
		self.assertTrue(required_document_code_is_attached("DO", attached))
		self.assertTrue(required_document_code_is_attached("Delivery Order", attached))
		self.assertFalse(required_document_code_is_attached("MANIFEST", attached))

	def test_idf_cert_stamp_matches_underscore_document_type(self):
		"""Template stamp 'IDF CERT' must match Document Type IDF_CERT."""
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			normalize_document_type_key,
		)

		attached = {"IDF_CERT", "IDFCERT"}
		self.assertEqual(normalize_document_type_key("IDF CERT"), "IDFCERT")
		self.assertTrue(required_document_code_is_attached("IDF CERT", attached))
		self.assertTrue(required_document_code_is_attached("IDF_CERT", attached))

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.task.get_required_document_codes",
		return_value=["INSPECT"],
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.task.attached_document_codes",
		return_value={"INSPECT"},
	)
	def test_validate_accepts_case_normalized_match(self, *_mocks):
		task = frappe._dict(custom_task_documents=[])
		validate_required_documents(task, 7)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.task.get_required_document_codes",
		return_value=["DO"],
	)
	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.task.attached_document_codes",
		return_value={"DO", "DELIVERY ORDER"},
	)
	def test_validate_accepts_do_when_code_is_delivery_order(self, *_mocks):
		task = frappe._dict(custom_task_documents=[])
		validate_required_documents(task, 14)
