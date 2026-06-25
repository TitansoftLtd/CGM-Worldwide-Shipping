"""Project billed total — auto-sync from Journal Entries linked to a shipment."""
from __future__ import annotations

import frappe
from frappe.utils import flt

TOTAL_FIELD = "custom_finance_cost_total"


def _task_for_journal_entry(je) -> frappe.model.document.Document | None:
	task_name = je.get("custom_cgm_source_task")
	if not task_name:
		task_name = frappe.db.get_value(
			"Task", {"custom_journal_entry": je.name}, "name"
		)
	if not task_name:
		task_name = frappe.db.get_value(
			"Permit Register",
			{"journal_entry": je.name, "parenttype": "Task"},
			"parent",
		)
	if not task_name or not frappe.db.exists("Task", task_name):
		return None
	return frappe.get_doc("Task", task_name)


def _project_for_journal_entry(je, task=None) -> str | None:
	if task and task.get("project"):
		return task.project
	rows = frappe.get_all(
		"Journal Entry Account",
		filters={"parent": je.name, "project": ["is", "set"]},
		pluck="project",
		limit=1,
	)
	return rows[0] if rows else None


def _expense_lines_for_project(je, project: str) -> list[dict]:
	lines = []
	for row in je.get("accounts") or []:
		if row.project and row.project != project:
			continue
		debit = flt(row.debit_in_account_currency or row.debit)
		if debit <= 0:
			continue
		account_type = frappe.db.get_value("Account", row.account, "account_type")
		if account_type in ("Bank", "Cash"):
			continue
		lines.append({"account": row.account, "amount": debit})
	return lines


def _journal_entry_names_for_project(project: str) -> set[str]:
	names: set[str] = set()
	for row in frappe.db.sql(
		"""
		SELECT DISTINCT je.name
		FROM `tabJournal Entry` je
		INNER JOIN `tabTask` t ON t.name = je.custom_cgm_source_task
		WHERE t.project = %s
		""",
		project,
		as_dict=True,
	):
		names.add(row.name)

	for row in frappe.db.sql(
		"""
		SELECT DISTINCT t.custom_journal_entry AS name
		FROM `tabTask` t
		WHERE t.project = %s
		  AND IFNULL(t.custom_journal_entry, '') != ''
		""",
		project,
		as_dict=True,
	):
		if row.name:
			names.add(row.name)

	for row in frappe.db.sql(
		"""
		SELECT DISTINCT pr.journal_entry AS name
		FROM `tabPermit Register` pr
		INNER JOIN `tabTask` t ON t.name = pr.parent AND pr.parenttype = 'Task'
		WHERE t.project = %s
		  AND IFNULL(pr.journal_entry, '') != ''
		""",
		project,
		as_dict=True,
	):
		if row.name:
			names.add(row.name)

	for row in frappe.db.sql(
		"""
		SELECT DISTINCT pr.journal_entry AS name
		FROM `tabPermit Register` pr
		INNER JOIN `tabProject` p ON p.name = pr.parent AND pr.parenttype = 'Project'
		WHERE p.name = %s
		  AND IFNULL(pr.journal_entry, '') != ''
		""",
		project,
		as_dict=True,
	):
		if row.name:
			names.add(row.name)

	for row in frappe.db.sql(
		"""
		SELECT DISTINCT jea.parent AS name
		FROM `tabJournal Entry Account` jea
		INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
		WHERE jea.project = %s
		""",
		project,
		as_dict=True,
	):
		names.add(row.name)

	return names


def _amount_for_journal_entry(je, project: str) -> float:
	if int(je.docstatus or 0) == 2:
		return 0.0
	lines = _expense_lines_for_project(je, project)
	return sum(flt(line["amount"]) for line in lines)


def rebuild_project_finance_billed_total(project: str) -> None:
	"""Recompute Total Billed Amount (via Journal Entry) on Project."""
	if not project or not frappe.db.exists("Project", project):
		return
	if not frappe.get_meta("Project").has_field(TOTAL_FIELD):
		return

	total = 0.0
	for je_name in _journal_entry_names_for_project(project):
		if not frappe.db.exists("Journal Entry", je_name):
			continue
		je = frappe.get_doc("Journal Entry", je_name)
		if int(je.docstatus or 0) not in (0, 1, 2):
			continue
		total += _amount_for_journal_entry(je, project)

	frappe.flags.cgm_syncing_finance_cost_ledger = True
	try:
		frappe.db.set_value(
			"Project", project, TOTAL_FIELD, total, update_modified=False
		)
	finally:
		frappe.flags.cgm_syncing_finance_cost_ledger = False


def sync_journal_entry_finance_cost(je, method=None) -> None:
	"""Hook: refresh Project total when a Journal Entry changes."""
	if frappe.flags.get("cgm_syncing_finance_cost_ledger"):
		return
	if not je.get("custom_cgm_source_task") and not any(
		(row.project or "") for row in (je.get("accounts") or [])
	):
		return
	task = _task_for_journal_entry(je)
	project = _project_for_journal_entry(je, task)
	if not project:
		return
	rebuild_project_finance_billed_total(project)


@frappe.whitelist()
def refresh_finance_cost_for_project(project: str) -> dict:
	"""Recompute billed total for a Project (desk refresh)."""
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	rebuild_project_finance_billed_total(project)
	return {"project": project, "refreshed": True}


@frappe.whitelist()
def get_project_finance_journal_entry_names(project: str) -> list[str]:
	"""Submitted Journal Entries linked to a Project (for list drill-down)."""
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	names: list[str] = []
	for je_name in sorted(_journal_entry_names_for_project(project)):
		if frappe.db.get_value("Journal Entry", je_name, "docstatus") == 1:
			names.append(je_name)
	return names
