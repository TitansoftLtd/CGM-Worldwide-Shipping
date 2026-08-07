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
	"""Template department stems the user may access via an ERPNext Role named exactly like the stem."""
	return set(get_sea_task_template_department_stems()) & user_roles(user)


def _roles_from_cgm_role_group(group_name: str) -> frozenset[str]:
	if not group_name or not frappe.db.exists("DocType", "CGM Role Group"):
		return frozenset()
	if not frappe.db.exists("CGM Role Group", group_name):
		return frozenset()
	rows = frappe.get_all(
		"CGM Role Item",
		filters={"parent": group_name, "parenttype": "CGM Role Group"},
		pluck="role",
	)
	return frozenset(r for r in rows if r)


def _roles_from_settings_field(fieldname: str) -> frozenset[str]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		get_cgm_shipping_settings,
	)

	settings = get_cgm_shipping_settings()
	if not settings or not settings.meta.has_field(fieldname):
		return frozenset()
	rows = settings.get(fieldname) or []
	return frozenset(row.role for row in rows if row.role)


# Desk / module roles often added so staff can open Task/Project — they must NOT
# unlock every clearance department when mistakenly listed under Ops/Declaration.
DESK_ROLES_IGNORED_FOR_DEPARTMENT_ACCESS = frozenset(
	{
		"All",
		"Guest",
		"Desk User",
		"Administrator",
		"System Manager",
		"Projects User",
		"Projects Manager",
		"Dashboard Manager",
		"Supplier",
	}
)


def _department_grant_roles(roles: frozenset[str] | set[str]) -> frozenset[str]:
	"""Roles that may grant a clearance department (excludes desk scaffolding roles)."""
	return frozenset(r for r in roles if r and r not in DESK_ROLES_IGNORED_FOR_DEPARTMENT_ACCESS)


@frappe.request_cache
def configured_declaration_roles() -> frozenset[str]:
	"""Declarant roles from CGM Role Group and/or Settings → Roles tab."""
	return _department_grant_roles(
		_roles_from_cgm_role_group("Declaration")
		| _roles_from_settings_field("custom_declaration_roles")
	)


@frappe.request_cache
def declarant_application_department_stems() -> frozenset[str]:
	"""Department stem for Declaration visibility.

	Always ``Declaration`` — do not derive stems from Settings application sequence
	markers. Those can drift from the live task template (e.g. Entry Application on
	seq 12 while the template has Finance Pays Entry Slip there), which previously
	opened Finance tasks to Declarants.
	"""
	return frozenset({"Declaration"})


def user_has_declarant_department_access(user: str | None = None) -> bool:
	"""True when the user has a role listed under Declaration roles (Settings / Role Group)."""
	return bool(_department_grant_roles(user_roles(user)) & configured_declaration_roles())


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
	"""Transport roles from CGM Role Group and/or Settings → Roles tab."""
	return _department_grant_roles(
		_roles_from_cgm_role_group("Transport")
		| _roles_from_settings_field("custom_transport_roles")
	)


def user_has_transport_department_access(user: str | None = None) -> bool:
	"""True when the user has a role listed under Transport roles (Settings / Role Group)."""
	return bool(_department_grant_roles(user_roles(user)) & configured_transport_roles())


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
		# KPA application task: Operations/Declarant attach the invoice (receipt is Finance-owned).
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


def _default_stems_for_role_group(group_name: str) -> frozenset[str]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		DEFAULT_ROLE_GROUPS,
	)

	raw, _roles = DEFAULT_ROLE_GROUPS.get(group_name, ("", ()))
	return frozenset(s.strip() for s in (raw or "").split(",") if s.strip())


