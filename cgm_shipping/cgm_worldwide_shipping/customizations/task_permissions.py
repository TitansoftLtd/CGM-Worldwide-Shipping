"""Restrict sea clearance Task list/form access by department and role."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.permissions_service import (
	application_department_stems_for_linked_pairs,
	finance_department_stems_for_linked_pairs,
	finance_payment_department_stems,
	get_user_sea_task_department_stems,
	user_has_department_for_sequence,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements_service import (
	finance_payment_sequences,
	permit_linked_task_pairs,
	ucr_linked_task_pairs,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	SEA_TASK_FLOW_KEY,
	normalize_department_stem,
)

# UCR / permit: cross-read on paired workflow steps (Settings-driven sequences).
def _ucr_linked_pairs() -> tuple[tuple[int, int], ...]:
	return ucr_linked_task_pairs()


def _permit_linked_pairs() -> tuple[tuple[int, int], ...]:
	return permit_linked_task_pairs()


def user_bypasses_sea_task_department_filter(user: str | None = None) -> bool:
	"""Only Administrator skips row-level sea task filtering."""
	return (user or frappe.session.user) == "Administrator"


def department_matches_stems(department: str | None, stems: set[str]) -> bool:
	if not stems:
		return False
	return normalize_department_stem(department) in stems


def user_is_assigned_to_task(doc, user: str) -> bool:
	assign = doc.get("_assign") if hasattr(doc, "get") else None
	if not assign:
		return False
	if isinstance(assign, str):
		try:
			assign = frappe.parse_json(assign)
		except Exception:
			assign = [assign]
	if isinstance(assign, list):
		return user in assign
	return False


def _project_has_sea_task(project: str, sequence_no: int) -> bool:
	if not project:
		return False
	return bool(
		frappe.db.exists(
			"Task",
			{
				"project": project,
				"custom_task_flow_key": SEA_TASK_FLOW_KEY,
				"custom_sequence_no": sequence_no,
			},
		)
	)


def _user_can_access_linked_sea_project_task(doc, user: str) -> bool:
	"""Cross-read for paired workflow tasks using template department stems."""
	if not hasattr(doc, "get"):
		return False
	if doc.get("custom_task_flow_key") != SEA_TASK_FLOW_KEY:
		return False
	seq = int(doc.get("custom_sequence_no") or 0)
	project = doc.get("project")
	if not project:
		return False

	for app_seq, fin_seq in _ucr_linked_pairs():
		if seq == fin_seq and user_has_department_for_sequence(user, app_seq):
			if _project_has_sea_task(project, app_seq):
				return True
		if seq == app_seq and user_has_department_for_sequence(user, fin_seq):
			if _project_has_sea_task(project, fin_seq):
				return True

	for app_seq, fin_seq in _permit_linked_pairs():
		if seq == fin_seq and user_has_department_for_sequence(user, app_seq):
			return True

	return False


def user_can_access_sea_task(
	doc,
	user: str | None = None,
	*,
	department: str | None = None,
	owner: str | None = None,
) -> bool:
	"""Whether *user* may read a single sea clearance task."""
	user = user or frappe.session.user
	if user_bypasses_sea_task_department_filter(user):
		return True

	if hasattr(doc, "get"):
		department = department if department is not None else doc.get("department")
		owner = owner if owner is not None else doc.get("owner")

	if owner == user or user_is_assigned_to_task(doc, user):
		return True

	if department_matches_stems(department, get_user_sea_task_department_stems(user)):
		return True

	if _user_can_access_sea_payment_task_by_role(doc, user):
		return True

	return _user_can_access_linked_sea_project_task(doc, user)


def _user_can_access_sea_payment_task_by_role(doc, user: str) -> bool:
	"""Finance payment tasks - user must have Role matching that step's template department."""
	if not hasattr(doc, "get"):
		return False
	if doc.get("custom_task_flow_key") != SEA_TASK_FLOW_KEY:
		return False
	seq = int(doc.get("custom_sequence_no") or 0)
	if seq not in finance_payment_sequences():
		return False
	return user_has_department_for_sequence(user, seq)


def _department_link_sql_fragment(stem: str) -> str:
	"""SQL: task department equals stem or '{stem} - {company abbr}' (any abbr)."""
	dept_col = "IFNULL(`tabTask`.`department`, '')"
	fragments = [
		f"`tabTask`.`department` = {frappe.db.escape(stem)}",
		f"LOCATE({frappe.db.escape(stem + ' -')}, {dept_col}) = 1",
	]
	# Avoid Operations stem matching Field Operations - CWSCL.
	if stem == "Operations":
		fragments[-1] = (
			f"(LOCATE({frappe.db.escape('Operations -')}, {dept_col}) = 1 "
			f"AND LOCATE({frappe.db.escape('Field Operations -')}, {dept_col}) != 1)"
		)
	return "(" + " OR ".join(fragments) + ")"


