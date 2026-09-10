# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_DOCUMENTS_FIELD
from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
	get_effective_required_document_types,
	get_template_required_document_types,
	purge_unrequired_task_document_rows,
	seed_required_task_document_rows,
	seed_stamped_required_document_rows,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
	coerce_legacy_document_type_tokens,
	document_type_names_from_template_row,
	normalize_required_document_type_stamp,
	resolve_legacy_document_type_name,
	resolve_required_document_type_name,
)


class _TaskStub(frappe._dict):
	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.meta = frappe._dict(has_field=lambda _f: True)
		if TASK_DOCUMENTS_FIELD not in self:
			self[TASK_DOCUMENTS_FIELD] = []

	def append(self, fieldname, row):
		self.setdefault(fieldname, []).append(frappe._dict(row))

	def remove(self, row):
		self.get(TASK_DOCUMENTS_FIELD, []).remove(row)


class TestTaskDocumentSeeding(UnitTestCase):
	def test_template_entry_application_does_not_auto_seed_documents(self):
		task = _TaskStub(
			custom_task_role="Application",
			custom_payment_kind="ENTRY_SLIP",
			custom_sequence_no=7,
		)
		seed_required_task_document_rows(task)
		self.assertEqual(len(task.get(TASK_DOCUMENTS_FIELD) or []), 0)

	def test_effective_required_docs_fall_back_to_template_item(self):
		task = _TaskStub(
			custom_task_role="Application",
			custom_payment_kind="ENTRY_SLIP",
			custom_task_flow_key="Sea Transit Import workflow",
			custom_sequence_no=7,
		)
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.task.get_template_task_item",
			return_value={"required_document_type_names": ["Entry"]},
		):
			self.assertEqual(get_template_required_document_types(task), ["Entry"])
			self.assertEqual(get_effective_required_document_types(task), ["Entry"])

	def test_seed_uses_exact_document_type_name(self):
		task = _TaskStub(
			custom_task_role="Application",
			custom_payment_kind="ENTRY_SLIP",
			custom_required_document_types="Entry",
			custom_sequence_no=7,
		)
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents.frappe.db.exists",
			return_value=True,
		):
			seed_stamped_required_document_rows(task)
			types = {row.document_type for row in task.get(TASK_DOCUMENTS_FIELD) or []}
			self.assertEqual(types, {"Entry"})

	def test_purge_keeps_user_added_entry_on_application_task(self):
		task = _TaskStub(
			custom_task_role="Application",
			custom_payment_kind="ENTRY_SLIP",
			custom_sequence_no=7,
		)
		task.append(TASK_DOCUMENTS_FIELD, {"document_type": "Entry", "status": "Missing"})
		self.assertFalse(purge_unrequired_task_document_rows(task))
		types = {row.document_type for row in task.get(TASK_DOCUMENTS_FIELD) or []}
		self.assertEqual(types, {"Entry"})

	def test_purge_keeps_user_added_documents_on_document_task(self):
		task = _TaskStub(
			custom_task_role="Document",
			custom_sequence_no=10,
		)
		task.append(TASK_DOCUMENTS_FIELD, {"document_type": "exit", "status": "Missing"})
		task.append(TASK_DOCUMENTS_FIELD, {"document_type": "c2", "status": "Missing"})
		self.assertFalse(purge_unrequired_task_document_rows(task))
		types = {row.document_type for row in task.get(TASK_DOCUMENTS_FIELD) or []}
		self.assertEqual(types, {"exit", "c2"})

	def test_purge_still_removes_invoice_rows_from_clearance_table(self):
		task = _TaskStub(
			custom_task_role="Application",
			custom_payment_kind="ENTRY_SLIP",
			custom_sequence_no=7,
		)
		task.append(TASK_DOCUMENTS_FIELD, {"document_type": "Entry", "status": "Missing"})
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.task.is_invoice_clearance_document_row",
			side_effect=lambda dt: dt == "Entry",
		):
			self.assertTrue(purge_unrequired_task_document_rows(task))
		self.assertEqual(task.get(TASK_DOCUMENTS_FIELD) or [], [])

	def test_finance_task_does_not_seed_checkpoint_documents_by_global_seq(self):
		task = _TaskStub(
			custom_task_role="Finance Payment",
			custom_sequence_no=8,
			custom_requires_document_upload=0,
		)
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.documents.seed_checkpoint_task_documents_from_project",
			return_value=True,
		) as seed_checkpoint:
			seed_required_task_document_rows(task)
		seed_checkpoint.assert_not_called()
		self.assertEqual(len(task.get(TASK_DOCUMENTS_FIELD) or []), 0)

	def test_purge_removes_intake_documents_from_finance_task(self):
		task = _TaskStub(
			custom_task_role="Finance Payment",
			custom_sequence_no=8,
			custom_requires_document_upload=0,
		)
		task.append(TASK_DOCUMENTS_FIELD, {"document_type": "BL", "status": "Uploaded"})
		task.append(TASK_DOCUMENTS_FIELD, {"document_type": "COO", "status": "Uploaded"})
		task.append(TASK_DOCUMENTS_FIELD, {"document_type": "COA", "status": "Uploaded"})
		self.assertTrue(purge_unrequired_task_document_rows(task))
		self.assertEqual(task.get(TASK_DOCUMENTS_FIELD) or [], [])

	def test_purge_keeps_intake_documents_on_document_task(self):
		task = _TaskStub(
			custom_task_role="Document",
			custom_sequence_no=2,
			custom_requires_document_upload=1,
		)
		task.append(TASK_DOCUMENTS_FIELD, {"document_type": "BL", "status": "Verified"})
		task.append(TASK_DOCUMENTS_FIELD, {"document_type": "COO", "status": "Verified"})
		self.assertFalse(purge_unrequired_task_document_rows(task))
		types = {row.document_type for row in task.get(TASK_DOCUMENTS_FIELD) or []}
		self.assertEqual(types, {"BL", "COO"})

	def test_template_row_reads_table_multiselect_children(self):
		row = {
			"required_document_types": [
				{"document_type": "Entry"},
				{"document_type": "Bill of Lading"},
			]
		}
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents.frappe.db.exists",
			return_value=True,
		):
			self.assertEqual(
				document_type_names_from_template_row(row),
				["Entry", "Bill of Lading"],
			)

	def test_resolve_rejects_unknown_labels(self):
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents.frappe.db.exists",
			return_value=False,
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.documents.get_document_type_link_name",
			return_value=None,
		):
			self.assertIsNone(resolve_legacy_document_type_name("Not A Real Document"))

	def test_legacy_entry_slip_resolves_to_entry(self):
		def _exists(doctype, name):
			return doctype == "Document Type" and name == "Entry"

		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents.frappe.db.exists",
			side_effect=_exists,
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.documents.get_document_type_link_name",
			return_value=None,
		):
			self.assertEqual(resolve_legacy_document_type_name("Entry Slip"), "Entry")
			self.assertEqual(resolve_required_document_type_name("Entry Slip"), "Entry")

	def test_coerce_normalizes_mixed_legacy_stamp(self):
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents.resolve_legacy_document_type_name",
			side_effect=lambda t: "Entry" if t in ("Entry Slip", "Entry") else None,
		):
			self.assertEqual(
				normalize_required_document_type_stamp("Entry Slip, Entry"),
				"Entry",
			)


class TestFieldClearanceValidation(UnitTestCase):
	def test_accepts_any_attached_task_document(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			validate_field_clearance_task,
		)

		task = _TaskStub(custom_sequence_no=17, custom_container_step="Field Clearance")
		task.append(
			TASK_DOCUMENTS_FIELD,
			{"document_type": "DO", "attachment": "/files/delivery-order.pdf"},
		)
		validate_field_clearance_task(task)

	def test_requires_document_release_or_report(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			validate_field_clearance_task,
		)

		task = _TaskStub(custom_sequence_no=17, custom_container_step="Field Clearance")
		with self.assertRaises(frappe.ValidationError):
			validate_field_clearance_task(task)
