"""Backfill existing Journal Entries onto Task Finance Line invoice rows.

Before per-line JE columns, payments lived on Task.custom_journal_entry (and on
Journal Entry.custom_cgm_source_task). Amendment payments often overwrote the
task-level link, leaving the primary Invoice row looking unpaid.

This patch only writes empty ``journal_entry`` / ``client_paid_directly`` on
Task Finance Line. It never creates, cancels, or edits Journal Entry docs.
"""

from __future__ import annotations

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		all_profiles,
		backfill_legacy_payment_onto_invoice_lines,
		is_application_finance_task,
		sync_finance_line_payments_to_application_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		finance_payment_sequences,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		task_flow_key_in_filter,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
		try_auto_complete_application_finance_task,
	)

	if not frappe.db.exists("DocType", "Task Finance Line"):
		return
	if not frappe.get_meta("Task Finance Line").has_field("journal_entry"):
		return

	payment_seqs = list(finance_payment_sequences())
	if not payment_seqs:
		return

	names = frappe.get_all(
		"Task",
		filters={
			"custom_sequence_no": ("in", payment_seqs),
			"custom_task_flow_key": task_flow_key_in_filter(),
			"status": ("!=", "Cancelled"),
		},
		pluck="name",
		limit=2000,
	)
	if not names:
		return

	profiles = list(all_profiles())
	updated = 0
	for name in names:
		try:
			task = frappe.get_doc("Task", name)
			seq = int(task.get("custom_sequence_no") or 0)
			profile = None
			for candidate in profiles:
				if is_application_finance_task(seq, candidate):
					profile = candidate
					break
			if not profile:
				continue

			changed = backfill_legacy_payment_onto_invoice_lines(task, profile)
			task.reload()
			changed = (
				sync_finance_line_payments_to_application_task(task, profile) or changed
			)
			if changed:
				updated += 1
				# Re-complete when every invoice line is now settled + receipt ok.
				if task.status not in ("Completed", "Cancelled"):
					try_auto_complete_application_finance_task(task, profile)
		except Exception:
			frappe.log_error(
				title=f"CGM: failed to backfill finance-line JE for {name}"
			)

	if updated:
		frappe.db.commit()
