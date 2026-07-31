"""Guard the statutory payroll exports against their filing templates.

The DTB, NSSF, PAYE and SHIF reports exist so finance can export a file and
upload it straight to the bank or portal. That only holds while the report's
leading columns match the supplied template exactly, in order -- reordering or
relabelling one column silently produces a file the portal rejects. These tests
pin that contract to the template files in ``apps/cgm_shipping/files``.

Run: bench --site <site> run-tests --app cgm_shipping --module cgm_shipping.tests.test_payroll_statutory_reports
"""

import importlib
import json
import os
import unittest

import frappe

import cgm_shipping

FILES_DIR = os.path.join(os.path.dirname(os.path.dirname(cgm_shipping.__file__)), "files")
REPORT_PKG = "cgm_shipping.cgm_worldwide_shipping.report"

# report module slug -> template workbook whose header row defines the contract
REPORT_TEMPLATES = {
	"dtb_salary_payment_schedule": "DTB TEMPLATE.xls",
	"nssf_monthly_return": "Nssf Template.xlsx",
	"paye_monthly_return": "PAYE Template.xls",
	"shif_monthly_return": "SHIF Template.xlsx",
}

# The NSSF and SHIF templates shout their headers in caps. The reports render them
# in the PAYE template's Title Case instead -- acronyms capitalised, minor words
# lowercase, "Number" spelled out -- so all four read consistently in the desk.
# Column ORDER and COUNT still track the template exactly; only the wording differs.
RELABELLED = {
	"nssf_monthly_return": [
		"Payroll Number",
		"Surname",
		"Other Names",
		"ID Number",
		"KRA PIN",
		"NSSF Number",
		"Gross Pay",
		"Voluntary",
	],
	"shif_monthly_return": [
		"Payroll Number",
		"First Name",
		"Last Name",
		"Identity Type",
		"ID Number",
		"KRA PIN",
		"NHIF Number",
		"Contribution Amount",
		"Phone",
	],
}


def expected_labels(slug: str, template: str) -> list[str]:
	"""Labels the report should emit: the template's own, unless deliberately relabelled."""
	return RELABELLED.get(slug) or template_headers(template)


def template_headers(filename: str) -> list[str]:
	path = os.path.join(FILES_DIR, filename)
	if filename.endswith(".xls"):
		import xlrd

		sheet = xlrd.open_workbook(path).sheet_by_index(0)
		return [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]

	import openpyxl

	sheet = openpyxl.load_workbook(path, data_only=True).worksheets[0]
	return [str(cell.value).strip() for cell in sheet[1] if cell.value is not None]


def load_report(slug: str):
	return importlib.import_module(f"{REPORT_PKG}.{slug}.{slug}")


def sample_slips() -> list[frappe._dict]:
	"""One fully documented employee and one missing every statutory number."""
	return [
		frappe._dict(
			name="SAL-TEST-0001",
			employee="EMP-TEST-0001",
			employee_name="Test Complete Employee",
			start_date="2026-06-01",
			end_date="2026-06-30",
			gross_pay=120000.0,
			net_pay=88450.0,
			total_deduction=31550.0,
			employee_doc=frappe._dict(
				employee_number="CGMWS/TEST1",
				first_name="Test",
				middle_name="Complete",
				last_name="Employee",
				cell_number="0722000111",
				custom_id_number="21345678",
				passport_number="",
				custom_kra_pin="A010115345P",
				custom_nssf_no="2015789153",
				custom_shif_no="CR1546435462",
				bank_name="DTB",
				custom_bank_branch="Koinange Street",
				custom_bank_branch_code="042",
				bank_ac_no="0112255335",
			),
			components={
				"PAYE": 24500.0,
				"NSSF": 4320.0,
				"SHIF": 3300.0,
				"Housing Levy": 1800.0,
			},
		),
		frappe._dict(
			name="SAL-TEST-0002",
			employee="EMP-TEST-0002",
			employee_name="Test Incomplete Employee",
			start_date="2026-06-01",
			end_date="2026-06-30",
			gross_pay=50000.0,
			net_pay=41200.0,
			total_deduction=8800.0,
			employee_doc=frappe._dict(
				employee_number="CGMWS/TEST2",
				first_name="Test",
				middle_name="Incomplete",
				last_name="Employee",
				cell_number="",
				custom_id_number="",
				passport_number="AK0912345",
				custom_kra_pin="",
				custom_nssf_no="",
				custom_shif_no="",
				bank_name="Equity Bank",
				custom_bank_branch="Westlands",
				custom_bank_branch_code="",
				bank_ac_no="",
			),
			components={"PAYE": 5200.0, "NSSF": 2160.0, "SHIF": 1375.0},
		),
	]


