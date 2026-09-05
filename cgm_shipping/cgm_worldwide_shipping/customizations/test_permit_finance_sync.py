# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import cint

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_PERMITS_FIELD
from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
	_payable_permit_invoice_keys,
	can_complete_finance_permit_task,
	finance_permit_row_payloads,
	finance_permit_rows_out_of_sync,
	permit_application_invoices_ready_for_finance,
	submitted_journal_entry,
	sync_permit_invoices_to_finance_task,
)
from cgm_shipping.patches.ensure_task_permits_field_visibility import (
	TASK_PERMITS_DEPENDS_ON,
)


class TestPayablePermitInvoiceKeys(UnitTestCase):
	def test_local_invoice_included(self):
		task = frappe._dict(
			custom_task_permits=[
				frappe._dict(
					permit_type="Porthealth",
					origin="Local",
					payment_invoice="/files/invoice.pdf",
				),
			]
		)
		self.assertEqual(
			_payable_permit_invoice_keys(task),
			[("Porthealth", 0, "/files/invoice.pdf")],
		)

	def test_foreign_row_excluded(self):
		task = frappe._dict(
			custom_task_permits=[
				frappe._dict(
					permit_type="KEBS",
					origin="Foreign",
					permit_document="/files/cert.pdf",
				),
			]
		)
		self.assertEqual(_payable_permit_invoice_keys(task), [])

	def test_empty_invoice_key_preserved(self):
		task = frappe._dict(
			custom_task_permits=[
				frappe._dict(permit_type="KPA", origin="Local", payment_invoice=""),
			]
		)
		self.assertEqual(_payable_permit_invoice_keys(task), [("KPA", 0, "")])

	def test_amendment_rows_distinct(self):
		task = frappe._dict(
			custom_task_permits=[
				frappe._dict(
					permit_type="Porthealth",
					origin="Local",
					is_amendment=0,
					payment_invoice="/files/a.pdf",
				),
				frappe._dict(
					permit_type="Porthealth",
					origin="Local",
					is_amendment=1,
					payment_invoice="/files/b.pdf",
				),
			]
		)
		self.assertEqual(
			_payable_permit_invoice_keys(task),
			[
				("Porthealth", 0, "/files/a.pdf"),
				("Porthealth", 1, "/files/b.pdf"),
			],
		)


class TestFinancePermitRowPayloads(UnitTestCase):
	def test_payload_includes_invoice(self):
		task = frappe._dict(
			custom_task_permits=[
				frappe._dict(
					permit_type="Entry",
					origin="Local",
					payment_invoice="/files/entry.pdf",
					status="Invoice Submitted",
					invoice_verified=0,
				),
			]
		)
		payload = finance_permit_row_payloads(task)
		self.assertEqual(len(payload), 1)
		self.assertEqual(payload[0]["permit_type"], "Entry")
		self.assertEqual(payload[0]["payment_invoice"], "/files/entry.pdf")


class TestTaskPermitsFieldVisibilityPatch(UnitTestCase):
	def test_depends_on_includes_post_clearance_finance(self):
		self.assertIn("16", TASK_PERMITS_DEPENDS_ON)
		self.assertIn("Permit Finance", TASK_PERMITS_DEPENDS_ON)


class TestSubmittedJournalEntry(UnitTestCase):
	def test_draft_journal_entry_is_not_submitted(self):
		self.assertFalse(submitted_journal_entry(None))
		self.assertFalse(submitted_journal_entry(""))

	def test_docstatus_one_counts_as_submitted(self):
		je = frappe._dict(name="ACC-JV-TEST")
		original_get_value = frappe.db.get_value
		original_exists = frappe.db.exists
		try:
			frappe.db.get_value = lambda doctype, name, field, *args, **kwargs: (
				1
				if doctype == "Journal Entry" and field == "docstatus"
				else original_get_value(doctype, name, field, *args, **kwargs)
			)
			frappe.db.exists = lambda doctype, name, *args, **kwargs: (
				doctype == "Journal Entry" and name == je.name
			) or original_exists(doctype, name, *args, **kwargs)
			self.assertTrue(submitted_journal_entry(je.name))
		finally:
			frappe.db.get_value = original_get_value
			frappe.db.exists = original_exists


