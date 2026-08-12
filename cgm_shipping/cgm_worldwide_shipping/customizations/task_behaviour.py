"""Template-driven task behaviour — Role / Payment Kind / Permit Stage on Task.

Prefer stamped Task fields from CGM Task Template Item. Fall back to Sea Import
Settings sequence maps when ``custom_task_role`` is empty (legacy projects).
"""

from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe.utils import cint

ROLE_STANDARD = "Standard"
ROLE_DOCUMENT = "Document"
ROLE_DOCUMENT_CHECKPOINT = "Document Checkpoint"
ROLE_APPLICATION = "Application"
ROLE_FINANCE_PAYMENT = "Finance Payment"
ROLE_PERMIT_APPLICATION = "Permit Application"
ROLE_PERMIT_FINANCE = "Permit Finance"
ROLE_AUTO_COMPLETE = "Auto Complete"

APPLICATION_ROLES = frozenset({ROLE_APPLICATION})
FINANCE_ROLES = frozenset({ROLE_FINANCE_PAYMENT})
PERMIT_APPLICATION_ROLES = frozenset({ROLE_PERMIT_APPLICATION})
PERMIT_FINANCE_ROLES = frozenset({ROLE_PERMIT_FINANCE})
DOCUMENT_ROLES = frozenset({ROLE_DOCUMENT, ROLE_DOCUMENT_CHECKPOINT})

# payment_item on Clearance Charge Item / Task Finance Line → ApplicationFinanceProfile key
PAYMENT_KIND_TO_PROFILE_KEY = {
	"UCR": "UCR Application",
	"ENTRY_SLIP": "Entry Application",
	"Shipping Line": "Shipping Line Application",
	"KPA": "KPA Application",
}


@dataclass(frozen=True)
class TaskBehaviour:
	role: str
	payment_kind: str
	permit_stage: str
	requires_finance_action: bool
	requires_document_upload: bool
	requires_permit_action: bool
	requires_container_update: bool
	is_auto_completable: bool
	from_template: bool

	@property
	def is_application(self) -> bool:
		return self.role in APPLICATION_ROLES

	@property
	def is_finance_payment(self) -> bool:
		return self.role in FINANCE_ROLES

	@property
	def is_permit_application(self) -> bool:
		return self.role in PERMIT_APPLICATION_ROLES

	@property
	def is_permit_finance(self) -> bool:
		return self.role in PERMIT_FINANCE_ROLES

	@property
	def show_finance_lines(self) -> bool:
		return self.is_application or self.is_finance_payment or (
			self.requires_finance_action and self.payment_kind in PAYMENT_KIND_TO_PROFILE_KEY
		)

	@property
	def show_permits(self) -> bool:
		return (
			self.is_permit_application
			or self.is_permit_finance
			or self.requires_permit_action
		)

	@property
	def show_documents(self) -> bool:
		if self.role in (ROLE_APPLICATION,) and self.payment_kind == "Shipping Line":
			return False
		if self.is_permit_application or self.is_permit_finance:
			return True
		if self.role in DOCUMENT_ROLES or self.requires_document_upload:
			return True
		if self.is_application:
			return True
		return self.role in (ROLE_STANDARD, ROLE_AUTO_COMPLETE, "")


def task_has_behaviour_fields(task=None) -> bool:
	meta = frappe.get_meta("Task")
	return bool(meta.has_field("custom_task_role"))


def _task_role(task) -> str:
	return (task.get("custom_task_role") or "").strip()


def get_task_behaviour(task) -> TaskBehaviour:
	"""Resolve behaviour for a Task document or dict-like object."""
	if task is None:
		return TaskBehaviour(
			role=ROLE_STANDARD,
			payment_kind="",
			permit_stage="",
			requires_finance_action=False,
			requires_document_upload=True,
			requires_permit_action=False,
			requires_container_update=False,
			is_auto_completable=False,
			from_template=False,
		)

	role = _task_role(task)
	if role and task_has_behaviour_fields(task):
		return TaskBehaviour(
			role=role,
			payment_kind=(task.get("custom_payment_kind") or "").strip(),
			permit_stage=(task.get("custom_permit_stage") or "").strip(),
			requires_finance_action=bool(cint(task.get("custom_requires_finance_action"))),
			requires_document_upload=bool(cint(task.get("custom_requires_document_upload"))),
			requires_permit_action=bool(cint(task.get("custom_requires_permit_action"))),
			requires_container_update=bool(cint(task.get("custom_requires_container_update"))),
			is_auto_completable=role == ROLE_AUTO_COMPLETE
			or bool(cint(task.get("custom_is_auto_completable"))),
			from_template=True,
		)

	return _behaviour_from_sea_settings(task)


