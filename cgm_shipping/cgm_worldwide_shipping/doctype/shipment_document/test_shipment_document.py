# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import UnitTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_upload_metadata import (
	stamp_row_attachment_metadata,
)


class TestShipmentDocumentUploadMetadata(UnitTestCase):
	def _stamp(self, row, prev_row=None, **kwargs):
		defaults = {
			"attach_field": "final_attachment",
			"on_field": "final_document_uploaded_on",
			"by_field": "final_document_uploaded_by",
		}
		defaults.update(kwargs)
		stamp_row_attachment_metadata(row, prev_row, **defaults)

	def test_new_final_document_upload_sets_metadata(self):
		row = frappe._dict(final_attachment="/files/final.pdf")
		self._stamp(row)
		self.assertEqual(row.final_document_uploaded_by, "Administrator")
		self.assertIsNotNone(row.final_document_uploaded_on)

	def test_unchanged_final_document_keeps_metadata(self):
		row = frappe._dict(
			final_attachment="/files/final.pdf",
			final_document_uploaded_by="user@example.com",
			final_document_uploaded_on="2026-01-01 10:00:00",
		)
		prev = frappe._dict(final_attachment="/files/final.pdf")
		self._stamp(row, prev)
		self.assertEqual(row.final_document_uploaded_by, "user@example.com")
		self.assertEqual(row.final_document_uploaded_on, "2026-01-01 10:00:00")

	def test_replaced_final_document_refreshes_metadata(self):
		row = frappe._dict(
			final_attachment="/files/final-v2.pdf",
			final_document_uploaded_by="user@example.com",
			final_document_uploaded_on="2026-01-01 10:00:00",
		)
		prev = frappe._dict(final_attachment="/files/final.pdf")
		self._stamp(row, prev)
		self.assertEqual(row.final_document_uploaded_by, "Administrator")
		self.assertNotEqual(row.final_document_uploaded_on, "2026-01-01 10:00:00")

	def test_removed_final_document_clears_metadata(self):
		row = frappe._dict(
			final_attachment="",
			final_document_uploaded_by="user@example.com",
			final_document_uploaded_on="2026-01-01 10:00:00",
		)
		prev = frappe._dict(final_attachment="/files/final.pdf")
		self._stamp(row, prev)
		self.assertIsNone(row.final_document_uploaded_by)
		self.assertIsNone(row.final_document_uploaded_on)

	def test_no_final_document_leaves_empty_metadata(self):
		row = frappe._dict(
			final_attachment="",
			final_document_uploaded_by=None,
			final_document_uploaded_on=None,
		)
		self._stamp(row)
		self.assertIsNone(row.final_document_uploaded_by)
		self.assertIsNone(row.final_document_uploaded_on)

	def test_new_draft_document_upload_sets_metadata(self):
		row = frappe._dict(draft_documents="/files/draft.pdf")
		self._stamp(
			row,
			attach_field="draft_documents",
			on_field="draft_documents_uploaded_on",
			by_field="draft_documents_uploaded_by",
		)
		self.assertEqual(row.draft_documents_uploaded_by, "Administrator")
		self.assertIsNotNone(row.draft_documents_uploaded_on)

	def test_unchanged_draft_document_keeps_metadata(self):
		row = frappe._dict(
			draft_documents="/files/draft.pdf",
			draft_documents_uploaded_by="user@example.com",
			draft_documents_uploaded_on="2026-01-01 10:00:00",
		)
		prev = frappe._dict(draft_documents="/files/draft.pdf")
		self._stamp(
			row,
			prev,
			attach_field="draft_documents",
			on_field="draft_documents_uploaded_on",
			by_field="draft_documents_uploaded_by",
		)
		self.assertEqual(row.draft_documents_uploaded_by, "user@example.com")
		self.assertEqual(row.draft_documents_uploaded_on, "2026-01-01 10:00:00")

	def test_removed_draft_document_clears_metadata(self):
		row = frappe._dict(
			draft_documents="",
			draft_documents_uploaded_by="user@example.com",
			draft_documents_uploaded_on="2026-01-01 10:00:00",
		)
		prev = frappe._dict(draft_documents="/files/draft.pdf")
		self._stamp(
			row,
			prev,
			attach_field="draft_documents",
			on_field="draft_documents_uploaded_on",
			by_field="draft_documents_uploaded_by",
		)
		self.assertIsNone(row.draft_documents_uploaded_by)
		self.assertIsNone(row.draft_documents_uploaded_on)