def run_with_sample_slips(module, filters=None):
	"""Execute a report against fabricated slips, leaving the database untouched."""
	original = module.get_salary_slips
	module.get_salary_slips = lambda _filters: sample_slips()
	try:
		return module.execute(filters or {"company": "Test Co", "from_date": "2026-06-01", "to_date": "2026-06-30"})
	finally:
		module.get_salary_slips = original


class TestStatutoryReportTemplates(unittest.TestCase):
	def test_columns_match_templates(self):
		"""Leading report columns reproduce the template's columns, in order."""
		for slug, template in REPORT_TEMPLATES.items():
			with self.subTest(report=slug):
				columns, _rows = run_with_sample_slips(load_report(slug))
				expected = expected_labels(slug, template)
				actual = [col["label"] for col in columns][: len(expected)]
				self.assertEqual(actual, expected)

	def test_column_count_tracks_template(self):
		"""Relabelling may change wording but never the number of template columns."""
		for slug, template in REPORT_TEMPLATES.items():
			with self.subTest(report=slug):
				self.assertEqual(len(expected_labels(slug, template)), len(template_headers(template)))

	def test_every_column_is_populated(self):
		"""Each row carries a key for every declared column, so no cell exports as undefined."""
		for slug in REPORT_TEMPLATES:
			with self.subTest(report=slug):
				columns, rows = run_with_sample_slips(load_report(slug))
				self.assertTrue(rows)
				for row in rows:
					missing = [col["fieldname"] for col in columns if col["fieldname"] not in row]
					self.assertEqual(missing, [])

	def test_empty_period_returns_columns_without_rows(self):
		"""Before payroll is run the reports render headers rather than raising."""
		for slug in REPORT_TEMPLATES:
			with self.subTest(report=slug):
				module = load_report(slug)
				original = module.get_salary_slips
				module.get_salary_slips = lambda _filters: []
				try:
					columns, rows = module.execute({"company": "Test Co"})
				finally:
					module.get_salary_slips = original
				self.assertTrue(columns)
				self.assertEqual(rows, [])


class TestStatutoryReportDefinitions(unittest.TestCase):
	REPORT_NAMES = {
		"dtb_salary_payment_schedule": "DTB Salary Payment Schedule",
		"nssf_monthly_return": "NSSF Monthly Return",
		"paye_monthly_return": "PAYE Monthly Return",
		"shif_monthly_return": "SHIF Monthly Return",
	}

	def test_no_total_row(self):
		"""A totals row would be uploaded to the portal as a bogus member record.

		Frappe appends it to the exported file too, so these reports must not set it.
		"""
		for slug, report_name in self.REPORT_NAMES.items():
			with self.subTest(report=report_name):
				path = os.path.join(
					os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
					"cgm_worldwide_shipping", "report", slug, f"{slug}.json",
				)
				with open(path) as fh:
					definition = json.load(fh)
				self.assertEqual(definition["add_total_row"], 0)

				if frappe.db.exists("Report", report_name):
					self.assertFalse(frappe.db.get_value("Report", report_name, "add_total_row"))


class TestStatutoryComponentNames(unittest.TestCase):
	def test_component_constants_exist(self):
		"""The constants must name real Salary Components.

		A typo here is silent: ``component()`` returns 0 for an unknown name, so the
		export files out zero PAYE/NSSF/SHIF instead of failing.
		"""
		from cgm_shipping.cgm_worldwide_shipping.services import payroll_statutory

		for constant in (
			"COMPONENT_PAYE",
			"COMPONENT_NSSF",
			"COMPONENT_SHIF",
			"COMPONENT_HOUSING_LEVY",
			"COMPONENT_PERSONAL_RELIEF",
		):
			name = getattr(payroll_statutory, constant)
			with self.subTest(constant=constant, component=name):
				self.assertTrue(
					frappe.db.exists("Salary Component", name),
					f"{constant} = {name!r} is not an existing Salary Component",
				)


