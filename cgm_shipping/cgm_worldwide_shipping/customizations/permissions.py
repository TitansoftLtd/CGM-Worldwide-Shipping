"""Department resolution, RBAC, and Task permissions."""
from __future__ import annotations



import frappe
from erpnext import get_default_company

# Map template labels or old department names -> ERPNext department_name (before company suffix).
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	DEPARTMENT_NAME_ALIASES,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
	SEA_IMPORT_TEMPLATE,
	is_sea_import_task,
	sql_task_flow_key_in,
)


def get_department_name_stem(raw):
	"""Extract the department name before the company abbreviation suffix."""
	value = (raw or "").strip()
	if not value:
		return ""

	# 1. ERPNext department docnames follow `{department_name} - {abbr}` - strip the suffix.
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


# ============================================================

# ERPNext RBAC helpers for sea clearance tasks (roles match template departments).


@frappe.request_cache
def _department_stem_by_sequence() -> dict[int, str]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import load_sea_task_template

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


@frappe.request_cache
def configured_declaration_roles() -> frozenset[str]:
	"""Declarant roles from CGM Shipping Settings → Roles tab."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		get_cgm_shipping_settings,
	)

	settings = get_cgm_shipping_settings()
	if not settings or not settings.meta.has_field("custom_declaration_roles"):
		return frozenset()
	rows = settings.get("custom_declaration_roles") or []
	return frozenset(row.role for row in rows if row.role)


@frappe.request_cache
def declarant_application_department_stems() -> frozenset[str]:
	"""Department stems Declarant users may open (Declaration application steps only).

	Do not include Documentation / Operations / Finance here — those come from
	CGM Shipping Settings role groups and matching Role↔department stems.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		entry_application_sequences,
		permit_application_sequences,
		ucr_application_sequences,
	)

	stems: set[str] = set()
	for seq in (
		permit_application_sequences()
		| ucr_application_sequences()
		| entry_application_sequences()
	):
		stem = department_stem_for_sequence(seq)
		if stem:
			stems.add(stem)
	# Always include Declaration even if Settings template is incomplete.
	stems.add("Declaration")
	return frozenset(stems)


def user_has_declarant_department_access(user: str | None = None) -> bool:
	"""True when the user may work Declaration application tasks (UCR / permits / entry)."""
	roles = user_roles(user)
	if roles & declarant_application_department_stems():
		return True
	return bool(roles & configured_declaration_roles())


@frappe.request_cache
def transport_department_stems() -> frozenset[str]:
	"""Department stems for transport / empty-return container steps."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CONTAINER_UPDATE_TASK_SEQS,
		TRANSPORT_TASK_SEQS,
	)

	stems: set[str] = set()
	for seq in TRANSPORT_TASK_SEQS | CONTAINER_UPDATE_TASK_SEQS:
		stem = department_stem_for_sequence(seq)
		if stem and stem in {"Transport", "Field Operations"}:
			stems.add(stem)
	if not stems:
		stems.update({"Transport", "Field Operations"})
	return frozenset(stems)


@frappe.request_cache
def configured_transport_roles() -> frozenset[str]:
	"""Transport roles from CGM Shipping Settings → Roles tab."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		get_cgm_shipping_settings,
	)

	settings = get_cgm_shipping_settings()
	if not settings or not settings.meta.has_field("custom_transport_roles"):
		return frozenset()
	rows = settings.get("custom_transport_roles") or []
	return frozenset(row.role for row in rows if row.role)


def user_has_transport_department_access(user: str | None = None) -> bool:
	"""True when the user may work Transport / Field Operations sea tasks."""
	roles = user_roles(user)
	if roles & transport_department_stems():
		return True
	return bool(roles & configured_transport_roles())


