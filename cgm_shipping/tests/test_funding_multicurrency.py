"""Foreign-currency requests reach the ledger with the right figures.

CGM pays shipping line and KPA charges in USD. Before multicurrency every Currency
field in the chain rendered in KES whatever was meant, so a USD request had to be
converted by hand before it was typed and the approved figure carried no record of
the rate behind it.

Two things here are easy to get wrong and are the reason most of these tests exist:

* `Journal Entry Account.debit_in_account_currency` is the *account's* currency,
  not the company's. Reconciling a USD payment against a KES approval with that
  column made a fully paid row read as 0.8% disbursed.
* A rate moves between approval and payment. Closing a row on the company-currency
  figure would strand a fully paid USD row whenever the rate fell, so closure is
  decided on the foreign amount and the company-currency figure is for reporting.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import funding as F
from cgm_shipping.cgm_worldwide_shipping.customizations import multicurrency as M

BASE = "KES"


def _meta(*fields):
	known = set(fields)
	return frappe._dict(has_field=lambda f: f in known)


class _Item(frappe._dict):
	def __init__(self, **kw):
		super().__init__()
		self.idx = kw.pop("idx", 1)
		self.update(kw)


class _MR(frappe._dict):
	"""Just enough Material Request for the normaliser."""

	def __init__(self, items, multicurrency=1, request_type="Operational Expense"):
		super().__init__()
		self.company = "CGM"
		self.material_request_type = request_type
		self.custom_multicurrency = multicurrency
		self.transaction_date = "2026-10-13"
		self["items"] = items
		self.meta = _meta("custom_base_total", "custom_currency_totals")


class TestCurrencyTotals(unittest.TestCase):
	"""The per-currency figures the user asked to see on both doctypes."""

	def test_amounts_group_by_currency(self):
		totals = M.currency_totals([("KES", 100), ("USD", 10), ("KES", 50)])
		self.assertEqual(totals, {"KES": 150, "USD": 10})

	def test_currency_that_nets_to_nothing_is_dropped(self):
		self.assertEqual(M.currency_totals([("USD", 10), ("USD", -10)]), {})

	def test_blank_currency_is_ignored(self):
		self.assertEqual(M.currency_totals([("", 10), ("USD", 5)]), {"USD": 5})

	def test_company_currency_is_listed_first(self):
		with patch.object(frappe.defaults, "get_global_default", return_value="KES"):
			text = M.format_currency_totals({"USD": 10, "KES": 100})
		self.assertTrue(text.startswith("KES"), text)
		self.assertIn("USD", text)

	def test_code_is_not_doubled_with_a_symbol(self):
		"""'USD $ 1,000.00' read as two currencies at a glance."""
		with patch.object(frappe.defaults, "get_global_default", return_value="KES"):
			text = M.format_currency_totals({"USD": 1000})
		self.assertEqual(text, "USD 1,000.00")


class TestNormalisingAMaterialRequest(unittest.TestCase):
	def test_base_amount_and_totals_are_derived(self):
		mr = _MR([_Item(custom_currency="USD", custom_exchange_rate=130, amount=1000)])
		with patch.object(M, "company_currency", return_value=BASE):
			M.normalize_material_request_currencies(mr)
		self.assertEqual(mr["items"][0].custom_base_amount, 130000)
		self.assertEqual(mr.custom_base_total, 130000)
		self.assertIn("USD", mr.custom_currency_totals)

	def test_unticking_multicurrency_forces_the_company_currency(self):
		"""Otherwise a stray USD line survives the box being cleared."""
		mr = _MR(
			[_Item(custom_currency="USD", custom_exchange_rate=130, amount=1000)],
			multicurrency=0,
		)
		with patch.object(M, "company_currency", return_value=BASE):
			M.normalize_material_request_currencies(mr)
		self.assertEqual(mr["items"][0].custom_currency, BASE)
		self.assertEqual(mr["items"][0].custom_exchange_rate, 1)
		self.assertEqual(mr["items"][0].custom_base_amount, 1000)
		self.assertEqual(mr.custom_currency_totals, "")

	def test_a_purchase_request_is_never_multicurrency(self):
		mr = _MR(
			[_Item(custom_currency="USD", custom_exchange_rate=130, amount=1000)],
			request_type="Purchase",
		)
		with patch.object(M, "company_currency", return_value=BASE):
			M.normalize_material_request_currencies(mr)
		self.assertEqual(mr["items"][0].custom_currency, BASE)

	def test_a_missing_rate_is_fetched_rather_than_left_at_zero(self):
		"""A zero rate would value the line at nothing in company currency."""
		mr = _MR([_Item(custom_currency="USD", custom_exchange_rate=0, amount=1000)])
		with patch.object(M, "company_currency", return_value=BASE), patch.object(
			M, "live_exchange_rate", return_value=129.6
		):
			M.normalize_material_request_currencies(mr)
		self.assertEqual(mr["items"][0].custom_exchange_rate, 129.6)
		self.assertEqual(mr["items"][0].custom_base_amount, 129600)

	def test_an_unfetchable_rate_is_refused_not_guessed(self):
		mr = _MR([_Item(custom_currency="USD", custom_exchange_rate=0, amount=1000)])
		with patch.object(M, "company_currency", return_value=BASE), patch.object(
			M, "live_exchange_rate", return_value=0
		):
			with self.assertRaises(frappe.ValidationError):
				M.normalize_material_request_currencies(mr)


class TestJournalLines(unittest.TestCase):
	"""A line is written in whichever currency its own account holds."""

	def _line(self, account_currency, side="debit"):
		with patch.object(frappe.db, "get_value", return_value=account_currency):
			return F._journal_line(
				"ACC", side, foreign_amount=1000, base_amount=129600,
				row_currency="USD", base=BASE, rate=129.6, remark="r",
			)

	def test_a_foreign_account_holds_the_foreign_amount(self):
		line = self._line("USD")
		self.assertEqual(line["debit_in_account_currency"], 1000)
		self.assertEqual(line["exchange_rate"], 129.6)
		self.assertEqual(line["account_currency"], "USD")

	def test_a_company_currency_account_holds_the_converted_amount(self):
		"""A USD expense settled from the KES bank still balances."""
		line = self._line("KES")
		self.assertEqual(line["debit_in_account_currency"], 129600)
		self.assertEqual(line["exchange_rate"], 1.0)

	def test_a_third_currency_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._line("EUR")

	def test_credit_side_uses_the_credit_field(self):
		line = self._line("USD", side="credit")
		self.assertEqual(line["credit_in_account_currency"], 1000)
		self.assertNotIn("debit_in_account_currency", line)


class TestPaymentRate(unittest.TestCase):
	"""The ledger gets today's rate, not the estimate made weeks earlier."""

	def test_company_currency_needs_no_rate(self):
		rate, note = F._payment_exchange_rate(frappe._dict(), BASE, BASE, "2026-10-13")
		self.assertEqual(rate, 1.0)
		self.assertEqual(note, "")

	def test_live_rate_is_preferred(self):
		row = frappe._dict(exchange_rate=120, material_request="MR")
		with patch.object(F, "live_exchange_rate", return_value=129.6):
			rate, note = F._payment_exchange_rate(row, "USD", BASE, "2026-10-13")
		self.assertEqual(rate, 129.6)
		self.assertIn("129.6", note)

	def test_estimate_is_the_named_fallback(self):
		"""Named, so a posted entry says which rate it used."""
		row = frappe._dict(exchange_rate=120, material_request="MR")
		with patch.object(F, "live_exchange_rate", return_value=0):
			rate, note = F._payment_exchange_rate(row, "USD", BASE, "2026-10-13")
		self.assertEqual(rate, 120)
		self.assertIn("estimated", note)

	def test_no_rate_at_all_refuses_to_build_the_entry(self):
		"""Posting at a zero rate would write a zero-value entry."""
		row = frappe._dict(exchange_rate=0, material_request="MR")
		with patch.object(F, "live_exchange_rate", return_value=0):
			with self.assertRaises(frappe.ValidationError):
				F._payment_exchange_rate(row, "USD", BASE, "2026-10-13")