def _stems_for_role_group(group_name: str) -> frozenset[str]:
	"""CGM Role Group department_stems, falling back to seeded defaults."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		department_stems_for_group,
	)

	stems = department_stems_for_group(group_name)
	return stems if stems else _default_stems_for_role_group(group_name)


def operations_visibility_department_stems() -> frozenset[str]:
	"""Departments Operations roles may see — from CGM Role Group only (not Documentation)."""
	stems = set(_stems_for_role_group("Operations"))
	stems |= set(operations_department_stems())
	stems.add("Operations")
	# Never bundle Documentation into Operations visibility.
	stems.discard("Documentation")
	return frozenset(stems)


def documentation_visibility_department_stems() -> frozenset[str]:
	"""Departments Documentation roles may see in Task list / form."""
	stems = set(_stems_for_role_group("Documentation"))
	stems.add("Documentation")
	return frozenset(stems)


@frappe.request_cache
def finance_payment_department_stems() -> frozenset[str]:
	"""Department stem for Finance payment visibility.

	Always ``Finance`` — do not derive stems from Settings ``Finance Payment``
	sequence numbers. Those markers can drift from the live task template
	(e.g. seq 11 marked payment while the template has Create Entry there),
	which previously opened Operations / Declaration / Transport to Finance users.
	"""
	return frozenset({"Finance"})


def finance_visibility_payment_sequences() -> frozenset[int]:
	"""Finance Payment sequences whose live template department is actually Finance."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import finance_payment_sequences

	aligned = {
		seq
		for seq in finance_payment_sequences()
		if department_stem_for_sequence(seq) == "Finance"
	}
	if aligned:
		return frozenset(aligned)
	# Fallback: every template row on the Finance department.
	return frozenset(
		seq
		for seq, stem in _department_stem_by_sequence().items()
		if stem == "Finance"
	)


@frappe.request_cache
def configured_finance_roles() -> frozenset[str]:
	"""Finance roles from CGM Role Group and/or Settings → Roles tab."""
	return _department_grant_roles(
		_roles_from_cgm_role_group("Finance") | _roles_from_settings_field("custom_finance_roles")
	)


@frappe.request_cache
def configured_operations_roles() -> frozenset[str]:
	"""Operations roles from CGM Role Group and/or Settings → Roles tab."""
	return _department_grant_roles(
		_roles_from_cgm_role_group("Operations")
		| _roles_from_settings_field("custom_operations_roles")
	)


@frappe.request_cache
def configured_documentation_roles() -> frozenset[str]:
	"""Documentation roles from CGM Role Group and/or Settings → Roles tab.

	No hardcoded default roles here — empty list means nobody gets Documentation tasks
	until roles are placed on the Documentation list (same rule as Finance / Operations).
	"""
	return _department_grant_roles(
		_roles_from_cgm_role_group("Documentation")
		| _roles_from_settings_field("custom_documentation_roles")
	)


def user_has_finance_department_access(user: str | None = None) -> bool:
	"""True when the user has a role listed under Finance roles (Settings / Role Group)."""
	return bool(_department_grant_roles(user_roles(user)) & configured_finance_roles())


def user_has_operations_department_access(user: str | None = None) -> bool:
	"""True when the user has a role listed under Operations roles (Settings / Role Group)."""
	return bool(_department_grant_roles(user_roles(user)) & configured_operations_roles())


def user_has_documentation_department_access(user: str | None = None) -> bool:
	"""True when the user has a role listed under Documentation roles (Settings / Role Group).

	Role name alone (e.g. CGM Documentation) does not grant Documentation tasks —
	the role must be placed on the Documentation list. Placing it under Operations
	grants Operations-department tasks instead.
	"""
	return bool(_department_grant_roles(user_roles(user)) & configured_documentation_roles())