class TestStatutoryReportValues(unittest.TestCase):
	def test_dtb_routes_internal_and_external_banks(self):
		"""DTB accounts settle internally; other banks go out by EFT."""
		_columns, rows = run_with_sample_slips(load_report("dtb_salary_payment_schedule"))
		self.assertEqual(rows[0]["payment_method"], "Internal funds transfer")
		self.assertEqual(rows[1]["payment_method"], "EFT")
		# An unmapped branch with no branch code on the record exports blank rather
		# than a guessed code that would misroute the payment.
		self.assertEqual(rows[1]["dtb_branch_code"], "")

	def test_branch_code_field_beats_the_fallback_map(self):
		"""The Employee's Bank Branch Code wins; the map only fills a blank field."""
		from cgm_shipping.cgm_worldwide_shipping.services.payroll_statutory import dtb_branch_code

		# Record says 042 even though the map would say 069 for Koinange Street.
		_columns, rows = run_with_sample_slips(load_report("dtb_salary_payment_schedule"))
		self.assertEqual(rows[0]["dtb_branch_code"], "042")

		# Blank field on a mapped branch falls back to the map.
		self.assertEqual(
			dtb_branch_code(
				frappe._dict(custom_bank_branch_code="", custom_bank_branch="Koinange Street")
			),
			"069",
		)
		# Blank field on an unmapped branch stays blank.
		self.assertEqual(
			dtb_branch_code(frappe._dict(custom_bank_branch_code="", custom_bank_branch="Nowhere")),
			"",
		)

	def test_dtb_pays_net_pay(self):
		_columns, rows = run_with_sample_slips(load_report("dtb_salary_payment_schedule"))
		self.assertEqual(rows[0]["payable_amount"], 88450.0)

	def test_payroll_number_is_the_employee_number(self):
		"""PAYROLL NUMBER is the employee's payroll number, not a row counter."""
		for slug in ("nssf_monthly_return", "shif_monthly_return"):
			with self.subTest(report=slug):
				_columns, rows = run_with_sample_slips(load_report(slug))
				self.assertEqual(rows[0]["payroll_number"], "CGMWS/TEST1")
				self.assertEqual(rows[1]["payroll_number"], "CGMWS/TEST2")

	def test_nssf_splits_surname_from_other_names(self):
		_columns, rows = run_with_sample_slips(load_report("nssf_monthly_return"))
		self.assertEqual(rows[0]["surname"], "Employee")
		self.assertEqual(rows[0]["other_names"], "Test Complete")
		self.assertEqual(rows[0]["gross_pay"], 120000.0)

	def test_shif_falls_back_to_passport(self):
		_columns, rows = run_with_sample_slips(load_report("shif_monthly_return"))
		self.assertEqual(rows[0]["identity_type"], "National ID")
		self.assertEqual(rows[0]["id_no"], "21345678")
		self.assertEqual(rows[1]["identity_type"], "Passport Number")
		self.assertEqual(rows[1]["id_no"], "AK0912345")

	def test_shif_uses_shif_deduction(self):
		_columns, rows = run_with_sample_slips(load_report("shif_monthly_return"))
		self.assertEqual(rows[0]["contribution_amount"], 3300.0)

	def test_paye_leaves_itax_computed_columns_blank(self):
		"""iTax derives these three; sending values makes it flag a mismatch."""
		_columns, rows = run_with_sample_slips(load_report("paye_monthly_return"))
		self.assertEqual(rows[0]["total_gross_pay"], "")
		self.assertEqual(rows[0]["taxable_pay"], "")
		self.assertEqual(rows[0]["paye_tax"], "")
		self.assertEqual(rows[0]["self_assessed_paye_tax"], 24500.0)

	def test_paye_carries_statutory_deductions(self):
		_columns, rows = run_with_sample_slips(load_report("paye_monthly_return"))
		self.assertEqual(rows[0]["shif"], 3300.0)
		self.assertEqual(rows[0]["nssf"], 4320.0)
		self.assertEqual(rows[0]["housing_levy"], 1800.0)
		self.assertEqual(rows[0]["monthly_personal_relief"], 2400.0)
		# A component absent from the slip contributes zero, never None.
		self.assertEqual(rows[1]["housing_levy"], 0.0)
