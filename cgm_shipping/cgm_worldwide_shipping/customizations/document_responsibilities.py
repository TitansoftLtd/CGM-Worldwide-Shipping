"""Settings-driven who-may-upload / who-may-verify for sea clearance documents.

CGM Role Group (Link master):
  Create any group (Finance, Documentation, …), attach ERPNext Roles + department stems.

CGM Shipping Settings → Document responsibilities:
  Workflow + Action → Link to CGM Role Group.
"""

from __future__ import annotations

import frappe

# Stable action keys used in Settings rows and in code.
ACTION_UPLOAD_INVOICE = "Upload Invoice"
ACTION_VERIFY_INVOICE = "Verify Invoice"
ACTION_UPLOAD_POP = "Upload POP"
ACTION_UPLOAD_RECEIPT = "Upload Receipt"
ACTION_UPLOAD_CERTIFICATE = "Upload Certificate"
ACTION_MAKE_PAYMENT = "Make Payment"
ACTION_CONFIRM_CLIENT_PAID = "Confirm Client Paid"
ACTION_UPLOAD_DOCUMENT = "Upload Document"

FLOW_PERMIT = "Permit"
FLOW_UCR = "UCR"
FLOW_ENTRY = "Entry Slip"
FLOW_SHIPPING_LINE = "Shipping Line"
FLOW_KPA = "KPA"
FLOW_CLEARANCE_DOCUMENT = "Clearance Document"

ROLE_GROUP_FINANCE = "Finance"
ROLE_GROUP_DECLARATION = "Declaration"
ROLE_GROUP_OPERATIONS = "Operations"
ROLE_GROUP_TRANSPORT = "Transport"
ROLE_GROUP_DOCUMENTATION = "Documentation"

# name → (department_stems, default roles)
DEFAULT_ROLE_GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {
	ROLE_GROUP_FINANCE: (
		"Finance",
		("Finance Manager", "Finance User", "Accounts Manager", "Accounts User"),
	),
	ROLE_GROUP_DECLARATION: (
		"Declaration",
		("Declarant", "Declaration User"),
	),
	ROLE_GROUP_OPERATIONS: (
		"Operations,Field Operations",
		("Operations Manager", "Operations User"),
	),
	ROLE_GROUP_DOCUMENTATION: (
		"Documentation",
		("CGM Documentation", "Operations Manager"),
	),
	ROLE_GROUP_TRANSPORT: (
		"Transport",
		("Transport Manager", "Transport User", "Fleet Manager", "Transporter"),
	),
}

# Legacy alias used by older seed helpers
DEFAULT_ROLE_GROUP_ROLES = {
	name: roles for name, (_stems, roles) in DEFAULT_ROLE_GROUPS.items()
}