def visibility_department_stems_for_user(user: str | None = None) -> set[str]:
	"""Department stems from Roles-tab membership only.

	Example: role listed under Operations roles → Operations department tasks only.
	Finance roles → Finance tasks only. Declaration roles → Declaration only.
	A role listed in two groups sees both departments' tasks.

	Desk roles such as Projects User never unlock a department, even if still listed
	under Operations / Declaration in Settings.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		ROLE_GROUP_DECLARATION,
		ROLE_GROUP_DOCUMENTATION,
		ROLE_GROUP_FINANCE,
		ROLE_GROUP_OPERATIONS,
		ROLE_GROUP_TRANSPORT,
	)

	roles = _department_grant_roles(user_roles(user))
	stems: set[str] = set(get_user_sea_task_department_stems(user))

	group_specs: list[tuple[str, frozenset[str], frozenset[str]]] = [
		(ROLE_GROUP_FINANCE, configured_finance_roles(), finance_payment_department_stems() or frozenset({"Finance"})),
		(
			ROLE_GROUP_DECLARATION,
			configured_declaration_roles(),
			declarant_application_department_stems(),
		),
		(
			ROLE_GROUP_OPERATIONS,
			configured_operations_roles(),
			frozenset({"Operations"}),
		),
		(
			ROLE_GROUP_DOCUMENTATION,
			configured_documentation_roles(),
			frozenset({"Documentation"}),
		),
		(
			ROLE_GROUP_TRANSPORT,
			configured_transport_roles(),
			transport_department_stems(),
		),
	]

	for group_name, group_roles, fallback in group_specs:
		if not (roles & group_roles):
			continue
		group_stems = set(_stems_for_role_group(group_name) or fallback)
		if group_name == ROLE_GROUP_OPERATIONS:
			# Operations list must never open Documentation tasks.
			group_stems.discard("Documentation")
			if not group_stems:
				group_stems = {"Operations"}
		stems |= group_stems

	return stems


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


def _shipping_line_linked_pairs() -> tuple[tuple[int, int], ...]:
	"""(application_seq, finance_seq) for Shipping Line POP/receipt handoff."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
		get_application_finance_sequence,
		get_application_sequence,
	)

	profile = APPLICATION_FINANCE_PROFILES.get("Shipping Line Application")
	if not profile:
		return ()
	app = get_application_sequence(profile)
	fin = get_application_finance_sequence(profile)
	if app and fin:
		return ((int(app), int(fin)),)
	return ()


def user_bypasses_sea_task_department_filter(user: str | None = None) -> bool:
	"""Only Administrator skips row-level sea task filtering."""
	return (user or frappe.session.user) == "Administrator"


def is_clearance_department_restricted_task(doc) -> bool:
	"""True when Task must pass department/role checks.

	Sea-import flow keys are the primary signal. Also treat any Task whose
	department stem is a sea-template department as restricted — otherwise a
	mismatched/blank ``custom_task_flow_key`` would leak every clearance task
	to users who only have Task read (e.g. Projects User on Assistant Finance Manager).
	"""
	if is_sea_import_task(doc):
		return True
	if not hasattr(doc, "get"):
		return False
	stem = normalize_department_stem(doc.get("department"))
	if not stem:
		return False
	return stem in get_sea_task_template_department_stems()


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
	"""Cross-access paired application ↔ finance tasks.

	- Finance may open the paired application task.
	- Declaration may open the paired Finance pays task when they own Upload Receipt
	  (same department that uploaded the invoice attaches the receipt).
	- Documentation may open Finance Pays Shipping Line when they own Upload Receipt
	  (attach receipt using the POP).
	"""
	if not hasattr(doc, "get"):
		return False
	if not is_sea_import_task(doc):
		return False
	seq = int(doc.get("custom_sequence_no") or 0)
	project = doc.get("project")
	if not project:
		return False

	if user_has_finance_department_access(user):
		for app_seq, fin_seq in _ucr_linked_pairs():
			if seq == app_seq and _project_has_sea_task(project, fin_seq):
				return True
		for app_seq, _fin_seq in _permit_linked_pairs():
			if seq == app_seq:
				return True
		for app_seq, fin_seq in _shipping_line_linked_pairs():
			if seq == app_seq and _project_has_sea_task(project, fin_seq):
				return True

	if user_has_declarant_department_access(user):
		from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
			ACTION_UPLOAD_RECEIPT,
			FLOW_PERMIT,
			FLOW_UCR,
			user_has_responsibility,
		)

		if user_has_responsibility(FLOW_UCR, ACTION_UPLOAD_RECEIPT, user):
			for app_seq, fin_seq in _ucr_linked_pairs():
				if seq == fin_seq and _project_has_sea_task(project, app_seq):
					return True
		if user_has_responsibility(FLOW_PERMIT, ACTION_UPLOAD_RECEIPT, user):
			for _app_seq, fin_seq in _permit_linked_pairs():
				if seq == fin_seq:
					return True

	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		ACTION_UPLOAD_RECEIPT,
		FLOW_SHIPPING_LINE,
		user_has_responsibility,
	)

	if user_has_responsibility(FLOW_SHIPPING_LINE, ACTION_UPLOAD_RECEIPT, user):
		for app_seq, fin_seq in _shipping_line_linked_pairs():
			if seq == fin_seq and _project_has_sea_task(project, app_seq):
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

	if department_matches_stems(department, visibility_department_stems_for_user(user)):
		return True

	if _user_can_access_sea_payment_task_by_role(doc, user):
		return True

	if _user_can_access_linked_sea_project_task(doc, user):
		return True

	return False