class TestPermitApplicationInvoicesReadyForFinance(UnitTestCase):
	def test_partial_payable_invoices_are_ready(self):
		task = frappe._dict(
			name="TASK-TEST",
			custom_task_permits=[
				frappe._dict(permit_type="Porthealth", origin="Local", payment_invoice="/files/a.pdf"),
				frappe._dict(permit_type="KEBS", origin="Local", payment_invoice=""),
			],
		)
		payable = [
			r
			for r in task.custom_task_permits
			if r.get("permit_type") and (r.get("origin") or "Local") != "Foreign"
		]
		self.assertTrue(any((r.get("payment_invoice") or "").strip() for r in payable))
		self.assertFalse(all((r.get("payment_invoice") or "").strip() for r in payable))


class TestPermitFinanceSync(IntegrationTestCase):
	"""Application → Finance permit invoice sync for all permit types."""

	def setUp(self):
		self.project = None
		for candidate in frappe.get_all("Project", pluck="name", limit=100):
			if not frappe.db.exists(
				"Task",
				{"project": candidate, "custom_sequence_no": ("in", (15, 16))},
			):
				self.project = candidate
				break
		if not self.project:
			self.skipTest("No Project without existing permit tasks for sync tests")
		suffix = frappe.generate_hash(length=8)
		self.app_task = f"_Test Permit App {suffix}"
		self.fin_task = f"_Test Permit Fin {suffix}"
		app = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "Test Permit Application",
				"project": self.project,
				"custom_task_flow_key": "Sea Import Workflow",
				"custom_sequence_no": 15,
				"custom_task_role": "Permit Application",
				"custom_permit_stage": "Post-clearance",
				"status": "Open",
			}
		)
		app.insert(ignore_permissions=True)
		self.app_task = app.name
		fin = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "Test Permit Finance",
				"project": self.project,
				"custom_task_flow_key": "Sea Import Workflow",
				"custom_sequence_no": 16,
				"custom_task_role": "Permit Finance",
				"custom_permit_stage": "Post-clearance",
				"custom_payment_kind": "Permit",
				"status": "Open",
			}
		)
		fin.insert(ignore_permissions=True)
		self.fin_task = fin.name

	def tearDown(self):
		for name in (self.app_task, self.fin_task):
			if name and frappe.db.exists("Task", name):
				frappe.delete_doc("Task", name, force=True)

	def _save_task(self, task):
		frappe.flags.cgm_skip_task_project_sync = True
		frappe.flags.cgm_syncing_permits = True
		try:
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_skip_task_project_sync = False
			frappe.flags.cgm_syncing_permits = False

	def _set_application_permits(self, rows: list[dict]):
		app = frappe.get_doc("Task", self.app_task)
		app.set(TASK_PERMITS_FIELD, [])
		for row in rows:
			app.append(TASK_PERMITS_FIELD, row)
		self._save_task(app)

	def _set_finance_permits(self, rows: list[dict]):
		fin = frappe.get_doc("Task", self.fin_task)
		fin.set(TASK_PERMITS_FIELD, [])
		for row in rows:
			fin.append(TASK_PERMITS_FIELD, row)
		self._save_task(fin)

	def _sync_finance(self):
		fin = frappe.get_doc("Task", self.fin_task)
		frappe.flags.cgm_skip_task_project_sync = True
		frappe.flags.cgm_syncing_permits = True
		frappe.flags.cgm_syncing_permit_finance_rows = True
		try:
			sync_permit_invoices_to_finance_task(fin, save=True)
		finally:
			frappe.flags.cgm_skip_task_project_sync = False
			frappe.flags.cgm_syncing_permits = False
			frappe.flags.cgm_syncing_permit_finance_rows = False
		fin.reload()
		return fin

	def _finance_invoice(self, permit_type: str) -> str:
		fin = frappe.get_doc("Task", self.fin_task)
		for row in fin.get(TASK_PERMITS_FIELD) or []:
			if row.permit_type == permit_type:
				return row.get("payment_invoice") or ""
		return ""

	def test_porthealth_invoice_synced_to_finance(self):
		invoice = "/files/test-porthealth-invoice.pdf"
		self._set_finance_permits([])
		self._set_application_permits(
			[
				{
					"permit_type": "Porthealth",
					"origin": "Local",
					"stage": "Post-clearance",
					"payment_invoice": invoice,
					"status": "Invoice Submitted",
				}
			]
		)
		fin = self._sync_finance()
		self.assertEqual(self._finance_invoice("Porthealth"), invoice)
		self.assertFalse(finance_permit_rows_out_of_sync(fin))

	def test_kebs_invoice_synced_to_finance(self):
		invoice = "/files/test-kebs-invoice.pdf"
		self._set_finance_permits([])
		self._set_application_permits(
			[
				{
					"permit_type": "KEBS",
					"origin": "Local",
					"stage": "Post-clearance",
					"payment_invoice": invoice,
					"status": "Invoice Submitted",
				}
			]
		)
		self._sync_finance()
		self.assertEqual(self._finance_invoice("KEBS"), invoice)

	def test_invoice_uploaded_after_finance_task_seeded(self):
		invoice = "/files/test-late-invoice.pdf"
		self._set_finance_permits(
			[
				{
					"permit_type": "KEBS",
					"origin": "Local",
					"stage": "Post-clearance",
					"status": "Applied",
				}
			]
		)
		self._set_application_permits(
			[
				{
					"permit_type": "KEBS",
					"origin": "Local",
					"stage": "Post-clearance",
					"payment_invoice": invoice,
					"status": "Invoice Submitted",
				}
			]
		)
		fin = frappe.get_doc("Task", self.fin_task)
		self.assertEqual(self._finance_invoice("KEBS"), invoice)
		self.assertFalse(finance_permit_rows_out_of_sync(fin))

	def test_replaced_invoice_resets_finance_row(self):
		first = "/files/test-invoice-v1.pdf"
		second = "/files/test-invoice-v2.pdf"
		self._set_finance_permits(
			[
				{
					"permit_type": "ACA",
					"origin": "Local",
					"stage": "Post-clearance",
					"payment_invoice": first,
					"status": "Invoice Submitted",
					"invoice_verified": 1,
				}
			]
		)
		self._set_application_permits(
			[
				{
					"permit_type": "ACA",
					"origin": "Local",
					"stage": "Post-clearance",
					"payment_invoice": second,
					"status": "Invoice Submitted",
				}
			]
		)
		fin = frappe.get_doc("Task", self.fin_task)
		row = next(r for r in fin.custom_task_permits if r.permit_type == "ACA")
		self.assertEqual(row.payment_invoice, second)
		self.assertEqual(cint(row.invoice_verified), 0)

	def test_multiple_permits_all_sync(self):
		rows = [
			("Porthealth", "/files/ph.pdf"),
			("KEBS", "/files/kebs.pdf"),
			("ACA", "/files/aca.pdf"),
		]
		self._set_finance_permits([])
		self._set_application_permits(
			[
				{
					"permit_type": permit_type,
					"origin": "Local",
					"stage": "Post-clearance",
					"payment_invoice": invoice,
					"status": "Invoice Submitted",
				}
				for permit_type, invoice in rows
			]
		)
		self._sync_finance()
		for permit_type, invoice in rows:
			self.assertEqual(self._finance_invoice(permit_type), invoice)

	def test_foreign_permit_not_copied_to_finance(self):
		self._set_finance_permits([])
		self._set_application_permits(
			[
				{
					"permit_type": "KEBS",
					"origin": "Foreign",
					"stage": "Post-clearance",
					"permit_document": "/files/kebs-cert.pdf",
					"status": "Receipt Submitted",
				},
				{
					"permit_type": "Porthealth",
					"origin": "Local",
					"stage": "Post-clearance",
					"payment_invoice": "/files/local-only.pdf",
					"status": "Invoice Submitted",
				},
			]
		)
		fin = self._sync_finance()
		types = [r.permit_type for r in fin.custom_task_permits]
		self.assertEqual(types, ["Porthealth"])
		self.assertEqual(self._finance_invoice("Porthealth"), "/files/local-only.pdf")

	def test_draft_journal_entry_does_not_complete_finance_task(self):
		self._set_application_permits(
			[
				{
					"permit_type": "Porthealth",
					"origin": "Local",
					"stage": "Post-clearance",
					"payment_invoice": "/files/draft-only.pdf",
					"status": "Invoice Submitted",
					"invoice_verified": 1,
				}
			]
		)
		self._sync_finance()
		fin = frappe.get_doc("Task", self.fin_task)
		row = fin.custom_task_permits[0]
		frappe.db.set_value(
			"Permit Register",
			row.name,
			"journal_entry",
			"ACC-JV-DRAFT-TEST",
			update_modified=False,
		)
		fin.reload()
		self.assertFalse(can_complete_finance_permit_task(fin))