class TestBankAccountChoice(unittest.TestCase):
	"""Finance picks the account, and the choice is checked before it is used."""

	GOOD = frappe._dict(
		name="NCBA USD", company="CGM", is_group=0,
		account_type="Bank", account_currency="USD",
	)

	def _resolve(self, account, chosen=None):
		with patch.object(frappe.db, "get_value", return_value=account):
			return F._resolve_bank_account("CGM", "USD", BASE, chosen or {"USD": "NCBA USD"})

	def test_the_chosen_account_is_used(self):
		self.assertEqual(self._resolve(self.GOOD), "NCBA USD")

	def test_an_account_of_another_company_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._resolve(self.GOOD.copy().update({"company": "Other"}) or self.GOOD)

	def test_a_group_account_is_refused(self):
		bad = frappe._dict(self.GOOD, is_group=1)
		with self.assertRaises(frappe.ValidationError):
			self._resolve(bad)

	def test_a_non_bank_account_is_refused(self):
		bad = frappe._dict(self.GOOD, account_type="Expense Account")
		with self.assertRaises(frappe.ValidationError):
			self._resolve(bad)

	def test_an_account_in_an_unrelated_currency_is_refused(self):
		bad = frappe._dict(self.GOOD, account_currency="EUR")
		with self.assertRaises(frappe.ValidationError):
			self._resolve(bad)

	def test_a_company_currency_account_is_allowed(self):
		"""Paying a USD request out of the KES account is a real thing to do."""
		ok = frappe._dict(self.GOOD, account_currency=BASE)
		self.assertEqual(self._resolve(ok), "NCBA USD")

	def test_a_missing_account_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._resolve(None)