# (workflow_flow, action, role_group, notes)
DEFAULT_DOCUMENT_RESPONSIBILITIES: tuple[tuple[str, str, str, str], ...] = (
	(FLOW_PERMIT, ACTION_UPLOAD_INVOICE, ROLE_GROUP_DECLARATION, "Declarant attaches permit invoice"),
	(FLOW_PERMIT, ACTION_VERIFY_INVOICE, ROLE_GROUP_FINANCE, "Finance verifies before Make Payment"),
	(
		FLOW_PERMIT,
		ACTION_UPLOAD_RECEIPT,
		ROLE_GROUP_DECLARATION,
		"Same department that uploaded the invoice attaches the payment receipt",
	),
	(FLOW_PERMIT, ACTION_UPLOAD_CERTIFICATE, ROLE_GROUP_DECLARATION, "Declarant attaches permit certificate"),
	(FLOW_PERMIT, ACTION_MAKE_PAYMENT, ROLE_GROUP_FINANCE, "Finance creates Journal Entry"),
	(FLOW_PERMIT, ACTION_CONFIRM_CLIENT_PAID, ROLE_GROUP_FINANCE, "Finance selects Client will pay (skip company JE)"),
	(FLOW_UCR, ACTION_UPLOAD_INVOICE, ROLE_GROUP_DECLARATION, "Declarant attaches UCR invoice"),
	(FLOW_UCR, ACTION_VERIFY_INVOICE, ROLE_GROUP_FINANCE, "Finance verifies UCR invoice"),
	(
		FLOW_UCR,
		ACTION_UPLOAD_RECEIPT,
		ROLE_GROUP_DECLARATION,
		"Same department that uploaded the invoice attaches the UCR receipt",
	),
	(FLOW_UCR, ACTION_UPLOAD_CERTIFICATE, ROLE_GROUP_DECLARATION, "Declarant attaches IDF/UCR certificate"),
	(FLOW_UCR, ACTION_MAKE_PAYMENT, ROLE_GROUP_FINANCE, ""),
	(FLOW_UCR, ACTION_CONFIRM_CLIENT_PAID, ROLE_GROUP_FINANCE, ""),
	(FLOW_ENTRY, ACTION_UPLOAD_INVOICE, ROLE_GROUP_DECLARATION, ""),
	(FLOW_ENTRY, ACTION_VERIFY_INVOICE, ROLE_GROUP_FINANCE, ""),
	(FLOW_ENTRY, ACTION_UPLOAD_RECEIPT, ROLE_GROUP_FINANCE, ""),
	(FLOW_ENTRY, ACTION_MAKE_PAYMENT, ROLE_GROUP_FINANCE, ""),
	(FLOW_ENTRY, ACTION_CONFIRM_CLIENT_PAID, ROLE_GROUP_FINANCE, ""),
	(
		FLOW_SHIPPING_LINE,
		ACTION_UPLOAD_INVOICE,
		ROLE_GROUP_DOCUMENTATION,
		"Documentation attaches shipping line invoice",
	),
	(FLOW_SHIPPING_LINE, ACTION_VERIFY_INVOICE, ROLE_GROUP_FINANCE, "Finance verifies invoice and receipt"),
	(
		FLOW_SHIPPING_LINE,
		ACTION_UPLOAD_POP,
		ROLE_GROUP_FINANCE,
		"Finance attaches bank POP (or client shares POP via portal)",
	),
	(
		FLOW_SHIPPING_LINE,
		ACTION_UPLOAD_RECEIPT,
		ROLE_GROUP_DOCUMENTATION,
		"Documentation attaches shipping line receipt using the POP",
	),
	(FLOW_SHIPPING_LINE, ACTION_MAKE_PAYMENT, ROLE_GROUP_FINANCE, ""),
	(FLOW_SHIPPING_LINE, ACTION_CONFIRM_CLIENT_PAID, ROLE_GROUP_FINANCE, ""),
	(
		FLOW_KPA,
		ACTION_UPLOAD_INVOICE,
		ROLE_GROUP_OPERATIONS,
		"Field Ops / Operations attach KPA invoice",
	),
	(FLOW_KPA, ACTION_VERIFY_INVOICE, ROLE_GROUP_FINANCE, ""),
	(FLOW_KPA, ACTION_UPLOAD_RECEIPT, ROLE_GROUP_FINANCE, ""),
	(FLOW_KPA, ACTION_MAKE_PAYMENT, ROLE_GROUP_FINANCE, ""),
	(FLOW_KPA, ACTION_CONFIRM_CLIENT_PAID, ROLE_GROUP_FINANCE, ""),
	(FLOW_CLEARANCE_DOCUMENT, ACTION_UPLOAD_DOCUMENT, ROLE_GROUP_DECLARATION, "Default owner for clearance docs"),
	(
		FLOW_CLEARANCE_DOCUMENT,
		ACTION_UPLOAD_DOCUMENT,
		ROLE_GROUP_DOCUMENTATION,
		"Documentation may also attach clearance docs",
	),
	(
		FLOW_CLEARANCE_DOCUMENT,
		ACTION_UPLOAD_DOCUMENT,
		ROLE_GROUP_OPERATIONS,
		"Operations may also attach clearance docs",
	),
)