def _behaviour_from_sea_settings(task) -> TaskBehaviour:
	"""Legacy path: Sea Import Settings sequence → coarse behaviour."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		all_profiles,
		is_application_finance_task,
		is_application_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_auto_complete_task,
		is_document_checkpoint_task,
		is_permit_application_task,
		is_permit_finance_payment_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		is_sea_import_task,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	if not is_sea_import_task(task):
		return TaskBehaviour(
			role=ROLE_STANDARD,
			payment_kind="",
			permit_stage="",
			requires_finance_action=False,
			requires_document_upload=True,
			requires_permit_action=False,
			requires_container_update=False,
			is_auto_completable=False,
			from_template=False,
		)

	if is_auto_complete_task(seq):
		return TaskBehaviour(
			ROLE_AUTO_COMPLETE, "", "", False, True, False, False, True, False
		)
	if is_permit_application_task(seq):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			get_permit_stage_for_sequence,
		)

		return TaskBehaviour(
			ROLE_PERMIT_APPLICATION,
			"Permit",
			get_permit_stage_for_sequence(seq) or "",
			False,
			True,
			True,
			False,
			False,
			False,
		)
	if is_permit_finance_payment_task(seq):
		return TaskBehaviour(
			ROLE_PERMIT_FINANCE, "Permit", "", True, True, True, False, False, False
		)
	if is_document_checkpoint_task(seq):
		return TaskBehaviour(
			ROLE_DOCUMENT_CHECKPOINT, "", "", False, True, False, False, False, False
		)

	for profile in all_profiles():
		if is_application_task(seq, profile):
			return TaskBehaviour(
				ROLE_APPLICATION,
				profile.payment_item,
				"",
				False,
				True,
				False,
				False,
				False,
				False,
			)
		if is_application_finance_task(seq, profile):
			return TaskBehaviour(
				ROLE_FINANCE_PAYMENT,
				profile.payment_item,
				"",
				True,
				False,
				False,
				False,
				False,
				False,
			)

	return TaskBehaviour(
		ROLE_STANDARD, "", "", False, True, False, False, False, False
	)


def profile_for_payment_kind(payment_kind: str | None):
	"""Return ApplicationFinanceProfile for a payment kind / payment_item."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
	)

	key = PAYMENT_KIND_TO_PROFILE_KEY.get((payment_kind or "").strip())
	if not key:
		return None
	return APPLICATION_FINANCE_PROFILES.get(key)


def profile_for_behaviour_task(task):
	"""Profile from stamped payment kind, else legacy Settings seq mapping."""
	behaviour = get_task_behaviour(task)
	if behaviour.from_template and behaviour.payment_kind:
		profile = profile_for_payment_kind(behaviour.payment_kind)
		if profile and (
			behaviour.is_application
			or behaviour.is_finance_payment
			or behaviour.show_finance_lines
		):
			return profile

	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		all_profiles,
		is_application_workflow_task,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	for profile in all_profiles():
		if is_application_workflow_task(seq, profile):
			return profile
	return None


def uses_clearance_behaviour(task) -> bool:
	"""True when finance/permit application hooks should run for this task."""
	behaviour = get_task_behaviour(task)
	if behaviour.from_template:
		return (
			behaviour.is_application
			or behaviour.is_finance_payment
			or behaviour.is_permit_application
			or behaviour.is_permit_finance
			or behaviour.show_finance_lines
			or behaviour.show_permits
		)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		is_sea_import_task,
	)

	return is_sea_import_task(task)


