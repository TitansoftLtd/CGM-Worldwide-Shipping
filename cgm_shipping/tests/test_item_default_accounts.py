"""Item Defaults may point at any account, but only when asked to.

CGM accrues shipping line and KPA charges to liability accounts because the charge
is incurred on a client's behalf and billed on, so it never belongs in an expense
account. ERPNext offers only Profit and Loss accounts there, which left an item for
one of those charges with nowhere valid to point.

The important half of this is the half that does nothing: with the setting off
these queries return exactly what ERPNext returns, account for account.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import item_default_accounts as IDA


class TestAnyAccountSetting(unittest.TestCase):
	def test_setting_is_read_through_the_meta_not_the_table(self):
		"""CGM Shipping Settings is a Single, so it has no table of its own.

		`frappe.db.has_column` raises TableMissingError on a Single rather than
		returning False, which is how the same pattern in funding.py turned a
		missing expense account into a raw ProgrammingError.
		"""
		with self.assertRaises(Exception):
			frappe.db.has_column("CGM Shipping Settings", "allow_any_item_default_account")
		# The real check does not raise.
		self.assertIn(IDA.any_account_allowed(), (True, False))

	def test_missing_field_means_not_allowed(self):
		with patch.object(
			frappe, "get_meta", return_value=frappe._dict(has_field=lambda _f: False)
		):
			self.assertFalse(IDA.any_account_allowed())


class TestAccountQueries(unittest.TestCase):
	"""Measured against ERPNext's own queries on the live chart of accounts."""

	@classmethod
	def setUpClass(cls):
		cls.company = frappe.defaults.get_global_default("company")
		if not cls.company:
			raise unittest.SkipTest("No default company on this site.")

	def _cgm(self, types, txt=""):
		return {r[0] for r in IDA._account_query(types, txt, {"company": self.company}, 0, 500)}

	def test_expense_matches_erpnext_when_the_setting_is_off(self):
		from erpnext.controllers.queries import get_expense_account

		with patch.object(IDA, "any_account_allowed", return_value=False):
			mine = self._cgm(IDA.EXPENSE_ACCOUNT_TYPES)
		theirs = {
			r[0]
			for r in get_expense_account("Account", "", "name", 0, 500, {"company": self.company})
		}
		self.assertEqual(mine, theirs)

	def test_income_matches_erpnext_when_the_setting_is_off(self):
		from erpnext.controllers.queries import get_income_account

		with patch.object(IDA, "any_account_allowed", return_value=False):
			mine = self._cgm(IDA.INCOME_ACCOUNT_TYPES)
		theirs = {
			r[0]
			for r in get_income_account("Account", "", "name", 0, 500, {"company": self.company})
		}
		self.assertEqual(mine, theirs)

	def test_every_postable_account_appears_when_allowed(self):
		"""On means every account on the company, not a wider shortlist."""
		with patch.object(IDA, "any_account_allowed", return_value=True):
			on = self._cgm(IDA.EXPENSE_ACCOUNT_TYPES)
		everything = {
			row.name
			for row in frappe.get_all(
				"Account",
				filters={"company": self.company, "is_group": 0, "disabled": 0},
				fields=["name"],
			)
		}
		self.assertEqual(on, everything)

	def test_the_liability_accounts_cgm_needs_are_among_them(self):
		"""The charges this was built for: both are Current Liability."""
		with patch.object(IDA, "any_account_allowed", return_value=True):
			on = self._cgm(IDA.EXPENSE_ACCOUNT_TYPES)
		with patch.object(IDA, "any_account_allowed", return_value=False):
			off = self._cgm(IDA.EXPENSE_ACCOUNT_TYPES)
		for account in ("Shipping Line Charges - CWSCL", "KPA Charges - CWSCL"):
			if not frappe.db.exists("Account", account):
				continue
			self.assertIn(account, on)
			self.assertNotIn(account, off)

	def test_income_offers_the_same_full_set_when_allowed(self):
		"""Both pickers open to the same list; only the narrowed lists differ."""
		with patch.object(IDA, "any_account_allowed", return_value=True):
			self.assertEqual(
				self._cgm(IDA.EXPENSE_ACCOUNT_TYPES), self._cgm(IDA.INCOME_ACCOUNT_TYPES)
			)

	def test_the_search_text_still_filters(self):
		with patch.object(IDA, "any_account_allowed", return_value=True):
			hits = self._cgm(IDA.EXPENSE_ACCOUNT_TYPES, txt="KPA")
		self.assertTrue(hits, "expected at least one KPA account")
		for name in hits:
			self.assertIn("kpa", name.lower())

	def test_another_company_is_excluded(self):
		with patch.object(IDA, "any_account_allowed", return_value=True):
			rows = IDA._account_query(
				IDA.EXPENSE_ACCOUNT_TYPES, "", {"company": "No Such Company"}, 0, 500
			)
		self.assertEqual(rows, ())

	def test_group_accounts_are_never_offered(self):
		with patch.object(IDA, "any_account_allowed", return_value=True):
			names = self._cgm(IDA.EXPENSE_ACCOUNT_TYPES)
		groups = [n for n in names if frappe.db.get_value("Account", n, "is_group")]
		self.assertEqual(groups, [])


class TestEnablePatch(unittest.TestCase):
	"""The patch that switches the setting on for sites that already exist.

	A DocField `default` only applies when a document is created, and CGM Shipping
	Settings is a Single created long ago, so the default never reaches a real
	site. The patch is what makes "on by default" true anywhere but a fresh
	install.
	"""

	DOCTYPE = "CGM Shipping Settings"
	FIELD = "allow_any_item_default_account"

	def setUp(self):
		from cgm_shipping.patches import enable_any_item_default_account as patch_module

		self.patch = patch_module
		self.before = frappe.db.sql(
			"select value from `tabSingles` where doctype = %s and field = %s",
			(self.DOCTYPE, self.FIELD),
		)

	def tearDown(self):
		frappe.db.delete("Singles", {"doctype": self.DOCTYPE, "field": self.FIELD})
		if self.before:
			frappe.db.set_single_value(self.DOCTYPE, self.FIELD, self.before[0][0])
		frappe.db.commit()

	def _stored(self):
		return frappe.db.get_single_value(self.DOCTYPE, self.FIELD)

	def test_a_site_that_never_had_the_field_gets_it_switched_on(self):
		frappe.db.delete("Singles", {"doctype": self.DOCTYPE, "field": self.FIELD})
		frappe.db.commit()
		self.patch.execute()
		self.assertEqual(int(self._stored() or 0), 1)

	def test_a_deliberate_untick_is_respected(self):
		"""`frappe.db.exists` returns nothing for `tabSingles`, which has no `name`
		column, so the first version of this guard fell through and overrode the
		user's choice."""
		frappe.db.set_single_value(self.DOCTYPE, self.FIELD, 0)
		frappe.db.commit()
		self.patch.execute()
		self.assertEqual(int(self._stored() or 0), 0)

	def test_running_it_twice_changes_nothing(self):
		frappe.db.delete("Singles", {"doctype": self.DOCTYPE, "field": self.FIELD})
		frappe.db.commit()
		self.patch.execute()
		self.patch.execute()
		self.assertEqual(int(self._stored() or 0), 1)