RESPONSIBILITIES_FIELD = "custom_document_responsibilities"
SETTINGS_ROLE_FIELDS = {
	ROLE_GROUP_FINANCE: "custom_finance_roles",
	ROLE_GROUP_DECLARATION: "custom_declaration_roles",
	ROLE_GROUP_OPERATIONS: "custom_operations_roles",
	ROLE_GROUP_TRANSPORT: "custom_transport_roles",
}


def _settings():
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		get_cgm_shipping_settings,
	)

	return get_cgm_shipping_settings()


def default_responsibility_rows() -> list[dict]:
	return [
		{
			"workflow_flow": flow,
			"action": action,
			"role_group": group,
			"notes": notes,
		}
		for flow, action, group, notes in DEFAULT_DOCUMENT_RESPONSIBILITIES
	]


def responsibilities_fingerprint(rows) -> frozenset[tuple[str, str, str]]:
	return frozenset(
		(
			(r.get("workflow_flow") or "").strip(),
			(r.get("action") or "").strip(),
			(r.get("role_group") or "").strip(),
		)
		for r in (rows or [])
		if (r.get("workflow_flow") or "").strip() and (r.get("action") or "").strip()
	)


def ensure_cgm_role_groups() -> bool:
	"""Create missing CGM Role Group masters; fill empty role lists only.

	Intended for one-time seeding — do not call from every ``after_migrate``.
	"""
	if not frappe.db.exists("DocType", "CGM Role Group"):
		return False

	settings = _settings() if frappe.db.exists("DocType", "CGM Shipping Settings") else None
	changed = False

	for name, (stems, default_roles) in DEFAULT_ROLE_GROUPS.items():
		roles_from_settings: list[str] = []
		fieldname = SETTINGS_ROLE_FIELDS.get(name)
		if settings and fieldname and settings.meta.has_field(fieldname):
			roles_from_settings = [r.role for r in (settings.get(fieldname) or []) if r.role]

		wanted_roles = roles_from_settings or [
			role for role in default_roles if frappe.db.exists("Role", role)
		]
		# Always prefer existing CGM Documentation on Documentation group if role exists.
		if name == ROLE_GROUP_DOCUMENTATION and frappe.db.exists("Role", "CGM Documentation"):
			if "CGM Documentation" not in wanted_roles:
				wanted_roles = ["CGM Documentation", *wanted_roles]

		if frappe.db.exists("CGM Role Group", name):
			doc = frappe.get_doc("CGM Role Group", name)
			current = {r.role for r in (doc.get("roles") or []) if r.role}
			row_changed = False
			if not doc.department_stems and stems:
				doc.department_stems = stems
				row_changed = True
			# Only fill empty role lists — never wipe custom membership.
			if not current and wanted_roles:
				for role in wanted_roles:
					doc.append("roles", {"role": role})
				row_changed = True
			if row_changed:
				doc.flags.ignore_permissions = True
				doc.save(ignore_permissions=True)
				changed = True
			continue

		doc = frappe.get_doc(
			{
				"doctype": "CGM Role Group",
				"role_group_name": name,
				"department_stems": stems,
				"roles": [{"role": role} for role in wanted_roles],
			}
		)
		doc.insert(ignore_permissions=True)
		changed = True

	return changed


def migrate_ucr_permit_receipt_upload_to_declaration(settings=None) -> bool:
	"""Move UCR / Permit Upload Receipt from Finance → Declaration when still on the old default.

	Does not touch Client will pay / Make Payment / Verify Invoice. Skips rows already
	reassigned away from Finance (admin edits stick).
	"""
	if settings is None:
		if not frappe.db.exists("DocType", "CGM Shipping Settings"):
			return False
		settings = frappe.get_doc("CGM Shipping Settings")
	meta = settings.meta if hasattr(settings, "meta") else None
	if meta and not meta.has_field(RESPONSIBILITIES_FIELD):
		return False
	if not frappe.db.exists("CGM Role Group", ROLE_GROUP_DECLARATION):
		return False

	notes = {
		FLOW_PERMIT: "Same department that uploaded the invoice attaches the payment receipt",
		FLOW_UCR: "Same department that uploaded the invoice attaches the UCR receipt",
	}
	changed = False
	for row in settings.get(RESPONSIBILITIES_FIELD) or []:
		if row.workflow_flow not in (FLOW_PERMIT, FLOW_UCR):
			continue
		if row.action != ACTION_UPLOAD_RECEIPT:
			continue
		if row.role_group != ROLE_GROUP_FINANCE:
			continue
		row.role_group = ROLE_GROUP_DECLARATION
		row.notes = notes.get(row.workflow_flow) or row.notes
		changed = True
	return changed