def _user_can_access_sea_payment_task_by_role(doc, user: str) -> bool:
	"""Finance payment tasks — Settings finance roles / Finance department stem."""
	if not hasattr(doc, "get"):
		return False
	seq = int(doc.get("custom_sequence_no") or 0)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import finance_payment_sequences

	if seq not in finance_payment_sequences():
		return False
	# Stale Settings markers must not open non-Finance template steps.
	if department_stem_for_sequence(seq) != "Finance":
		return False
	stem = normalize_department_stem(doc.get("department"))
	if stem and stem not in finance_payment_department_stems():
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


def _linked_pairs_aligned_to_finance_department(
	pairs: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
	"""Keep only (app, finance) pairs whose finance sequence is on Finance in the live template."""
	return tuple(
		(app_seq, fin_seq)
		for app_seq, fin_seq in pairs
		if department_stem_for_sequence(fin_seq) == "Finance"
	)


def _build_linked_sea_task_sql(stems: set[str]) -> str | None:
	"""SQL OR-clauses for linked UCR / permit / Shipping Line tasks in list views."""
	flow_in = sql_task_flow_key_in(SEA_IMPORT_TEMPLATE, column="lk.custom_task_flow_key")
	parts: list[str] = []
	ucr_pairs = _linked_pairs_aligned_to_finance_department(_ucr_linked_pairs())
	permit_pairs = _linked_pairs_aligned_to_finance_department(_permit_linked_pairs())
	shipping_pairs = _linked_pairs_aligned_to_finance_department(_shipping_line_linked_pairs())

	app_stems = set(application_department_stems_for_linked_pairs(ucr_pairs))
	app_stems |= set(application_department_stems_for_linked_pairs(permit_pairs))
	app_stems |= set(application_department_stems_for_linked_pairs(shipping_pairs))
	fin_stems = set(finance_department_stems_for_linked_pairs(ucr_pairs))
	fin_stems |= set(finance_department_stems_for_linked_pairs(permit_pairs))
	fin_stems |= set(finance_department_stems_for_linked_pairs(shipping_pairs))

	if stems & app_stems:
		for app_seq, fin_seq in ucr_pairs:
			parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) = {fin_seq} "
				f"AND EXISTS (SELECT 1 FROM `tabTask` lk "
				f"WHERE lk.project = `tabTask`.project "
				f"AND {flow_in} "
				f"AND lk.custom_sequence_no = {app_seq} LIMIT 1))"
			)
		for app_seq, fin_seq in permit_pairs:
			parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) = {fin_seq} "
				f"AND EXISTS (SELECT 1 FROM `tabTask` lk "
				f"WHERE lk.project = `tabTask`.project "
				f"AND {flow_in} "
				f"AND lk.custom_sequence_no = {app_seq} LIMIT 1))"
			)
		for app_seq, fin_seq in shipping_pairs:
			parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) = {fin_seq} "
				f"AND EXISTS (SELECT 1 FROM `tabTask` lk "
				f"WHERE lk.project = `tabTask`.project "
				f"AND {flow_in} "
				f"AND lk.custom_sequence_no = {app_seq} LIMIT 1))"
			)
	if stems & fin_stems:
		for app_seq, fin_seq in ucr_pairs:
			parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) = {app_seq} "
				f"AND EXISTS (SELECT 1 FROM `tabTask` lk "
				f"WHERE lk.project = `tabTask`.project "
				f"AND {flow_in} "
				f"AND lk.custom_sequence_no = {fin_seq} LIMIT 1))"
			)
		for app_seq, fin_seq in permit_pairs:
			parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) = {app_seq} "
				f"AND EXISTS (SELECT 1 FROM `tabTask` lk "
				f"WHERE lk.project = `tabTask`.project "
				f"AND {flow_in} "
				f"AND lk.custom_sequence_no = {fin_seq} LIMIT 1))"
			)
		for app_seq, fin_seq in shipping_pairs:
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


