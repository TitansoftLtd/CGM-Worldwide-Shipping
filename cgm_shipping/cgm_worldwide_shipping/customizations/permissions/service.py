"""
ERPNext RBAC helpers for sea clearance tasks.

Administrators create Roles in Desk (names should match sea task template departments).
Access checks use frappe.get_roles() against template department stems — no role lists in code.
"""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import load_sea_task_template


@frappe.request_cache
def _department_stem_by_sequence() -> dict[int, str]:
	return {
		sequence_no: row["department"]
		for sequence_no, row in enumerate(load_sea_task_template(), start=1)
	}


def user_roles(user: str | None = None) -> set[str]:
	return set(frappe.get_roles(user or frappe.session.user))


def get_sea_task_template_department_stems() -> frozenset[str]:
	return frozenset(_department_stem_by_sequence().values())


def department_stem_for_sequence(sequence_no: int) -> str | None:
	return _department_stem_by_sequence().get(int(sequence_no or 0))


def get_user_sea_task_department_stems(user: str | None = None) -> set[str]:
	"""Template department stems the user may access via matching ERPNext Role names."""
	return set(get_sea_task_template_department_stems()) & user_roles(user)


def user_has_department_stem(user: str | None, stem: str) -> bool:
	return stem in user_roles(user)


def user_has_department_for_sequence(user: str | None, sequence_no: int) -> bool:
	stem = department_stem_for_sequence(sequence_no)
	return bool(stem and stem in user_roles(user))


@frappe.request_cache
def finance_payment_department_stems() -> frozenset[str]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements.service import (
		finance_payment_sequences,
	)

	stems: set[str] = set()
	for seq in finance_payment_sequences():
		stem = department_stem_for_sequence(seq)
		if stem:
			stems.add(stem)
	return frozenset(stems)


def user_has_finance_department_access(user: str | None = None) -> bool:
	"""True when the user has a Role matching a finance-payment task department from Settings."""
	return bool(get_user_sea_task_department_stems(user) & finance_payment_department_stems())


def application_department_stems_for_linked_pairs(
	pairs: tuple[tuple[int, int], ...],
) -> frozenset[str]:
	stems: set[str] = set()
	for app_seq, _fin_seq in pairs:
		stem = department_stem_for_sequence(app_seq)
		if stem:
			stems.add(stem)
	return frozenset(stems)


def finance_department_stems_for_linked_pairs(
	pairs: tuple[tuple[int, int], ...],
) -> frozenset[str]:
	stems: set[str] = set()
	for _app_seq, fin_seq in pairs:
		stem = department_stem_for_sequence(fin_seq)
		if stem:
			stems.add(stem)
	return frozenset(stems)