def find_paired_task(
	task,
	*,
	want_role: str,
	payment_kind: str | None = None,
	permit_stage: str | None = None,
) -> str | None:
	"""Find sibling task in same project + flow_key with the given role/kind."""
	if not task or not task.get("project"):
		return None
	filters = {
		"project": task.project,
		"custom_task_flow_key": task.get("custom_task_flow_key") or ["!=", ""],
		"custom_task_role": want_role,
	}
	meta = frappe.get_meta("Task")
	if payment_kind and meta.has_field("custom_payment_kind"):
		filters["custom_payment_kind"] = payment_kind
	if permit_stage and meta.has_field("custom_permit_stage"):
		filters["custom_permit_stage"] = permit_stage

	candidates = frappe.get_all(
		"Task",
		filters=filters,
		fields=["name", "custom_sequence_no"],
		order_by="custom_sequence_no asc",
	)
	if not candidates:
		return None

	task_seq = int(task.get("custom_sequence_no") or 0)
	# Prefer finance task that depends on this application (or vice versa).
	for row in candidates:
		if row.name == task.name:
			continue
		if _tasks_are_paired(task.name, row.name, task_seq, int(row.custom_sequence_no or 0)):
			return row.name
	# Fallback: nearest sequence in the right direction.
	if want_role == ROLE_FINANCE_PAYMENT:
		after = [r for r in candidates if int(r.custom_sequence_no or 0) > task_seq]
		return after[0].name if after else candidates[0].name
	before = [r for r in candidates if int(r.custom_sequence_no or 0) < task_seq]
	return before[-1].name if before else candidates[0].name


def _tasks_are_paired(a_name: str, b_name: str, a_seq: int, b_seq: int) -> bool:
	"""True if one task depends_on the other (by name) or depends_on_sequences intent."""
	for parent, child in ((a_name, b_name), (b_name, a_name)):
		if frappe.db.exists("Task Depends On", {"parent": child, "task": parent}):
			return True
	# Adjacent sequences are a weak fallback when depends_on was not stamped.
	return abs(a_seq - b_seq) == 1


def get_application_task_for_behaviour(task, profile=None) -> str | None:
	behaviour = get_task_behaviour(task)
	kind = (profile.payment_item if profile else None) or behaviour.payment_kind
	if behaviour.is_finance_payment or behaviour.role == ROLE_FINANCE_PAYMENT:
		return find_paired_task(task, want_role=ROLE_APPLICATION, payment_kind=kind)
	if behaviour.is_application:
		return task.name
	return None


def get_finance_task_for_behaviour(task, profile=None) -> str | None:
	behaviour = get_task_behaviour(task)
	kind = (profile.payment_item if profile else None) or behaviour.payment_kind
	if behaviour.is_application:
		return find_paired_task(task, want_role=ROLE_FINANCE_PAYMENT, payment_kind=kind)
	if behaviour.is_finance_payment:
		return task.name
	return None


def get_permit_application_for_behaviour(task) -> str | None:
	behaviour = get_task_behaviour(task)
	if behaviour.is_permit_application:
		return task.name
	if behaviour.is_permit_finance:
		return find_paired_task(
			task,
			want_role=ROLE_PERMIT_APPLICATION,
			payment_kind=behaviour.payment_kind or "Permit",
			permit_stage=behaviour.permit_stage or None,
		)
	return None


def get_permit_finance_for_behaviour(task) -> str | None:
	behaviour = get_task_behaviour(task)
	if behaviour.is_permit_finance:
		return task.name
	if behaviour.is_permit_application:
		return find_paired_task(
			task,
			want_role=ROLE_PERMIT_FINANCE,
			payment_kind=behaviour.payment_kind or "Permit",
			permit_stage=behaviour.permit_stage or None,
		)
	return None


def task_is_ucr_application(task) -> bool:
	behaviour = get_task_behaviour(task)
	if behaviour.from_template:
		return behaviour.is_application and behaviour.payment_kind == "UCR"
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import is_ucr_application_task

	return is_ucr_application_task(int(task.get("custom_sequence_no") or 0))