def user_has_department_for_sequence(user: str | None, sequence_no: int) -> bool:
	stem = department_stem_for_sequence(sequence_no)
	if stem and stem in user_roles(user):
		return True
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_entry_application_task,
		is_kpa_application_task,
		is_permit_application_task,
		is_shipping_line_application_task,
		is_ucr_application_task,
	)

	if is_kpa_application_task(sequence_no):
		# KPA receipt is on the Operations supervisor task; Declarant roles are also allowed
		# (error message: "Only Declarant or Operations can attach KPA Receipt").
		return (
			user_has_operations_department_access(user)
			or user_has_declarant_department_access(user)
		)

	if (
		is_permit_application_task(sequence_no)
		or is_ucr_application_task(sequence_no)
		or is_entry_application_task(sequence_no)
		or is_shipping_line_application_task(sequence_no)
	):
		return user_has_declarant_department_access(user)

	ops_stems = operations_department_stems()
	if stem and ops_stems and stem in ops_stems:
		return user_has_operations_department_access(user)

	return False


@frappe.request_cache
def operations_department_stems() -> frozenset[str]:
	"""Department stems for KPA / supervisor application steps (from sea task template)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		kpa_application_sequences,
	)

	stems: set[str] = set()
	for seq in kpa_application_sequences():
		stem = department_stem_for_sequence(seq)
		if stem:
			stems.add(stem)
	return frozenset(stems)


def operations_visibility_department_stems() -> frozenset[str]:
	"""Departments Operations roles may see in Task list / form (aligned)."""
	return frozenset(set(operations_department_stems()) | {"Operations", "Documentation", "Field Operations"})


@frappe.request_cache
def finance_payment_department_stems() -> frozenset[str]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		finance_payment_sequences,
	)

	stems: set[str] = set()
	for seq in finance_payment_sequences():
		stem = department_stem_for_sequence(seq)
		if stem:
			stems.add(stem)
	return frozenset(stems)


@frappe.request_cache
def configured_finance_roles() -> frozenset[str]:
	"""Finance roles from CGM Shipping Settings → Roles tab."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		get_cgm_shipping_settings,
	)

	settings = get_cgm_shipping_settings()
	if not settings or not settings.meta.has_field("custom_finance_roles"):
		return frozenset()
	rows = settings.get("custom_finance_roles") or []
	return frozenset(row.role for row in rows if row.role)