def _finance_only_visibility(user: str) -> bool:
	"""True when user is Finance Settings/role only (not Ops/Declarant/Documentation/Transport)."""
	return user_has_finance_department_access(user) and not (
		user_has_operations_department_access(user)
		or user_has_declarant_department_access(user)
		or user_has_documentation_department_access(user)
		or user_has_transport_department_access(user)
	)


def _documentation_only_visibility(user: str) -> bool:
	"""True when user is Documentation Settings/role only."""
	return user_has_documentation_department_access(user) and not (
		user_has_finance_department_access(user)
		or user_has_operations_department_access(user)
		or user_has_declarant_department_access(user)
		or user_has_transport_department_access(user)
	)


def _operations_only_visibility(user: str) -> bool:
	"""True when user is Operations Settings/role only."""
	return user_has_operations_department_access(user) and not (
		user_has_finance_department_access(user)
		or user_has_documentation_department_access(user)
		or user_has_declarant_department_access(user)
		or user_has_transport_department_access(user)
	)


def _transport_only_visibility(user: str) -> bool:
	"""True when user is Transport Settings/role only."""
	return user_has_transport_department_access(user) and not (
		user_has_finance_department_access(user)
		or user_has_documentation_department_access(user)
		or user_has_declarant_department_access(user)
		or user_has_operations_department_access(user)
	)


def _declaration_only_visibility(user: str) -> bool:
	"""True when user is Declaration Settings/role only."""
	return user_has_declarant_department_access(user) and not (
		user_has_finance_department_access(user)
		or user_has_documentation_department_access(user)
		or user_has_operations_department_access(user)
		or user_has_transport_department_access(user)
	)


def _department_only_sql(
	*,
	restricted: str,
	assigned_only: str,
	stems: set[str],
	extra_parts: list[str] | None = None,
) -> str:
	"""List filter locked to the given department stems (+ optional extras like assignment)."""
	visibility_parts = [assigned_only, _build_department_sql_conditions(stems)]
	if extra_parts:
		visibility_parts.extend(extra_parts)
	restricted_visible = f"({restricted} AND ({' OR '.join(visibility_parts)}))"
	unrestricted = f"(NOT ({restricted}))"
	return f"({unrestricted} OR {restricted_visible})"


