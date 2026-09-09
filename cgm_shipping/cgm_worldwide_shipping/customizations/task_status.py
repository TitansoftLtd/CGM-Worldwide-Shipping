# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

"""Authoritative Task.status persistence and form/list alignment.

Task.status in tabTask is the single source of truth. Form and List View must
never show a different value unless a save is in flight. The recurring
form=Completed / list=Open bug came from:

1. mark_task_completed wrote Completed via db.set_value while another request
   still held status=Open in memory and later saved over the DB row.
2. getdoc/onload returned an in-memory status=Completed that was never persisted.
3. List View did not react to cgm_task_status_changed realtime events.

before_save guards (preserve_completed_status_against_stale_save,
promote_ready_finance_task_before_save) address (1). This module addresses (2)
and supports reconciliation for existing rows.
"""

from __future__ import annotations

import frappe


def get_persisted_task_status(task_name: str) -> str | None:
	if not task_name:
		return None
	return frappe.db.get_value("Task", task_name, "status")


def get_persisted_task_completion_fields(task_name: str) -> dict:
	if not task_name:
		return {}
	row = frappe.db.get_value(
		"Task",
		task_name,
		["status", "progress", "completed_by", "completed_on"],
		as_dict=True,
	)
	return row or {}


def apply_persisted_status_to_doc(doc) -> bool:
	"""Copy status + completion metadata from DB onto doc. Returns True if doc changed."""
	if doc.is_new() or not doc.name:
		return False
	persisted = get_persisted_task_completion_fields(doc.name)
	if not persisted:
		return False
	changed = False
	for field in ("status", "progress", "completed_by", "completed_on"):
		value = persisted.get(field)
		if doc.get(field) != value:
			doc.set(field, value)
			changed = True
	return changed


def try_persist_sea_task_completion_if_ready(doc) -> bool:
	"""Persist Completed when business gates are met but DB still shows Open."""
	if doc.is_new() or doc.status in ("Completed", "Cancelled"):
		return False
	if frappe.flags.get("cgm_reopening_task") or frappe.flags.get("cgm_healing_finance_status"):
		return False

	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		_is_sea_task,
		heal_ready_finance_task_status,
	)

	if not _is_sea_task(doc):
		return False

	if heal_ready_finance_task_status(doc):
		doc.reload()
		return True

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_configured_application_workflow,
		task_is_permit_finance,
		task_is_ucr_application,
		task_is_ucr_finance,
	)

	if task_is_ucr_application(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			try_auto_complete_ucr_create_task,
		)

		if try_auto_complete_ucr_create_task(doc):
			doc.reload()
			return True

	if task_is_ucr_finance(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			try_auto_complete_ucr_finance_task,
		)

		if try_auto_complete_ucr_finance_task(doc):
			doc.reload()
			return True

	if task_is_permit_finance(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			auto_complete_finance_permit_task,
			can_complete_finance_permit_task,
		)

		if can_complete_finance_permit_task(doc) and auto_complete_finance_permit_task(doc):
			doc.reload()
			return True

	if task_is_configured_application_workflow(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			profile_for_task,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
			try_auto_complete_application_finance_task,
			try_auto_complete_application_task,
		)

		profile = profile_for_task(doc)
		if not profile:
			return False
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			task_matches_application,
			task_matches_application_finance,
		)

		if task_matches_application(doc, profile) and try_auto_complete_application_task(
			doc, profile
		):
			doc.reload()
			return True
		if task_matches_application_finance(doc, profile) and try_auto_complete_application_finance_task(
			doc, profile
		):
			doc.reload()
			return True

	return False


def finalize_task_status_for_form(doc) -> None:
	"""Ensure getdoc never returns status that disagrees with tabTask.

	- DB Open + phantom in-memory Completed → revert to DB or persist if ready.
	- DB Open + ready to complete → persist Completed before rendering the form.
	- DB Completed + in-memory Open → align memory to DB (stale client doc).
	"""
	if doc.is_new() or not doc.name:
		return
	if frappe.flags.get("cgm_finalizing_task_status"):
		return

	frappe.flags.cgm_finalizing_task_status = True
	try:
		db_status = get_persisted_task_status(doc.name)
		if not db_status:
			return

		if doc.status == "Completed" and db_status == "Open":
			if not try_persist_sea_task_completion_if_ready(doc):
				apply_persisted_status_to_doc(doc)
			return

		if doc.status == "Open" and db_status == "Completed":
			apply_persisted_status_to_doc(doc)
			return

		if db_status == "Open" and doc.status == "Open":
			try_persist_sea_task_completion_if_ready(doc)
	finally:
		frappe.flags.cgm_finalizing_task_status = False


def prepare_task_doc_before_programmatic_save(doc) -> None:
	"""Call before any workflow sync that saves a Task outside the user's form save."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		preserve_completed_status_against_stale_save,
	)

	preserve_completed_status_against_stale_save(doc)


def find_tasks_with_status_mismatch(limit: int = 500) -> list[dict]:
	"""Find sea clearance tasks stuck Open while completion gates are satisfied."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		finance_payment_task_ready_to_complete,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		task_flow_key_in_filter,
	)

	names = frappe.get_all(
		"Task",
		filters={
			"status": "Open",
			"custom_task_flow_key": task_flow_key_in_filter(),
		},
		pluck="name",
		limit=limit,
	)
	out: list[dict] = []
	for name in names:
		try:
			doc = frappe.get_doc("Task", name)
			if finance_payment_task_ready_to_complete(doc):
				out.append({"name": name, "reason": "finance_payment_ready"})
		except Exception:
			frappe.log_error(title=f"CGM task status mismatch scan failed for {name}")
	return out


def reconcile_open_tasks_ready_to_complete(*, dry_run: bool = False) -> dict:
	"""Persist Completed for tasks that meet gates but remain Open in tabTask."""
	from cgm_shipping.patches.settle_stale_open_finance_tasks import execute as settle_finance

	if dry_run:
		return {"would_reconcile": find_tasks_with_status_mismatch()}

	settle_finance()
	remaining = find_tasks_with_status_mismatch()
	reconciled = 0
	for row in remaining:
		try:
			doc = frappe.get_doc("Task", row["name"])
			if try_persist_sea_task_completion_if_ready(doc):
				reconciled += 1
		except Exception:
			frappe.log_error(title=f"CGM task status reconcile failed for {row['name']}")
	return {
		"reconciled": reconciled,
		"remaining_mismatch": len(find_tasks_with_status_mismatch()),
	}