class TestRateSources(unittest.TestCase):
	"""Where the rate comes from, and in which order.

	ERPNext asks stored Currency Exchange records first and this site has
	`allow_stale` switched on, so one record entered in 2020 would price every
	payment made since. The order is inverted here on purpose.
	"""

	def test_the_service_is_asked_before_stored_records(self):
		with patch.object(M, "_service_exchange_rate", return_value=129.6) as service, patch.object(
			M, "_stored_exchange_rate", return_value=99.0
		) as stored:
			rate = M.live_exchange_rate("USD", "KES", "2026-10-13")
		self.assertEqual(rate, 129.6)
		service.assert_called_once()
		stored.assert_not_called()

	def test_stored_records_are_the_fallback(self):
		with patch.object(M, "_service_exchange_rate", return_value=0.0), patch.object(
			M, "_stored_exchange_rate", return_value=99.0
		):
			self.assertEqual(M.live_exchange_rate("USD", "KES", "2026-10-13"), 99.0)

	def test_no_source_returns_zero_rather_than_raising(self):
		"""The caller decides; a zero rate must never silently reach the ledger."""
		with patch.object(M, "_service_exchange_rate", return_value=0.0), patch.object(
			M, "_stored_exchange_rate", return_value=0.0
		):
			self.assertEqual(M.live_exchange_rate("USD", "KES", "2026-10-13"), 0.0)

	def test_same_currency_short_circuits(self):
		with patch.object(M, "_service_exchange_rate") as service:
			self.assertEqual(M.live_exchange_rate("KES", "KES", "2026-10-13"), 1.0)
		service.assert_not_called()

	def test_a_disabled_service_yields_nothing(self):
		with patch.object(
			frappe, "get_cached_doc", return_value=frappe._dict(disabled=1)
		):
			self.assertEqual(M._service_exchange_rate("USD", "KES", "2026-10-13"), 0.0)


class _FundingRequestStub:
	"""Enough of a Funding Request to exercise the totals table."""

	def __init__(self, rows, workflow_state="Approved", company="CGM"):
		from cgm_shipping.cgm_worldwide_shipping.doctype.funding_request.funding_request import (
			FundingRequest,
		)

		self.company = company
		self.workflow_state = workflow_state
		self.currency_totals = []
		self.meta = _meta("currency_totals")
		self._rows = rows
		self._set_currency_totals = FundingRequest._set_currency_totals.__get__(self)

	def set(self, fieldname, value):
		setattr(self, fieldname, value)

	def append(self, fieldname, row):
		getattr(self, fieldname).append(frappe._dict(row))


def _row(name, currency, requested, approved=0, funded=0, rate=1, decision="Approved"):
	return frappe._dict(
		name=name, currency=currency, requested_amount=requested,
		approved_amount=approved, funded_amount=funded, exchange_rate=rate,
		base_approved_amount=approved * rate, decision=decision,
	)