def migrate_shipping_line_pop_responsibilities(settings=None) -> bool:
	"""Shipping Line: add Upload POP (Finance) and move Upload Receipt → Documentation.

	Skips rows already reassigned away from the old Finance receipt default.
	"""
	if settings is None:
		if not frappe.db.exists("DocType", "CGM Shipping Settings"):
			return False
		settings = frappe.get_doc("CGM Shipping Settings")
	meta = settings.meta if hasattr(settings, "meta") else None
	if meta and not meta.has_field(RESPONSIBILITIES_FIELD):
		return False

	changed = False
	rows = settings.get(RESPONSIBILITIES_FIELD) or []
	has_pop = any(
		r.workflow_flow == FLOW_SHIPPING_LINE and r.action == ACTION_UPLOAD_POP for r in rows
	)
	if not has_pop and frappe.db.exists("CGM Role Group", ROLE_GROUP_FINANCE):
		settings.append(
			RESPONSIBILITIES_FIELD,
			{
				"workflow_flow": FLOW_SHIPPING_LINE,
				"action": ACTION_UPLOAD_POP,
				"role_group": ROLE_GROUP_FINANCE,
				"notes": "Finance attaches bank POP (or client shares POP via portal)",
			},
		)
		changed = True

	if frappe.db.exists("CGM Role Group", ROLE_GROUP_DOCUMENTATION):
		for row in settings.get(RESPONSIBILITIES_FIELD) or []:
			if row.workflow_flow != FLOW_SHIPPING_LINE:
				continue
			if row.action != ACTION_UPLOAD_RECEIPT:
				continue
			if row.role_group != ROLE_GROUP_FINANCE:
				continue
			row.role_group = ROLE_GROUP_DOCUMENTATION
			row.notes = "Documentation attaches shipping line receipt using the POP"
			changed = True
	return changed


def ensure_document_responsibilities(settings=None) -> bool:
	"""Add missing default responsibility rows (one-time seed helper).

	Skips (flow, action) pairs that already have a role_group (Clearance Document
	allows multiple groups). Call only from install/patch so deleted rows stay gone.
	"""
	if settings is None:
		if not frappe.db.exists("DocType", "CGM Shipping Settings"):
			return False
		settings = frappe.get_doc("CGM Shipping Settings")
	meta = settings.meta if hasattr(settings, "meta") else None
	if meta and not meta.has_field(RESPONSIBILITIES_FIELD):
		return False

	existing = set(responsibilities_fingerprint(settings.get(RESPONSIBILITIES_FIELD) or []))
	changed = False

	# Migrate early defaults toward Documentation for Shipping Line invoice upload.
	for row in settings.get(RESPONSIBILITIES_FIELD) or []:
		if (
			row.workflow_flow == FLOW_SHIPPING_LINE
			and row.action == ACTION_UPLOAD_INVOICE
			and row.role_group in (ROLE_GROUP_DECLARATION, ROLE_GROUP_OPERATIONS)
		):
			if frappe.db.exists("CGM Role Group", ROLE_GROUP_DOCUMENTATION):
				row.role_group = ROLE_GROUP_DOCUMENTATION
				row.notes = "Documentation attaches shipping line invoice"
				changed = True

	# UCR / Permit receipts: uploading department (Declaration), not Finance.
	# Client will pay / Share Invoice / Make Payment stay with Finance.
	if migrate_ucr_permit_receipt_upload_to_declaration(settings):
		changed = True
	if migrate_shipping_line_pop_responsibilities(settings):
		changed = True

	for row in default_responsibility_rows():
		key = (row["workflow_flow"], row["action"], row["role_group"])
		if key in existing:
			continue
		same_action = [
			r
			for r in (settings.get(RESPONSIBILITIES_FIELD) or [])
			if r.workflow_flow == row["workflow_flow"] and r.action == row["action"]
		]
		if same_action and row["workflow_flow"] != FLOW_CLEARANCE_DOCUMENT:
			continue
		if same_action and row["workflow_flow"] == FLOW_CLEARANCE_DOCUMENT:
			if any(r.role_group == row["role_group"] for r in same_action):
				continue
		# Skip Link rows if the Role Group master is missing (migrate not finished).
		if row["role_group"] and not frappe.db.exists("CGM Role Group", row["role_group"]):
			continue
		settings.append(RESPONSIBILITIES_FIELD, row)
		existing.add(key)
		changed = True
	return changed


