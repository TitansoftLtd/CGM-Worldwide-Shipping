"""Restrict sea clearance Task list/form access by department and role."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	SEA_TASK_FLOW_KEY,
	get_department_name_stem,
)

# Roles that see every sea clearance task (oversight).
UNRESTRICTED_SEA_TASK_ROLES = frozenset(
	{
		"Administrator",
		"System Manager",
		"Projects Manager",
	}
)

# ERPNext role → department stems from sea_clearance_flow.SEA_FREIGHT_TASK_TEMPLATE.
ROLE_DEPARTMENT_STEMS: dict[str, tuple[str, ...]] = {
	"Operations Manager": ("Operations", "Documentation"),
	"Operations User": ("Operations", "Documentation"),
	"Declaration User": ("Declaration",),
	"Declarant": ("Declaration",),
	"Finance Manager": ("Finance",),
	"Finance User": ("Finance",),
	"Accounts User": ("Finance",),
	"Accounts Manager": ("Finance",),
	"Field Officer": ("Field Operations",),
	"Transport Manager": ("Transport",),
	"Transport Officer": ("Transport",),
}

# UCR: Declarant ↔ Finance cross-read. Permits: Declarant may read finance task only.
UCR_LINKED_TASK_PAIRS: tuple[tuple[int, int], ...] = ((3, 4),)
PERMIT_LINKED_TASK_PAIRS: tuple[tuple[int, int], ...] = ((5, 6),)
PERMIT_FINANCE_SEQ_BY_APPLICATION: dict[int, int] = {5: 6}


def user_has_unrestricted_sea_task_access(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(frappe.get_roles(user)) & UNRESTRICTED_SEA_TASK_ROLES)


def get_user_sea_task_department_stems(user: str | None = None) -> set[str]:
	user = user or frappe.session.user
	stems: set[str] = set()
	for role in frappe.get_roles(user):
		stems.update(ROLE_DEPARTMENT_STEMS.get(role, ()))
	return stems


def department_matches_stems(department: str | None, stems: set[str]) -> bool:
	if not stems:
		return False
	return get_department_name_stem(department) in stems


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
	"""Cross-read for paired workflow tasks — Finance never gets Declaration permit tasks."""
	if not hasattr(doc, "get"):
		return False
	if doc.get("custom_task_flow_key") != SEA_TASK_FLOW_KEY:
		return False
	seq = int(doc.get("custom_sequence_no") or 0)
	project = doc.get("project")
	if not project:
		return False

	stems = get_user_sea_task_department_stems(user)
	if not stems:
		return False

	for app_seq, fin_seq in UCR_LINKED_TASK_PAIRS:
		if seq == fin_seq and "Declaration" in stems and _project_has_sea_task(project, app_seq):
			return True
		if seq == app_seq and "Finance" in stems and _project_has_sea_task(project, fin_seq):
			return True

	for app_seq, fin_seq in PERMIT_LINKED_TASK_PAIRS:
		if seq == fin_seq and "Declaration" in stems and _project_has_sea_task(project, app_seq):
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
	if user_has_unrestricted_sea_task_access(user):
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
	"""Finance payment tasks (seq 4,6,…) — allow Finance roles even if department link differs."""
	if not hasattr(doc, "get"):
		return False
	if doc.get("custom_task_flow_key") != SEA_TASK_FLOW_KEY:
		return False
	seq = int(doc.get("custom_sequence_no") or 0)
	if seq not in (4, 6, 12, 14, 18):
		return False
	return "Finance" in get_user_sea_task_department_stems(user)


def _build_department_sql_conditions(stems: set[str]) -> str:
	"""Match ERPNext Department link names (`{stem}` or `{stem} - {abbr}`).

	Avoid SQL ``%`` wildcards: permission fragments are inlined into queries that
	MySQLdb formats with pyformat, so ``LIKE 'foo-%'`` breaks list views.
	"""
	parts: list[str] = []
	for stem in sorted(stems):
		parts.append(f"`tabTask`.`department` = {frappe.db.escape(stem)}")
		prefix = frappe.db.escape(stem + " -")
		parts.append(f"LOCATE({prefix}, IFNULL(`tabTask`.`department`, '')) = 1")
	return "(" + " OR ".join(parts) + ")"


def _build_linked_sea_task_sql(stems: set[str]) -> str | None:
	"""SQL OR-clauses for linked UCR / permit tasks in list views."""
	flow = frappe.db.escape(SEA_TASK_FLOW_KEY)
	parts: list[str] = []
	if "Declaration" in stems:
		for app_seq, fin_seq in UCR_LINKED_TASK_PAIRS:
			parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) = {fin_seq} "
				f"AND EXISTS (SELECT 1 FROM `tabTask` lk "
				f"WHERE lk.project = `tabTask`.project "
				f"AND lk.custom_task_flow_key = {flow} "
				f"AND lk.custom_sequence_no = {app_seq} LIMIT 1))"
			)
		for app_seq, fin_seq in PERMIT_LINKED_TASK_PAIRS:
			parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) = {fin_seq} "
				f"AND EXISTS (SELECT 1 FROM `tabTask` lk "
				f"WHERE lk.project = `tabTask`.project "
				f"AND lk.custom_task_flow_key = {flow} "
				f"AND lk.custom_sequence_no = {app_seq} LIMIT 1))"
			)
	if "Finance" in stems:
		for app_seq, fin_seq in UCR_LINKED_TASK_PAIRS:
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
	if user_has_unrestricted_sea_task_access(user):
		return None

	stems = get_user_sea_task_department_stems(user)
	escaped_user = frappe.db.escape(user)
	non_sea = f"(IFNULL(`tabTask`.`custom_task_flow_key`, '') != {frappe.db.escape(SEA_TASK_FLOW_KEY)})"
	assigned_or_owner = (
		f"(`tabTask`.`owner` = {escaped_user} "
		f"OR LOCATE({escaped_user}, IFNULL(`tabTask`.`_assign`, '')) > 0)"
	)

	visibility_parts = [assigned_or_owner]
	if stems:
		visibility_parts.insert(0, _build_department_sql_conditions(stems))
	linked = _build_linked_sea_task_sql(stems)
	if linked:
		visibility_parts.append(linked)
	if "Finance" in stems:
		visibility_parts.append(
			f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) IN (4, 6, 12, 14, 18))"
		)

	sea_visible = (
		f"(`tabTask`.`custom_task_flow_key` = {frappe.db.escape(SEA_TASK_FLOW_KEY)} "
		f"AND ({' OR '.join(visibility_parts)}))"
	)

	return f"({non_sea} OR {sea_visible})"


def has_permission(doc, ptype=None, user=None, **kwargs):
	"""Deny access to sea clearance tasks outside the user's departments."""
	user = user or frappe.session.user
	if user_has_unrestricted_sea_task_access(user):
		return True
	if doc.get("custom_task_flow_key") != SEA_TASK_FLOW_KEY:
		return True
	if user_can_access_sea_task(doc, user):
		return True
	return False


def filter_sea_tasks_for_user(tasks: list[dict], user: str | None = None) -> list[dict]:
	"""Filter task rows (e.g. from SQL) for the current user's visibility."""
	user = user or frappe.session.user
	if user_has_unrestricted_sea_task_access(user):
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
