"""The Material Request items grid is driven by JavaScript, not by `in_list_view`.

This cost real time, so it is worth stating plainly. `apply_item_grid_layout` in
`public/js/material_request.js` holds two hardcoded column lists, forces
`in_list_view = 0` on every field absent from the one in play, and replaces
`grid.setup_user_defined_columns` outright. A field added through Customize Form,
a Custom Field or a Property Setter therefore does **not** appear on this form
until it is named in that list, and nothing anywhere reports an error.

These tests check the two lists against the live DocType, so a field that is
renamed or removed fails here rather than silently vanishing from the grid. The
behaviour itself - which list wins, and whether a user may still configure the
grid - is exercised by running the script in `tests/js/material_request_grid.test.js`.
"""

import re
import shutil
import subprocess
import unittest
from unittest.mock import patch
from pathlib import Path

import frappe

JS = Path(frappe.get_app_path("cgm_shipping")) / "public" / "js" / "material_request.js"


def _show_list(constant: str) -> list[str]:
	source = JS.read_text()
	block = re.search(rf"const {constant} = \{{(.*?)\n\}};", source, re.S)
	assert block, f"{constant} not found in material_request.js"
	shown = re.search(r"show:\s*\[(.*?)\]", block.group(1), re.S)
	assert shown, f"{constant} has no show list"
	return re.findall(r'"([^"]+)"', shown.group(1))


class TestItemGridLayout(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.meta = frappe.get_meta("Material Request Item")

	def test_operational_expense_shows_the_currency(self):
		"""Added for multicurrency. Without it the column cannot be seen at all."""
		self.assertIn("custom_currency", _show_list("OE_ITEM_GRID_FIELDS"))

	def test_operational_expense_shows_the_expense_account(self):
		"""The account the Journal Entry debits, chosen per line."""
		self.assertIn("expense_account", _show_list("OE_ITEM_GRID_FIELDS"))

	def test_every_named_field_exists_on_the_doctype(self):
		"""A renamed field would otherwise drop out of the grid in silence."""
		for constant in ("OE_ITEM_GRID_FIELDS", "STANDARD_ITEM_GRID_FIELDS"):
			for fieldname in _show_list(constant):
				with self.subTest(constant=constant, field=fieldname):
					self.assertTrue(
						self.meta.has_field(fieldname),
						f"{constant} names {fieldname}, which is not on Material Request Item",
					)

	def test_the_standard_layout_is_left_alone(self):
		"""Purchase requests are company currency, so nothing changed for them."""
		standard = _show_list("STANDARD_ITEM_GRID_FIELDS")
		self.assertNotIn("custom_currency", standard)
		self.assertEqual(
			standard,
			["item_code", "qty", "uom", "rate", "amount", "schedule_date", "warehouse"],
		)

	def test_the_doctype_also_marks_these_fields_in_list_view(self):
		"""The JS wins on this form, but the DocField has to agree elsewhere.

		Reports, the API and any grid the script has not patched read
		`in_list_view`, so the two must not drift apart.
		"""
		for fieldname in ("custom_currency", "expense_account"):
			with self.subTest(field=fieldname):
				field = self.meta.get_field(fieldname)
				self.assertTrue(field, f"{fieldname} missing")
				self.assertTrue(field.in_list_view, f"{fieldname} is not in_list_view")


class TestItemGridBehaviour(unittest.TestCase):
	"""Runs the grid logic rather than reading it.

	Reading the source tells you which fields are named. Only running it tells you
	whether a column somebody adds from the gear survives the next refresh, which
	is the part that was wrong.
	"""

	def test_the_javascript_behaves(self):
		node = shutil.which("node")
		if not node:
			self.skipTest("node is not available")
		script = Path(frappe.get_app_path("cgm_shipping")) / "tests" / "js" / "material_request_grid.test.js"
		result = subprocess.run(
			[node, str(script)], capture_output=True, text=True, timeout=120
		)
		self.assertEqual(
			result.returncode,
			0,
			f"grid behaviour test failed:\n{result.stdout}\n{result.stderr}",
		)
		self.assertIn("PASS", result.stdout)
		self.assertNotIn("FAIL", result.stdout)


class TestExpenseAccountEditableAfterSubmit(unittest.TestCase):
	"""The account can be corrected on a request that is already submitted.

	The Journal Entry reads the expense account off the line when Finance creates
	it, which can be days after the request was submitted. Locking the field on
	submit meant a wrong account could only be fixed by cancelling and re-raising
	the whole request, and the Material Request posts nothing to the ledger itself,
	so there was nothing to protect.
	"""

	def test_the_field_may_be_changed_after_submit(self):
		field = frappe.get_meta("Material Request Item").get_field("expense_account")
		self.assertTrue(
			field.allow_on_submit,
			"expense_account is locked on submit; a wrong account could only be "
			"fixed by cancelling the request",
		)

	def test_the_field_is_not_read_only(self):
		field = frappe.get_meta("Material Request Item").get_field("expense_account")
		self.assertFalse(field.read_only)

	def test_a_change_reaches_the_next_journal_entry(self):
		"""Editing the line is only useful if the entry actually follows it.

		Entries already posted keep the account they were posted with: this changes
		what the *next* one debits, not history.
		"""
		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			_material_request_expense_account,
		)

		lines = [
			frappe._dict(expense_account="Corrected - X", custom_currency="KES", amount=100)
		]
		with patch.object(frappe, "get_all", return_value=lines), patch.object(
			frappe.db, "get_value", return_value=0
		):
			self.assertEqual(
				_material_request_expense_account("MR-1", "Company"), "Corrected - X"
			)