def ensure_default_role_group_membership(settings=None) -> bool:
	"""Fill empty legacy Settings MultiSelect tables (kept in sync with CGM Role Group)."""
	if settings is None:
		if not frappe.db.exists("DocType", "CGM Shipping Settings"):
			return False
		settings = frappe.get_doc("CGM Shipping Settings")

	changed = False
	meta = settings.meta
	for group, fieldname in SETTINGS_ROLE_FIELDS.items():
		if not meta.has_field(fieldname):
			continue
		if settings.get(fieldname):
			continue
		for role in DEFAULT_ROLE_GROUP_ROLES.get(group, ()):
			if frappe.db.exists("Role", role):
				settings.append(fieldname, {"role": role})
				changed = True
	return changed


def ensure_document_responsibility_settings() -> bool:
	"""Seed Role Group masters + responsibilities matrix (one-time defaults).

	Call from ``after_install`` / a one-time migrate patch only — not from
	``after_migrate`` — so admins can delete or reassign rows without them
	coming back on the next ``bench migrate``.
	"""
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return False
	if not frappe.db.exists("DocType", "CGM Document Responsibility Item"):
		return False

	changed = ensure_cgm_role_groups()
	settings = frappe.get_doc("CGM Shipping Settings")
	changed = ensure_default_role_group_membership(settings) or changed
	changed = ensure_document_responsibilities(settings) or changed
	if changed:
		settings.save(ignore_permissions=True)
		frappe.clear_cache()
	return changed


@frappe.request_cache
def _responsibility_role_groups() -> dict[tuple[str, str], frozenset[str]]:
	"""(flow, action) → set of role group names from Settings (or defaults)."""
	mapping: dict[tuple[str, str], set[str]] = {}
	settings = _settings()
	rows = []
	if settings and settings.meta.has_field(RESPONSIBILITIES_FIELD):
		rows = settings.get(RESPONSIBILITIES_FIELD) or []
	if not rows:
		rows = default_responsibility_rows()
	for row in rows:
		flow = (row.get("workflow_flow") if hasattr(row, "get") else row.workflow_flow) or ""
		action = (row.get("action") if hasattr(row, "get") else row.action) or ""
		group = (row.get("role_group") if hasattr(row, "get") else row.role_group) or ""
		flow, action, group = flow.strip(), action.strip(), group.strip()
		if not flow or not action or not group:
			continue
		mapping.setdefault((flow, action), set()).add(group)
	return {k: frozenset(v) for k, v in mapping.items()}


def role_groups_for(flow: str, action: str) -> frozenset[str]:
	return _responsibility_role_groups().get((flow, action), frozenset())