def task_is_ucr_finance(task) -> bool:
	behaviour = get_task_behaviour(task)
	if behaviour.from_template:
		return behaviour.is_finance_payment and behaviour.payment_kind == "UCR"
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import is_ucr_finance_payment_task

	return is_ucr_finance_payment_task(int(task.get("custom_sequence_no") or 0))


def task_is_ucr_workflow(task) -> bool:
	return task_is_ucr_application(task) or task_is_ucr_finance(task)


def task_is_permit_application(task) -> bool:
	behaviour = get_task_behaviour(task)
	if behaviour.from_template:
		return behaviour.is_permit_application
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import is_permit_application_task

	return is_permit_application_task(int(task.get("custom_sequence_no") or 0))


def task_is_permit_finance(task) -> bool:
	behaviour = get_task_behaviour(task)
	if behaviour.from_template:
		return behaviour.is_permit_finance
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import is_permit_finance_payment_task

	return is_permit_finance_payment_task(int(task.get("custom_sequence_no") or 0))


def task_is_document_checkpoint(task) -> bool:
	behaviour = get_task_behaviour(task)
	if behaviour.from_template:
		return behaviour.role == ROLE_DOCUMENT_CHECKPOINT
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import is_document_checkpoint_task

	return is_document_checkpoint_task(int(task.get("custom_sequence_no") or 0))


def task_is_auto_complete(task) -> bool:
	behaviour = get_task_behaviour(task)
	if behaviour.from_template:
		return behaviour.is_auto_completable
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import is_auto_complete_task

	return is_auto_complete_task(int(task.get("custom_sequence_no") or 0))


def task_is_configured_application_workflow(task) -> bool:
	"""UCR / Entry / Shipping Line / KPA application or finance (not Permit)."""
	behaviour = get_task_behaviour(task)
	if behaviour.from_template:
		if behaviour.payment_kind == "Permit":
			return False
		return (behaviour.is_application or behaviour.is_finance_payment) and bool(
			profile_for_payment_kind(behaviour.payment_kind)
		)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_configured_application_workflow_task,
	)

	return is_configured_application_workflow_task(int(task.get("custom_sequence_no") or 0))


def task_is_application_for_profile(task, profile) -> bool:
	if not profile:
		return False
	behaviour = get_task_behaviour(task)
	if behaviour.from_template:
		return behaviour.is_application and behaviour.payment_kind == profile.payment_item
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		is_application_task,
	)

	return is_application_task(int(task.get("custom_sequence_no") or 0), profile)


def task_is_application_finance_for_profile(task, profile) -> bool:
	if not profile:
		return False
	behaviour = get_task_behaviour(task)
	if behaviour.from_template:
		return behaviour.is_finance_payment and behaviour.payment_kind == profile.payment_item
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		is_application_finance_task,
	)

	return is_application_finance_task(int(task.get("custom_sequence_no") or 0), profile)


def ui_payload_from_behaviour(behaviour: TaskBehaviour) -> dict:
	"""Shape consumed by task.js get_sea_task_ui-style consumers."""
	kind = behaviour.payment_kind or ""
	payload = {
		"is_sea_task": True,
		"from_template": behaviour.from_template,
		"task_role": behaviour.role,
		"payment_kind": kind,
		"permit_stage": behaviour.permit_stage,
		"show_finance_lines": behaviour.show_finance_lines,
		"show_documents": behaviour.show_documents,
		"documents_read_only": False,
		"show_permits": behaviour.show_permits,
		"show_payments": False,
		"show_external_ref": True,
		"show_description": True,
		"auto_intake_intro": False,
		"hide_mark_complete": behaviour.is_application
		or behaviour.is_finance_payment
		or behaviour.is_permit_application
		or behaviour.is_permit_finance,
		"is_ucr_application": behaviour.is_application and kind == "UCR",
		"is_ucr_finance": behaviour.is_finance_payment and kind == "UCR",
		"is_entry_application": behaviour.is_application and kind == "ENTRY_SLIP",
		"is_entry_finance": behaviour.is_finance_payment and kind == "ENTRY_SLIP",
		"is_shipping_line_application": behaviour.is_application and kind == "Shipping Line",
		"is_shipping_line_finance": behaviour.is_finance_payment and kind == "Shipping Line",
		"is_kpa_application": behaviour.is_application and kind == "KPA",
		"is_kpa_finance": behaviour.is_finance_payment and kind == "KPA",
		"is_permit_application": behaviour.is_permit_application,
		"is_permit_finance": behaviour.is_permit_finance,
		"is_pre_clearance_permit": behaviour.is_permit_application
		and behaviour.permit_stage == "Pre-clearance",
		"is_post_clearance_permit": behaviour.is_permit_application
		and behaviour.permit_stage == "Post-clearance",
		"is_document_checkpoint": behaviour.role == ROLE_DOCUMENT_CHECKPOINT,
		"is_auto_complete": behaviour.is_auto_completable,
	}
	if behaviour.is_auto_completable:
		payload["hide_mark_complete"] = True
		payload["auto_intake_intro"] = True
	return payload