class TestCurrencyTotalsTable(unittest.TestCase):
	"""One row per currency, so a KES figure is never added to a USD one.

	This replaced a single text line. The figures the approval and payment gates
	use stay in company currency underneath; this table is what the money was
	actually asked for in.
	"""

	def _build(self, rows, workflow_state="Approved"):
		stub = _FundingRequestStub(rows, workflow_state=workflow_state)
		with patch.object(M, "company_currency", return_value=BASE):
			stub._set_currency_totals(rows, [r for r in rows if r.decision == "Approved"])
		return {row.currency: row for row in stub.currency_totals}

	def test_each_currency_gets_its_own_row(self):
		totals = self._build([
			_row("a", "USD", 1000, 1000, 0, 129.6),
			_row("b", "USD", 1013, 1013, 0, 129.6),
			_row("c", BASE, 2011, 2011),
			_row("d", BASE, 3605, 3605),
		])
		self.assertEqual(set(totals), {BASE, "USD"})
		self.assertEqual(totals["USD"].total_requested, 2013)
		self.assertEqual(totals[BASE].total_requested, 5616)

	def test_a_single_company_currency_request_gets_no_table(self):
		"""One row repeating the totals below it would be noise."""
		self.assertEqual(self._build([_row("a", BASE, 1000, 1000)]), {})

	def test_company_currency_is_listed_first(self):
		stub = _FundingRequestStub([])
		rows = [_row("a", "USD", 1000, 1000, 0, 129.6), _row("b", BASE, 2000, 2000)]
		with patch.object(M, "company_currency", return_value=BASE):
			stub._set_currency_totals(rows, rows)
		self.assertEqual([r.currency for r in stub.currency_totals], [BASE, "USD"])

	def test_outstanding_is_per_currency(self):
		totals = self._build([
			_row("a", "USD", 1000, 1000, 400, 129.6),
			_row("b", BASE, 2000, 2000, 500),
		])
		self.assertEqual(totals["USD"].outstanding, 600)
		self.assertEqual(totals[BASE].outstanding, 1500)

	def test_the_company_currency_equivalent_is_carried_per_row(self):
		totals = self._build([
			_row("a", "USD", 1000, 1000, 0, 129.6),
			_row("b", BASE, 2000, 2000),
		])
		self.assertEqual(totals["USD"].base_total_approved, 129600)
		self.assertEqual(totals[BASE].base_total_approved, 2000)

	def test_nothing_is_approved_before_the_approver_acts(self):
		"""Requested still shows; approved and disbursed stay at zero."""
		totals = self._build(
			[_row("a", "USD", 1000, 1000, 0, 129.6, decision="Pending"),
			 _row("b", BASE, 2000, 2000, 0, 1, decision="Pending")],
			workflow_state="Pending",
		)
		self.assertEqual(totals["USD"].total_requested, 1000)
		self.assertEqual(totals["USD"].total_approved, 0)
		self.assertEqual(totals["USD"].total_funded, 0)

	def test_a_rejected_row_still_shows_what_was_asked_for(self):
		totals = self._build([
			_row("a", "USD", 1000, 0, 0, 129.6, decision="Rejected"),
			_row("b", BASE, 2000, 2000),
		])
		self.assertEqual(totals["USD"].total_requested, 1000)
		self.assertEqual(totals["USD"].total_approved, 0)