@frappe.request_cache
def roles_for_group(role_group: str) -> frozenset[str]:
	"""ERPNext Roles attached to a CGM Role Group (Link master)."""
	if not role_group:
		return frozenset()
	if frappe.db.exists("DocType", "CGM Role Group") and frappe.db.exists(
		"CGM Role Group", role_group
	):
		rows = frappe.get_all(
			"CGM Role Item",
			filters={"parent": role_group, "parenttype": "CGM Role Group"},
			pluck="role",
		)
		roles = frozenset(r for r in rows if r)
		if roles:
			return roles

	# Legacy Settings MultiSelect fallback for the four classic groups.
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		configured_declaration_roles,
		configured_finance_roles,
		configured_operations_roles,
		configured_transport_roles,
	)

	legacy = {
		ROLE_GROUP_FINANCE: configured_finance_roles,
		ROLE_GROUP_DECLARATION: configured_declaration_roles,
		ROLE_GROUP_OPERATIONS: configured_operations_roles,
		ROLE_GROUP_TRANSPORT: configured_transport_roles,
	}
	getter = legacy.get(role_group)
	if getter:
		roles = getter()
		if roles:
			return roles
	return frozenset(DEFAULT_ROLE_GROUP_ROLES.get(role_group, ()))


@frappe.request_cache
def department_stems_for_group(role_group: str) -> frozenset[str]:
	if not role_group or not frappe.db.exists("DocType", "CGM Role Group"):
		return frozenset()
	if not frappe.db.exists("CGM Role Group", role_group):
		return frozenset()
	raw = frappe.db.get_value("CGM Role Group", role_group, "department_stems") or ""
	return frozenset(s.strip() for s in raw.split(",") if s.strip())


def user_matches_department_stems(stems: frozenset[str], user: str | None = None) -> bool:
	"""True when the user has an ERPNext Role whose name matches a department stem,
	or (best-effort) when any open Task department they own matches — role name is primary.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import user_roles

	if not stems:
		return False
	roles = user_roles(user)
	# Role named like the stem (e.g. "Documentation") or containing it.
	for stem in stems:
		if stem in roles:
			return True
		if any(stem.lower() in (r or "").lower() for r in roles):
			return True
	return False


def user_in_role_group(role_group: str, user: str | None = None) -> bool:
	"""True when user has a role on the CGM Role Group, or matches its department stems."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		user_has_declarant_department_access,
		user_has_finance_department_access,
		user_has_operations_department_access,
		user_roles,
	)

	user = user or frappe.session.user
	if user == "Administrator":
		return True

	if roles_for_group(role_group) & user_roles(user):
		return True

	stems = department_stems_for_group(role_group)
	if user_matches_department_stems(stems, user):
		return True

	# Classic department-access helpers for the built-in groups.
	if role_group == ROLE_GROUP_FINANCE:
		return user_has_finance_department_access(user)
	if role_group == ROLE_GROUP_DECLARATION:
		return user_has_declarant_department_access(user)
	if role_group in (ROLE_GROUP_OPERATIONS, ROLE_GROUP_DOCUMENTATION):
		# Documentation visibility is part of operations visibility stems.
		if role_group == ROLE_GROUP_DOCUMENTATION and "Documentation" in stems:
			roles = user_roles(user)
			if "CGM Documentation" in roles or "Documentation" in roles:
				return True
		return user_has_operations_department_access(user)
	if role_group == ROLE_GROUP_TRANSPORT:
		from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
			configured_transport_roles,
			transport_department_stems,
		)

		roles = user_roles(user)
		if roles & configured_transport_roles():
			return True
		return bool(roles & transport_department_stems())
	return False


def user_has_responsibility(flow: str, action: str, user: str | None = None) -> bool:
	"""True when the user belongs to any role group assigned to this flow+action."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	groups = role_groups_for(flow, action)
	if not groups:
		if action in (
			ACTION_VERIFY_INVOICE,
			ACTION_UPLOAD_RECEIPT,
			ACTION_UPLOAD_POP,
			ACTION_MAKE_PAYMENT,
			ACTION_CONFIRM_CLIENT_PAID,
		):
			groups = frozenset({ROLE_GROUP_FINANCE})
		else:
			groups = frozenset({ROLE_GROUP_DECLARATION})
	return any(user_in_role_group(g, user) for g in groups)


def flow_for_task(task) -> str | None:
	"""Best-effort workflow flow label for a Task doc / dict."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_entry_application_task,
		is_entry_finance_payment_task,
		is_kpa_application_task,
		is_kpa_finance_payment_task,
		is_permit_application_task,
		is_permit_finance_payment_task,
		is_shipping_line_application_task,
		is_shipping_line_finance_payment_task,
		is_ucr_application_task,
		is_ucr_finance_payment_task,
		task_sequence,
	)

	seq = task_sequence(task) if not isinstance(task, int) else int(task or 0)
	if is_permit_application_task(seq) or is_permit_finance_payment_task(seq):
		return FLOW_PERMIT
	if is_ucr_application_task(seq) or is_ucr_finance_payment_task(seq):
		return FLOW_UCR
	if is_entry_application_task(seq) or is_entry_finance_payment_task(seq):
		return FLOW_ENTRY
	if is_shipping_line_application_task(seq) or is_shipping_line_finance_payment_task(seq):
		return FLOW_SHIPPING_LINE
	if is_kpa_application_task(seq) or is_kpa_finance_payment_task(seq):
		return FLOW_KPA
	return FLOW_CLEARANCE_DOCUMENT


