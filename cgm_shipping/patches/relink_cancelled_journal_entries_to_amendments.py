"""Move permit rows and finance lines off cancelled Journal Entries onto their amendments.

Why: Cancel + Amend leaves a new Journal Entry, and nothing moved the row that
pointed at the cancelled one. The payment then read as unpaid while the row
offered no way forward, so the finance task stayed Open with the amendment
posted and unlinked (TASK-2026-00441, DVS; TASK-2026-00354 and PROJ-0015,
Porthealth).

What: for every row linking a cancelled entry, repoints it at the newest
submitted amendment of that entry, then lets the permit finance task complete if
that was the last payment outstanding. Rows whose entry has no amendment are left
alone - Make Payment is offered again for those.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it. New cancellations are handled by
task.relink_amended_journal_entry on the amendment's submit.
"""

import frappe


def _newest_submitted_amendment(journal_entry: str) -> str | None:
	"""Follow the amend chain: an amendment can itself be cancelled and amended again."""
	seen: set[str] = set()
	current = journal_entry
	while current and current not in seen:
		seen.add(current)
		nxt = frappe.get_all(
			"Journal Entry",
			filters={"amended_from": current},
			fields=["name", "docstatus"],
			order_by="creation desc",
			limit=1,
		)
		if not nxt:
			return None
		current = nxt[0].name
		if nxt[0].docstatus == 1:
			return current
	return None


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		PERMIT_JOURNAL_ENTRY_FIELD,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_permit_finance,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		auto_complete_finance_permit_task,
	)

	tasks: set[str] = set()
	moved = 0
	for doctype in ("Permit Register", "Task Finance Line"):
		if not frappe.db.has_column(doctype, PERMIT_JOURNAL_ENTRY_FIELD):
			continue
		rows = frappe.db.sql(
			f"""
			SELECT row.name, row.parent, row.parenttype, row.{PERMIT_JOURNAL_ENTRY_FIELD} AS journal_entry
			FROM `tab{doctype}` row
			JOIN `tabJournal Entry` je ON je.name = row.{PERMIT_JOURNAL_ENTRY_FIELD}
			WHERE je.docstatus = 2
			""",
			as_dict=True,
		)
		for row in rows:
			amendment = _newest_submitted_amendment(row.journal_entry)
			if not amendment:
				continue
			frappe.db.set_value(
				doctype, row.name, PERMIT_JOURNAL_ENTRY_FIELD, amendment, update_modified=False
			)
			frappe.clear_document_cache(row.parenttype, row.parent)
			moved += 1
			if row.parenttype == "Task":
				tasks.add(row.parent)

	for task_name, journal_entry in frappe.db.sql(
		"""
		SELECT t.name, t.custom_journal_entry
		FROM tabTask t JOIN `tabJournal Entry` je ON je.name = t.custom_journal_entry
		WHERE je.docstatus = 2
		"""
	):
		amendment = _newest_submitted_amendment(journal_entry)
		if not amendment:
			continue
		frappe.db.set_value("Task", task_name, "custom_journal_entry", amendment, update_modified=False)
		frappe.clear_document_cache("Task", task_name)
		moved += 1
		tasks.add(task_name)

	for task_name in tasks:
		task = frappe.get_doc("Task", task_name)
		if task_is_permit_finance(task):
			auto_complete_finance_permit_task(task)

	if moved:
		print(f"Relinked {moved} row(s) from cancelled Journal Entries to their amendments")