@frappe.request_cache
def configured_operations_roles() -> frozenset[str]:
	"""Operations roles from CGM Shipping Settings → Roles tab."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		get_cgm_shipping_settings,
	)

	settings = get_cgm_shipping_settings()
	if not settings or not settings.meta.has_field("custom_operations_roles"):
		return frozenset()
	rows = settings.get("custom_operations_roles") or []
	return frozenset(row.role for row in rows if row.role)


def user_has_finance_department_access(user: str | None = None) -> bool:
	"""True when the user has a sea-template Finance department role or a Settings finance role."""
	roles = user_roles(user)
	if roles & finance_payment_department_stems():
		return True
	return bool(roles & configured_finance_roles())


def user_has_operations_department_access(user: str | None = None) -> bool:
	"""True when the user has a KPA/supervisor template department role or a Settings operations role."""
	roles = user_roles(user)
	if roles & operations_department_stems():
		return True
	return bool(roles & configured_operations_roles())


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


# ============================================================
# Restrict sea clearance Task list/form access by department and role.

# UCR / permit: cross-read on paired workflow steps (Settings-driven sequences).
def _ucr_linked_pairs() -> tuple[tuple[int, int], ...]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import ucr_linked_task_pairs

	return ucr_linked_task_pairs()


def _permit_linked_pairs() -> tuple[tuple[int, int], ...]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import permit_linked_task_pairs

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
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_task_name_by_sequence,
	)

	return bool(get_task_name_by_sequence(project, sequence_no))


def _user_can_access_linked_sea_project_task(doc, user: str) -> bool:
	"""Cross-read: Finance may open paired application tasks (not the reverse)."""
	if not hasattr(doc, "get"):
		return False
	if not is_sea_import_task(doc):
		return False
	if not user_has_finance_department_access(user):
		return False
	seq = int(doc.get("custom_sequence_no") or 0)
	project = doc.get("project")
	if not project:
		return False

	for app_seq, fin_seq in _ucr_linked_pairs():
		if seq == app_seq and _project_has_sea_task(project, fin_seq):
			return True

	for app_seq, fin_seq in _permit_linked_pairs():
		if seq == app_seq:
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

	# Sea workflow tasks are process-owned; role/department (and _assign) control access.
	# Do not grant all steps to whoever clicked Start Shipment (document owner).
	if user_is_assigned_to_task(doc, user):
		return True

	if department_matches_stems(department, get_user_sea_task_department_stems(user)):
		return True

	stem = normalize_department_stem(department)
	if (
		stem in declarant_application_department_stems()
		and user_has_declarant_department_access(user)
	):
		return True

	if stem in operations_visibility_department_stems() and user_has_operations_department_access(
		user
	):
		return True

	if stem in transport_department_stems() and user_has_transport_department_access(user):
		return True

	if _user_can_access_sea_payment_task_by_role(doc, user):
		return True

	return False


def _user_can_access_sea_payment_task_by_role(doc, user: str) -> bool:
	"""Finance payment tasks - user must have Role matching that step's template department."""
	if not hasattr(doc, "get"):
		return False
	if not is_sea_import_task(doc):
		return False
	seq = int(doc.get("custom_sequence_no") or 0)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import finance_payment_sequences

	if seq not in finance_payment_sequences():
		return False
	return user_has_finance_department_access(user)


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
	flow_in = sql_task_flow_key_in(SEA_IMPORT_TEMPLATE, column="lk.custom_task_flow_key")
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
				f"AND {flow_in} "
				f"AND lk.custom_sequence_no = {app_seq} LIMIT 1))"
			)
		for app_seq, fin_seq in _permit_linked_pairs():
			parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) = {fin_seq} "
				f"AND EXISTS (SELECT 1 FROM `tabTask` lk "
				f"WHERE lk.project = `tabTask`.project "
				f"AND {flow_in} "
				f"AND lk.custom_sequence_no = {app_seq} LIMIT 1))"
			)
	if stems & fin_stems:
		for app_seq, fin_seq in _ucr_linked_pairs():
			parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) = {app_seq} "
				f"AND EXISTS (SELECT 1 FROM `tabTask` lk "
				f"WHERE lk.project = `tabTask`.project "
				f"AND {flow_in} "
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

	stems = set(get_user_sea_task_department_stems(user))
	# Settings role groups → department stems (not the old broad app-stem dump).
	if user_has_declarant_department_access(user):
		stems |= set(declarant_application_department_stems())
	if user_has_operations_department_access(user):
		stems |= set(operations_visibility_department_stems())
	if user_has_transport_department_access(user):
		stems |= set(transport_department_stems())

	escaped_user = frappe.db.escape(user)
	assign_token = frappe.db.escape(f'"{user}"')
	sea_flow = sql_task_flow_key_in(SEA_IMPORT_TEMPLATE)
	non_sea = f"(NOT ({sea_flow}))"
	# Assignment only — not owner (Start Shipment used to make Declarants owner of every step).
	assigned_only = (
		f"(LOCATE({assign_token}, IFNULL(`tabTask`.`_assign`, '')) > 0)"
	)

	visibility_parts = [assigned_only]
	if stems:
		visibility_parts.insert(0, _build_department_sql_conditions(stems))

	# Finance: only finance payment sequences / Finance department — not Create UCR / permits.
	if user_has_finance_department_access(user):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import finance_payment_sequences

		stems |= set(finance_payment_department_stems())
		visibility_parts = [assigned_only]
		if stems:
			visibility_parts.insert(0, _build_department_sql_conditions(stems))

		finance_seqs = sorted(finance_payment_sequences())
		if finance_seqs:
			seq_list = ", ".join(str(s) for s in finance_seqs)
			visibility_parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) IN ({seq_list}))"
			)

	sea_visible = f"({sea_flow} AND ({' OR '.join(visibility_parts)}))"

	return f"({non_sea} OR {sea_visible})"


def has_permission(doc, ptype=None, user=None, **kwargs):
	"""Deny access to sea clearance tasks outside the user's departments."""
	user = user or frappe.session.user
	if user_bypasses_sea_task_department_filter(user):
		return True
	if not is_sea_import_task(doc):
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
