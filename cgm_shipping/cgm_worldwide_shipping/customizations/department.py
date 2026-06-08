"""ERPNext Department resolution for the sea-clearance task flow.

Extracted from utils.py. Depends only on frappe and erpnext, so it has no import
cycle with utils — which re-exports these names for existing call sites.
"""

from __future__ import annotations

import frappe
from erpnext import get_default_company

# Map template labels or old department names -> ERPNext department_name (before company suffix).
DEPARTMENT_NAME_ALIASES = {
	"Administration": "Documentation",
}


def get_department_name_stem(raw):
	"""Extract the department name before the company abbreviation suffix."""
	value = (raw or "").strip()
	if not value:
		return ""

	# 1. ERPNext department docnames follow `{department_name} - {abbr}` — strip the suffix.
	if " - " in value:
		return value.split(" - ", 1)[0].strip()
	return value


def normalize_department_stem(raw) -> str:
	"""Template / task stem only (e.g. Finance), never Finance - C from another site."""
	stem = get_department_name_stem(raw)
	if not stem:
		return ""
	return DEPARTMENT_NAME_ALIASES.get(stem, stem)


def _department_matches_company(department: str, company: str) -> bool:
	"""True when Department link belongs to the given company."""
	if not department or not company:
		return False
	dept_company = frappe.db.get_value("Department", department, "company")
	if dept_company:
		return dept_company == company
	abbr = frappe.db.get_value("Company", company, "abbr")
	return bool(abbr and department.endswith(f" - {abbr}"))


def resolve_department_name(department_value, company=None):
	"""Resolve stem or link to ERPNext Department for *company* (e.g. Finance - CWSCL)."""
	if not (department_value or "").strip():
		return None

	value = department_value.strip()
	stem = normalize_department_stem(value)
	if not stem:
		frappe.throw("Department value is invalid.")

	def pick_one(filters_list):
		"""Return the single matching department name or throw on ambiguity."""
		names = frappe.get_all(
			"Department",
			filters=filters_list + [["disabled", "=", 0]],
			pluck="name",
			order_by="name asc",
		)
		if len(names) == 1:
			return names[0]
		if len(names) > 1:
			preview = ", ".join(names[:8])
			suffix = f"... ({len(names)} total)" if len(names) > 8 else ""
			frappe.throw(
				f"Multiple Departments match '{stem}' ({preview}{suffix}). "
				"Pick an exact ERPNext Department link name."
			)
		return None

	def resolve_for_company(co: str | None) -> str | None:
		if not co:
			return None
		abbr = frappe.db.get_value("Company", co, "abbr")
		if abbr:
			candidate = f"{stem} - {abbr}".strip()
			if frappe.db.exists("Department", candidate):
				return candidate
		return pick_one([["company", "=", co], ["department_name", "=", stem]])

	# 1. Always prefer the project / target company (local Finance - C must not stick on server).
	if company:
		matched = resolve_for_company(company)
		if matched:
			return matched

	# 2. Accept an exact link only when it matches that company.
	if frappe.db.exists("Department", value):
		if not company or _department_matches_company(value, company):
			return value

	fallback_company = get_default_company()
	if fallback_company and fallback_company != company:
		matched = resolve_for_company(fallback_company)
		if matched:
			return matched

	# 3. Unique department_name across companies.
	all_match = frappe.get_all(
		"Department",
		filters=[["department_name", "=", stem], ["disabled", "=", 0]],
		pluck="name",
		order_by="name asc",
	)
	if len(all_match) == 1:
		return all_match[0]
	if len(all_match) > 1:
		frappe.throw(
			f"Multiple Departments named '{stem}' exist across companies. "
			"Set Project.company or rename one."
		)

	frappe.throw(
		f"No Department found for '{stem}'"
		+ (f" under company {company}." if company else ".")
		+ f" Create Department '{stem} - <company abbr>' for that company."
	)