class TestStaleGridViewPatch(unittest.TestCase):
	"""A saved grid layout hides columns added later, silently and for good.

	Frappe writes a `GridView` entry to `__UserSettings` the moment somebody uses
	the gear on a child table. From then on the grid renders that saved list and
	ignores `in_list_view` entirely, so the Currency column added here would never
	appear for exactly the people who use the form most. This caught us on both
	grids in turn.
	"""

	PARENT = "Funding Request"
	CHILD = "Funding Request Material Request"
	USER = "grid-view-patch-test@example.com"

	def setUp(self):
		from cgm_shipping.patches import clear_stale_child_grid_views as patch_module

		self.patch = patch_module
		self._write({
			"updated_on": "2026-10-13",
			"List": {"filters": [["status", "=", "Open"]]},
			"GridView": {
				self.CHILD: [{"fieldname": "material_request"}, {"fieldname": "decision"}],
				"Some Other Table": [{"fieldname": "whatever"}],
			},
		})

	def tearDown(self):
		frappe.db.sql(
			"delete from `__UserSettings` where user = %(user)s and doctype = %(doctype)s",
			{"user": self.USER, "doctype": self.PARENT},
		)
		frappe.db.commit()

	def _write(self, data):
		import json

		frappe.db.sql(
			"delete from `__UserSettings` where user = %(user)s and doctype = %(doctype)s",
			{"user": self.USER, "doctype": self.PARENT},
		)
		frappe.db.sql(
			"insert into `__UserSettings` (user, doctype, data) values (%(user)s, %(doctype)s, %(data)s)",
			{"user": self.USER, "doctype": self.PARENT, "data": json.dumps(data)},
		)
		frappe.db.commit()

	def _read(self):
		import json

		row = frappe.db.sql(
			"select data from `__UserSettings` where user = %(user)s and doctype = %(doctype)s",
			{"user": self.USER, "doctype": self.PARENT},
		)
		return json.loads(row[0][0]) if row else {}

	def test_the_stale_layout_is_removed(self):
		self.patch.execute()
		self.assertNotIn(self.CHILD, self._read().get("GridView", {}))

	def test_other_saved_layouts_survive(self):
		"""Only the tables that gained a column are reset."""
		self.patch.execute()
		self.assertIn("Some Other Table", self._read().get("GridView", {}))

	def test_list_settings_and_filters_survive(self):
		self.patch.execute()
		data = self._read()
		self.assertEqual(data["List"]["filters"], [["status", "=", "Open"]])
		self.assertEqual(data["updated_on"], "2026-10-13")

	def test_running_it_again_is_harmless(self):
		self.patch.execute()
		self.patch.execute()
		self.assertNotIn(self.CHILD, self._read().get("GridView", {}))

	def test_an_unreadable_settings_blob_is_left_alone(self):
		"""Not ours to rewrite, and it must not stop the patch."""
		frappe.db.sql(
			"update `__UserSettings` set data = %(data)s where user = %(user)s and doctype = %(doctype)s",
			{"data": "not json at all", "user": self.USER, "doctype": self.PARENT},
		)
		frappe.db.commit()
		self.patch.execute()
		row = frappe.db.sql(
			"select data from `__UserSettings` where user = %(user)s and doctype = %(doctype)s",
			{"user": self.USER, "doctype": self.PARENT},
		)
		self.assertEqual(row[0][0], "not json at all")

	def test_every_affected_grid_still_defines_the_column_it_lost(self):
		"""The patch is pointless if the field is not actually in the grid."""
		expected = {
			"Material Request Item": "custom_currency",
			"Funding Request Material Request": "currency",
		}
		for _parent, child in self.patch.AFFECTED:
			meta = frappe.get_meta(child)
			field = meta.get_field(expected[child])
			self.assertTrue(field, f"{child}.{expected[child]} is missing")
			self.assertTrue(
				field.in_list_view, f"{child}.{expected[child]} is not in the grid"
			)


class TestSplittingARequestByCurrency(unittest.TestCase):
	"""One request holding two currencies becomes one row per currency.

	It cannot be paid as one thing: a Journal Entry takes money out of a single
	bank account held in a single currency. So each currency is approved on its
	own and paid from the account that matches it.
	"""

	def _splits(self, lines, base=BASE):
		rows = [frappe._dict(l) for l in lines]
		with patch.object(frappe.db, "get_value", return_value="CGM"), patch.object(
			M, "company_currency", return_value=base
		), patch.object(frappe, "get_all", return_value=rows):
			return M.material_request_currency_totals("MR-1")

	def test_a_single_currency_request_yields_one_entry(self):
		out = self._splits([{"custom_currency": BASE, "custom_exchange_rate": 1, "amount": 1000, "custom_base_amount": 1000}])
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["currency"], BASE)
		self.assertEqual(out[0]["amount"], 1000)

	def test_two_currencies_yield_two_entries(self):
		out = self._splits([
			{"custom_currency": "USD", "custom_exchange_rate": 129.6, "amount": 800, "custom_base_amount": 103680},
			{"custom_currency": BASE, "custom_exchange_rate": 1, "amount": 35000, "custom_base_amount": 35000},
			{"custom_currency": "USD", "custom_exchange_rate": 129.6, "amount": 200, "custom_base_amount": 25920},
		])
		by_currency = {o["currency"]: o for o in out}
		self.assertEqual(set(by_currency), {BASE, "USD"})
		self.assertEqual(by_currency["USD"]["amount"], 1000)
		self.assertEqual(by_currency["USD"]["base_amount"], 129600)
		self.assertEqual(by_currency[BASE]["amount"], 35000)

	def test_company_currency_is_listed_first(self):
		out = self._splits([
			{"custom_currency": "USD", "custom_exchange_rate": 129.6, "amount": 100, "custom_base_amount": 12960},
			{"custom_currency": BASE, "custom_exchange_rate": 1, "amount": 100, "custom_base_amount": 100},
		])
		self.assertEqual([o["currency"] for o in out], [BASE, "USD"])

	def test_lines_at_different_rates_are_weighted_by_amount(self):
		"""The rate reported has to reproduce the figure the approver was shown."""
		out = self._splits([
			{"custom_currency": "USD", "custom_exchange_rate": 130, "amount": 100, "custom_base_amount": 13000},
			{"custom_currency": "USD", "custom_exchange_rate": 120, "amount": 100, "custom_base_amount": 12000},
		])
		self.assertEqual(out[0]["amount"], 200)
		self.assertEqual(out[0]["base_amount"], 25000)
		self.assertEqual(out[0]["exchange_rate"], 125)

	def test_unpriced_lines_are_ignored(self):
		out = self._splits([
			{"custom_currency": "USD", "custom_exchange_rate": 129.6, "amount": 0, "custom_base_amount": 0},
			{"custom_currency": BASE, "custom_exchange_rate": 1, "amount": 500, "custom_base_amount": 500},
		])
		self.assertEqual([o["currency"] for o in out], [BASE])