def get_permission_query_conditions(user: str | None = None) -> str | None:
	"""List view / report SQL filter for Task."""
	user = user or frappe.session.user
	if user_bypasses_sea_task_department_filter(user):
		return None

	# One CGM Role Group → only that group's department stems (no cross-department dump).
	stems = visibility_department_stems_for_user(user)

	assign_token = frappe.db.escape(f'"{user}"')
	sea_flow = sql_task_flow_key_in(SEA_IMPORT_TEMPLATE)
	# Also restrict by clearance department stem so a wrong/blank flow key cannot leak tasks.
	clearance_dept = _build_department_sql_conditions(
		set(get_sea_task_template_department_stems())
	)
	restricted = f"(({sea_flow}) OR {clearance_dept})"
	# Assignment only — not owner (Start Shipment used to make Declarants owner of every step).
	assigned_only = f"(LOCATE({assign_token}, IFNULL(`tabTask`.`_assign`, '')) > 0)"

	# Single-department users: lock to that department only (no cross-department handoff leaks).
	if _documentation_only_visibility(user):
		return _department_only_sql(
			restricted=restricted,
			assigned_only=assigned_only,
			stems=set(documentation_visibility_department_stems()) or {"Documentation"},
		)
	if _operations_only_visibility(user):
		return _department_only_sql(
			restricted=restricted,
			assigned_only=assigned_only,
			stems=set(operations_visibility_department_stems()) or {"Operations"},
		)
	if _transport_only_visibility(user):
		return _department_only_sql(
			restricted=restricted,
			assigned_only=assigned_only,
			stems=set(transport_department_stems()) | set(_stems_for_role_group("Transport")),
		)
	if _finance_only_visibility(user):
		fin_stems = set(finance_payment_department_stems()) or {"Finance"}
		extra: list[str] = []
		finance_seqs = sorted(finance_visibility_payment_sequences())
		if finance_seqs:
			seq_list = ", ".join(str(s) for s in finance_seqs)
			extra.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) IN ({seq_list}) "
				f"AND {_build_department_sql_conditions(fin_stems)})"
			)
		return _department_only_sql(
			restricted=restricted,
			assigned_only=assigned_only,
			stems=fin_stems,
			extra_parts=extra,
		)
	if _declaration_only_visibility(user):
		# Declaration department only — never Finance via stale application markers.
		return _department_only_sql(
			restricted=restricted,
			assigned_only=assigned_only,
			stems=set(declarant_application_department_stems()) or {"Declaration"},
		)

	# Hybrid users (roles in more than one Settings list): union of their departments.
	visibility_parts = [assigned_only]
	if stems:
		visibility_parts.insert(0, _build_department_sql_conditions(stems))

	linked = _build_linked_sea_task_sql(stems)
	if linked:
		visibility_parts.append(linked)

	if user_has_finance_department_access(user):
		stems |= set(finance_payment_department_stems())
		visibility_parts = [assigned_only]
		if stems:
			visibility_parts.insert(0, _build_department_sql_conditions(stems))
		finance_seqs = sorted(finance_visibility_payment_sequences())
		if finance_seqs:
			seq_list = ", ".join(str(s) for s in finance_seqs)
			visibility_parts.append(
				f"(IFNULL(`tabTask`.`custom_sequence_no`, 0) IN ({seq_list}) "
				f"AND {_build_department_sql_conditions(set(finance_payment_department_stems()) or {'Finance'})})"
			)
		linked = _build_linked_sea_task_sql(stems)
		if linked:
			visibility_parts.append(linked)

	restricted_visible = f"({restricted} AND ({' OR '.join(visibility_parts)}))"
	unrestricted = f"(NOT ({restricted}))"

	return f"({unrestricted} OR {restricted_visible})"


def has_permission(doc, ptype=None, user=None, **kwargs):
	"""Deny access to clearance tasks outside the user's departments."""
	user = user or frappe.session.user
	if user_bypasses_sea_task_department_filter(user):
		return True
	if not is_clearance_department_restricted_task(doc):
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
		if not is_clearance_department_restricted_task(row):
			out.append(row)
			continue
		if user_can_access_sea_task(
			row,
			user,
			department=row.get("department"),
			owner=row.get("owner"),
		):
			out.append(row)
	return out