def _build_department_sql_conditions(stems: set[str]) -> str:
	parts = [_department_link_sql_fragment(stem) for stem in sorted(stems)]
	return "(" + " OR ".join(parts) + ")"


def _build_linked_sea_task_sql(stems: set[str]) -> str | None:
	"""SQL OR-clauses for linked UCR / permit tasks in list views."""
	flow = frappe.db.escape(SEA_TASK_FLOW_KEY)
	parts: list[str] = []
	app_stems = set(application_department_stems_for_linked_pairs(_ucr_linked_pairs()))
	app_stems |= set(application_department_stems_for_linked_pairs(_permit_linked_pairs()))
	fin_stems = finance_department_stems_for_linked_pairs(_ucr_linked_pairs())

	if stems & app_stems:
		for app_seq, fin_seq in _ucr_linked_pairs():
			parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) = {fin_seq} "
				f"AND EXISTS (SELECT 1 FROM `tabTask` lk "
				f"WHERE lk.project = `tabTask`.project "
				f"AND lk.custom_task_flow_key = {flow} "
				f"AND lk.custom_sequence_no = {app_seq} LIMIT 1))"
			)
		for app_seq, fin_seq in _permit_linked_pairs():
			parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) = {fin_seq} "
				f"AND EXISTS (SELECT 1 FROM `tabTask` lk "
				f"WHERE lk.project = `tabTask`.project "
				f"AND lk.custom_task_flow_key = {flow} "
				f"AND lk.custom_sequence_no = {app_seq} LIMIT 1))"
			)
	if stems & fin_stems:
		for app_seq, fin_seq in _ucr_linked_pairs():
			parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) = {app_seq} "
				f"AND EXISTS (SELECT 1 FROM `tabTask` lk "
				f"WHERE lk.project = `tabTask`.project "
				f"AND lk.custom_task_flow_key = {flow} "
				f"AND lk.custom_sequence_no = {fin_seq} LIMIT 1))"
			)
	if not parts:
		return None
	return "(" + " OR ".join(parts) + ")"


def get_permission_query_conditions(user: str | None = None) -> str | None:
	"""List view / report SQL filter for Task."""
	user = user or frappe.session.user
	if user_bypasses_sea_task_department_filter(user):
		return None

	stems = get_user_sea_task_department_stems(user)
	escaped_user = frappe.db.escape(user)
	assign_token = frappe.db.escape(f'"{user}"')
	non_sea = f"(IFNULL(`tabTask`.`custom_task_flow_key`, '') != {frappe.db.escape(SEA_TASK_FLOW_KEY)})"
	assigned_or_owner = (
		f"(`tabTask`.`owner` = {escaped_user} "
		f"OR LOCATE({assign_token}, IFNULL(`tabTask`.`_assign`, '')) > 0)"
	)

	visibility_parts = [assigned_or_owner]
	if stems:
		visibility_parts.insert(0, _build_department_sql_conditions(stems))
	linked = _build_linked_sea_task_sql(stems)
	if linked:
		visibility_parts.append(linked)
	if stems & finance_payment_department_stems():
		finance_seqs = sorted(finance_payment_sequences())
		if finance_seqs:
			seq_list = ", ".join(str(s) for s in finance_seqs)
			visibility_parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) IN ({seq_list}))"
			)

	sea_visible = (
		f"(`tabTask`.`custom_task_flow_key` = {frappe.db.escape(SEA_TASK_FLOW_KEY)} "
		f"AND ({' OR '.join(visibility_parts)}))"
	)

	return f"({non_sea} OR {sea_visible})"


def has_permission(doc, ptype=None, user=None, **kwargs):
	"""Deny access to sea clearance tasks outside the user's departments."""
	user = user or frappe.session.user
	if user_bypasses_sea_task_department_filter(user):
		return True
	if doc.get("custom_task_flow_key") != SEA_TASK_FLOW_KEY:
		return True
	if user_can_access_sea_task(doc, user):
		return True
	return False


def filter_sea_tasks_for_user(tasks: list[dict], user: str | None = None) -> list[dict]:
	"""Filter task rows (e.g. from SQL) for the current user's visibility."""
	user = user or frappe.session.user
	if user_bypasses_sea_task_department_filter(user):
		return tasks
	out: list[dict] = []
	for row in tasks:
		if user_can_access_sea_task(
			row,
			user,
			department=row.get("department"),
			owner=row.get("owner"),
		):
			out.append(row)
	return out