class TestMulticurrencyDefault(unittest.TestCase):
	"""Operational Expense is multicurrency unless somebody turns it off.

	It is the only request type funded by Journal Entry rather than a Purchase
	Order, and it is where CGM's foreign-currency spending lives. Starting it
	unticked meant every USD request began unable to say which currency it was in.
	"""

	REQUEST_TYPE = "Operational Expense"

	def test_the_field_defaults_to_on(self):
		field = frappe.get_meta("Material Request").get_field("custom_multicurrency")
		self.assertEqual(str(field.default), "1")

	def test_it_is_only_shown_on_operational_expense(self):
		"""Other types fund through a Purchase Order in the company currency."""
		field = frappe.get_meta("Material Request").get_field("custom_multicurrency")
		self.assertIn(self.REQUEST_TYPE, field.depends_on or "")

	def test_a_new_operational_expense_request_arrives_ticked(self):
		doc = frappe.new_doc("Material Request")
		doc.material_request_type = self.REQUEST_TYPE
		self.assertEqual(int(doc.custom_multicurrency or 0), 1)

	def test_the_flag_is_ignored_for_other_request_types(self):
		"""Ticked or not, a Purchase request is never multicurrency."""
		doc = frappe._dict(material_request_type="Purchase", custom_multicurrency=1)
		self.assertFalse(M.is_multicurrency(doc))


class TestMulticurrencyBackfillPatch(unittest.TestCase):
	"""Existing requests get the flag too, or the same form behaves two ways."""

	REQUEST_TYPE = "Operational Expense"

	def setUp(self):
		from cgm_shipping.patches import (
			default_multicurrency_on_operational_expense as patch_module,
		)

		self.patch = patch_module
		self.before = frappe.db.sql(
			"select name, custom_multicurrency from `tabMaterial Request`"
		)

	def tearDown(self):
		for name, value in self.before:
			frappe.db.set_value(
				"Material Request", name, "custom_multicurrency", value, update_modified=False
			)
		frappe.db.commit()

	def _flags(self, request_type):
		return {
			row[0]
			for row in frappe.db.sql(
				"""select ifnull(custom_multicurrency, 0) from `tabMaterial Request`
				   where material_request_type = %s""",
				(request_type,),
			)
		}

	def test_operational_expense_requests_are_switched_on(self):
		frappe.db.sql("update `tabMaterial Request` set custom_multicurrency = 0")
		frappe.db.commit()
		self.patch.execute()
		flags = self._flags(self.REQUEST_TYPE)
		self.assertTrue(flags <= {1}, f"expected every flag on, got {flags}")

	def test_purchase_requests_are_left_alone(self):
		frappe.db.sql("update `tabMaterial Request` set custom_multicurrency = 0")
		frappe.db.commit()
		self.patch.execute()
		flags = self._flags("Purchase")
		self.assertTrue(flags <= {0}, f"expected Purchase untouched, got {flags}")

	def test_running_it_again_changes_nothing(self):
		self.patch.execute()
		self.patch.execute()
		self.assertTrue(self._flags(self.REQUEST_TYPE) <= {1})