@frappe.whitelist()
def get_task_behaviour_ui(task_name: str | None = None) -> dict:
	"""Desk API: UI flags for a Task (template-driven or Sea Settings fallback)."""
	if not task_name:
		return ui_payload_from_behaviour(get_task_behaviour(None))
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	return ui_payload_from_behaviour(get_task_behaviour(task))


def ensure_task_behaviour_fields() -> None:
	"""Create Task custom fields for template-stamped behaviour."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _ensure_cf

	_ensure_cf(
		"Task",
		{
			"fieldname": "custom_task_role",
			"label": "Task Role",
			"fieldtype": "Select",
			"options": "\n".join(
				[
					ROLE_STANDARD,
					ROLE_DOCUMENT,
					ROLE_DOCUMENT_CHECKPOINT,
					ROLE_APPLICATION,
					ROLE_FINANCE_PAYMENT,
					ROLE_PERMIT_APPLICATION,
					ROLE_PERMIT_FINANCE,
					ROLE_AUTO_COMPLETE,
				]
			),
			"insert_after": "custom_sequence_no",
			"read_only": 1,
			"allow_on_submit": 0,
			"description": "Stamped from CGM Task Template Item. Drives finance/permit/document UI.",
		},
	)
	_ensure_cf(
		"Task",
		{
			"fieldname": "custom_payment_kind",
			"label": "Payment Kind",
			"fieldtype": "Link",
			"options": "Payment Kind",
			"insert_after": "custom_task_role",
			"read_only": 1,
			"allow_on_submit": 0,
		},
	)
	_ensure_cf(
		"Task",
		{
			"fieldname": "custom_permit_stage",
			"label": "Permit Stage",
			"fieldtype": "Select",
			"options": "\nPre-clearance\nPost-clearance",
			"insert_after": "custom_payment_kind",
			"read_only": 1,
			"allow_on_submit": 0,
		},
	)
	for fieldname, label, insert_after in (
		("custom_requires_finance_action", "Requires Finance Action", "custom_permit_stage"),
		("custom_requires_document_upload", "Requires Document Upload", "custom_requires_finance_action"),
		("custom_requires_permit_action", "Requires Permit Action", "custom_requires_document_upload"),
		("custom_requires_container_update", "Requires Container Update", "custom_requires_permit_action"),
		("custom_is_auto_completable", "Is Auto Completable", "custom_requires_container_update"),
	):
		_ensure_cf(
			"Task",
			{
				"fieldname": fieldname,
				"label": label,
				"fieldtype": "Check",
				"insert_after": insert_after,
				"read_only": 1,
				"hidden": 1,
				"allow_on_submit": 0,
			},
		)
	_ensure_cf(
		"Task",
		{
			"fieldname": "custom_required_document_types",
			"label": "Required Document Types",
			"fieldtype": "Small Text",
			"insert_after": "custom_is_auto_completable",
			"read_only": 1,
			"allow_on_submit": 0,
			"description": "Stamped from CGM Task Template Item. Task cannot Complete until these Document Types are attached on Task Documents.",
		},
	)
	frappe.clear_cache(doctype="Task")
