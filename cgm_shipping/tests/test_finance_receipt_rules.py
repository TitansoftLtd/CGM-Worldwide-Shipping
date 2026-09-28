"""The receipt waits only while CGM Shipping Settings ask it to.

The receipt is the one document CGM cannot produce itself. A client who pays his
own entry slip often never sends the proof back (TASK-2026-00471), and the
shipping line does not always issue a receipt for a payment CGM has already
evidenced with its bank POP (TASK-2026-01058). Both waits used to be hardcoded,
so a finished payment sat Open until someone chased a third party.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import application_finance as af
from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
	APPLICATION_FINANCE_PROFILES,
	can_complete_application_finance_task,
	receipt_required,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_FINANCE_FIELD

ENTRY = APPLICATION_FINANCE_PROFILES["Entry Application"]
SHIPPING_LINE = APPLICATION_FINANCE_PROFILES["Shipping Line Application"]


class _TaskStub(frappe._dict):
	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.meta = frappe._dict(has_field=lambda _f: True)
		self.name = kwargs.get("name", "TASK-TEST")
		self.is_new = lambda: False
		self.setdefault("status", "Open")
		self.setdefault(TASK_FINANCE_FIELD, [])

	def append(self, fieldname, row):
		self.setdefault(fieldname, []).append(frappe._dict(row))


def _rules(**kwargs):
	"""Patch Settings > Finance receipts with the given payment-kind rows."""
	return patch.object(af, "finance_receipt_rules", return_value=kwargs)


def _paid_entry_task(receipt=None, verified=0, client_pays=0):
	task = _TaskStub(
		name="TASK-ENTRY-FIN",
		custom_task_role="Finance Payment",
		custom_payment_kind="ENTRY_SLIP",
		custom_client_paid_directly=client_pays,
	)
	task.append(
		TASK_FINANCE_FIELD,
		{
			"line_type": "Invoice",
			"line_label": "Entry Slip Invoice",
			"attachment": "/files/entry-invoice.pdf",
			"verified": 1,
			"journal_entry": None if client_pays else "ACC-JV-2026-00001",
			"client_paid_directly": client_pays,
		},
	)
	task.append(
		TASK_FINANCE_FIELD,
		{
			"line_type": "Receipt",
			"line_label": "Entry Slip POP",
			"attachment": receipt,
			"verified": verified,
		},
	)
	return task


class TestReceiptRequired(unittest.TestCase):
	def test_no_rule_keeps_the_built_in_behaviour(self):
		with _rules():
			self.assertEqual(
				receipt_required(_paid_entry_task(), ENTRY),
				ENTRY.requires_receipt_verification,
			)

	def test_company_pays_reads_the_company_column(self):
		with _rules(ENTRY_SLIP={"required_when_company_pays": 1, "required_when_client_pays": 0}):
			self.assertTrue(receipt_required(_paid_entry_task(), ENTRY))

	def test_client_pays_reads_the_client_column(self):
		with _rules(ENTRY_SLIP={"required_when_company_pays": 1, "required_when_client_pays": 0}):
			self.assertFalse(receipt_required(_paid_entry_task(client_pays=1), ENTRY))

	def test_a_client_paid_invoice_row_counts_as_client_pays(self):
		"""Finance ticks Client will pay on the row; the task flag syncs later."""
		task = _paid_entry_task()
		task[TASK_FINANCE_FIELD][0].client_paid_directly = 1
		with _rules(ENTRY_SLIP={"required_when_company_pays": 1, "required_when_client_pays": 0}):
			self.assertFalse(receipt_required(task, ENTRY))

	def test_the_rule_is_per_payment_kind(self):
		with _rules(KPA={"required_when_company_pays": 0, "required_when_client_pays": 0}):
			self.assertEqual(
				receipt_required(_paid_entry_task(), ENTRY),
				ENTRY.requires_receipt_verification,
			)


class TestFinanceTaskCompletes(unittest.TestCase):
	def test_client_paid_entry_completes_without_the_receipt(self):
		with _rules(ENTRY_SLIP={"required_when_company_pays": 1, "required_when_client_pays": 0}):
			self.assertTrue(
				can_complete_application_finance_task(_paid_entry_task(client_pays=1), ENTRY)
			)

	def test_company_paid_entry_still_waits_for_the_receipt(self):
		with _rules(ENTRY_SLIP={"required_when_company_pays": 1, "required_when_client_pays": 0}):
			self.assertFalse(can_complete_application_finance_task(_paid_entry_task(), ENTRY))

	def test_an_attached_receipt_is_still_verified_before_completion(self):
		task = _paid_entry_task(receipt="/files/duty-pop.pdf", verified=0)
		with _rules(ENTRY_SLIP={"required_when_company_pays": 1, "required_when_client_pays": 0}):
			self.assertFalse(can_complete_application_finance_task(task, ENTRY))


class TestShippingLineKeepsItsPop(unittest.TestCase):
	def _shipping_line_task(self, pop=None, receipt=None):
		task = _TaskStub(
			name="TASK-SL-FIN",
			custom_task_role="Finance Payment",
			custom_payment_kind="Shipping Line",
		)
		task.append(
			TASK_FINANCE_FIELD,
			{
				"line_type": "Invoice",
				"line_label": "Shipping Line Invoice",
				"attachment": "/files/sl-invoice.pdf",
				"verified": 1,
				"journal_entry": "ACC-JV-2026-00002",
			},
		)
		task.append(
			TASK_FINANCE_FIELD,
			{"line_type": "POP", "line_label": "Shipping Line POP", "attachment": pop},
		)
		task.append(
			TASK_FINANCE_FIELD,
			{
				"line_type": "Receipt",
				"line_label": "Shipping Line Receipt",
				"attachment": receipt,
				"verified": 1 if receipt else 0,
			},
		)
		return task

	def test_invoice_and_pop_are_enough(self):
		with _rules(
			**{"Shipping Line": {"required_when_company_pays": 0, "required_when_client_pays": 0}}
		):
			task = self._shipping_line_task(pop="/files/sl-pop.pdf")
			self.assertTrue(can_complete_application_finance_task(task, SHIPPING_LINE))

	def test_the_pop_still_gates(self):
		with _rules(
			**{"Shipping Line": {"required_when_company_pays": 0, "required_when_client_pays": 0}}
		):
			task = self._shipping_line_task(receipt="/files/sl-receipt.pdf")
			self.assertFalse(can_complete_application_finance_task(task, SHIPPING_LINE))

	def test_ticking_the_rule_back_on_restores_the_wait(self):
		with _rules(
			**{"Shipping Line": {"required_when_company_pays": 1, "required_when_client_pays": 0}}
		):
			task = self._shipping_line_task(pop="/files/sl-pop.pdf")
			self.assertFalse(can_complete_application_finance_task(task, SHIPPING_LINE))


class TestReceiptDoesNotWaitForThePop(unittest.TestCase):
	"""Documentation used to be told: "Wait for Finance/client to attach the
	Shipping Line POP before uploading the Shipping Line Receipt." The line's
	receipt and CGM's bank advice arrive independently, and holding one for the
	other stalled the pair (TASK-2026-01058).
	"""

	def _application_task_attaching_a_receipt(self):
		task = _TaskStub(
			name="TASK-SL-APP",
			custom_task_role="Documentation",
			custom_payment_kind=None,
			project="PROJ-TEST",
		)
		task.append(
			TASK_FINANCE_FIELD,
			{"line_type": "POP", "line_label": "Shipping Line POP", "attachment": None},
		)
		task.append(
			TASK_FINANCE_FIELD,
			{
				"line_type": "Receipt",
				"line_label": "Shipping Line Receipt",
				"attachment": "/files/sl-receipt.pdf",
				"verified": 0,
			},
		)
		task.get_doc_before_save = lambda: None
		return task

	def test_the_receipt_may_be_attached_first(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import (
			document_responsibilities as dr,
		)

		task = self._application_task_attaching_a_receipt()
		was = frappe.session.user
		frappe.session.user = "documentation@example.com"  # Administrator skips the checks
		self.addCleanup(lambda: setattr(frappe.session, "user", was))
		with (
			patch.object(af, "task_matches_application_workflow", return_value=True),
			patch.object(af, "task_has_finance_table", return_value=True),
			patch.object(af, "task_matches_application", return_value=True),
			patch.object(af, "task_matches_application_finance", return_value=False),
			patch.object(dr, "flow_for_profile", return_value=None),
			patch.object(dr, "user_has_responsibility", return_value=True),
		):
			# No POP anywhere, yet the receipt upload goes through.
			af.enforce_application_finance_line_permissions(task, SHIPPING_LINE)


class TestAnAttachedReceiptIsAlwaysChecked(unittest.TestCase):
	"""Not required does not mean unread: if one arrives, Finance still verifies it."""

	def test_an_unverified_receipt_holds_the_task_even_when_not_required(self):
		task = _paid_entry_task(receipt="/files/duty-pop.pdf", verified=0, client_pays=1)
		with _rules(ENTRY_SLIP={"required_when_company_pays": 1, "required_when_client_pays": 0}):
			self.assertFalse(can_complete_application_finance_task(task, ENTRY))

	def test_verifying_it_releases_the_task(self):
		task = _paid_entry_task(receipt="/files/duty-pop.pdf", verified=1, client_pays=1)
		with _rules(ENTRY_SLIP={"required_when_company_pays": 1, "required_when_client_pays": 0}):
			self.assertTrue(can_complete_application_finance_task(task, ENTRY))

	def test_no_receipt_at_all_is_fine(self):
		task = _paid_entry_task(client_pays=1)
		with _rules(ENTRY_SLIP={"required_when_company_pays": 1, "required_when_client_pays": 0}):
			self.assertTrue(can_complete_application_finance_task(task, ENTRY))


class TestTheRowIsNamedAsOpsNamedIt(unittest.TestCase):
	"""Ops renamed UCR's receipt charge to "UCR POP" in Desk - 130 rows read that way.
	A message quoting the built-in "UCR Receipt" sent people looking for a row that
	is not on the form.
	"""

	def test_the_row_label_wins(self):
		task = _paid_entry_task()
		self.assertEqual(af.receipt_label_for(task, ENTRY), "Entry Slip POP")

	def test_it_falls_back_to_the_charge_item(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import clearance_charge_item as cci

		task = _paid_entry_task()
		task[TASK_FINANCE_FIELD][1].line_label = None
		with (
			patch.object(cci, "get_clearance_charge_item", return_value="UCR POP"),
			patch.object(cci, "get_charge_item_label", return_value="UCR POP"),
		):
			self.assertEqual(af.receipt_label_for(task, ENTRY), "UCR POP")

	def test_it_falls_back_to_the_profile_when_nothing_is_configured(self):
		task = _paid_entry_task()
		task[TASK_FINANCE_FIELD][1].line_label = None
		from cgm_shipping.cgm_worldwide_shipping.customizations import clearance_charge_item as cci

		with (
			patch.object(cci, "get_clearance_charge_item", return_value=None),
			patch.object(cci, "get_charge_item_label", return_value=""),
		):
			self.assertEqual(af.receipt_label_for(task, ENTRY), ENTRY.receipt_label)


class TestSeedingDoesNotUndoARename(unittest.TestCase):
	"""Seeding checked the charge name alone, so a Desk rename came back as a second
	active charge for the same payment kind (UCR POP + UCR Receipt).
	"""

	def test_a_covered_pair_is_left_alone(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import clearance_charge_item as cci

		spec = {"charge_name": "UCR Receipt", "line_type": "Receipt", "payment_kind": "UCR"}
		with patch.object(frappe.db, "exists", return_value="UCR POP"):
			self.assertTrue(cci._pair_already_covered(spec))
		with patch.object(frappe.db, "exists", return_value=None):
			self.assertFalse(cci._pair_already_covered(spec))

	def test_the_original_charge_wins_over_a_later_duplicate(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import clearance_charge_item as cci

		seen = {}

		def get_value(doctype, filters, fieldname, **kwargs):
			seen["order_by"] = kwargs.get("order_by")
			return "UCR POP"

		with (
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe.db, "get_value", side_effect=get_value),
		):
			self.assertEqual(cci.get_clearance_charge_item("UCR", "Receipt"), "UCR POP")
		self.assertEqual(seen["order_by"], "creation asc")


class TestSavingItByHandAgreesWithTheGate(unittest.TestCase):
	"""Finance ticks Client will pay on the invoice row; the task-level flag only
	catches up on the next save. The completion gate accepted that, the save path did
	not, so a finished payment refused to be marked Completed (TASK-2026-00471).
	"""

	def _settled_task(self):
		task = _paid_entry_task(client_pays=0)
		task[TASK_FINANCE_FIELD][0].journal_entry = None
		task[TASK_FINANCE_FIELD][0].client_paid_directly = 1  # on the row, not the task
		task.project = "PROJ-TEST"
		task.status = "Completed"
		return task

	def _validate(self, task, settled):
		from cgm_shipping.cgm_worldwide_shipping.customizations import (
			workflow_application_finance as waf,
		)

		with (
			patch.object(waf, "is_application_payment_task_doc", return_value=True),
			patch.object(waf, "get_application_task", return_value=None),
			patch.object(waf, "seed_application_finance_lines"),
			patch.object(af, "all_invoice_lines_settled", return_value=settled),
			patch.object(af, "finance_receipt_rules", return_value={}),
			patch.object(
				af, "receipt_required", return_value=False
			),
		):
			waf.validate_finance_application_payment_task(task, ENTRY)

	def test_a_row_settled_payment_may_be_completed(self):
		self._validate(self._settled_task(), settled=True)

	def test_an_unsettled_payment_is_still_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._validate(self._settled_task(), settled=False)