def flow_for_profile(profile) -> str:
	"""Map ApplicationFinanceProfile (or finance_payment_kind / key) → flow label."""
	kind = getattr(profile, "finance_payment_kind", None) or getattr(profile, "key", None) or profile
	kind = str(kind or "").strip()
	mapping = {
		"UCR": FLOW_UCR,
		"ucr": FLOW_UCR,
		"Entry Slip": FLOW_ENTRY,
		"entry": FLOW_ENTRY,
		"Shipping Line": FLOW_SHIPPING_LINE,
		"shipping_line": FLOW_SHIPPING_LINE,
		"KPA": FLOW_KPA,
		"kpa": FLOW_KPA,
		"Permit": FLOW_PERMIT,
	}
	return mapping.get(kind, FLOW_CLEARANCE_DOCUMENT)


def throw_unless_responsibility(flow: str, action: str, *, label: str | None = None) -> None:
	if user_has_responsibility(flow, action):
		return
	groups = sorted(role_groups_for(flow, action) or {ROLE_GROUP_FINANCE})
	who = ", ".join(groups)
	frappe.throw(
		f"Only <b>{who}</b> can {label or action.lower()} "
		f"(CGM Shipping Settings → Document responsibilities / CGM Role Group)."
	)


def responsibility_flags_for_user(user: str | None = None) -> dict[str, bool]:
	"""Flat flags for Task form JS (derived from Settings matrix)."""
	user = user or frappe.session.user
	money_flows = (FLOW_PERMIT, FLOW_UCR, FLOW_ENTRY, FLOW_SHIPPING_LINE, FLOW_KPA)
	return {
		"can_make_payment": any(
			user_has_responsibility(f, ACTION_MAKE_PAYMENT, user) for f in money_flows
		),
		"can_upload_receipt": any(
			user_has_responsibility(f, ACTION_UPLOAD_RECEIPT, user) for f in money_flows
		),
		"can_upload_pop": user_has_responsibility(
			FLOW_SHIPPING_LINE, ACTION_UPLOAD_POP, user
		),
		"can_verify_invoice": any(
			user_has_responsibility(f, ACTION_VERIFY_INVOICE, user) for f in money_flows
		),
		"can_upload_invoice": any(
			user_has_responsibility(f, ACTION_UPLOAD_INVOICE, user) for f in money_flows
		),
		"can_upload_certificate": any(
			user_has_responsibility(f, ACTION_UPLOAD_CERTIFICATE, user)
			for f in (FLOW_PERMIT, FLOW_UCR)
		),
		"can_confirm_client_paid": any(
			user_has_responsibility(f, ACTION_CONFIRM_CLIENT_PAID, user) for f in money_flows
		),
		"can_upload_document": user_has_responsibility(
			FLOW_CLEARANCE_DOCUMENT, ACTION_UPLOAD_DOCUMENT, user
		),
		"can_record_purchase_invoice": any(
			user_has_responsibility(f, ACTION_MAKE_PAYMENT, user) for f in money_flows
		)
		or bool(frappe.has_permission("Purchase Invoice", ptype="create", user=user)),
	}
