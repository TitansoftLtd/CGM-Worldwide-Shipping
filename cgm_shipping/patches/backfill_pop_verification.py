"""Carry already-verified POPs onto their application tasks.

Why: only Shipping Line carries a POP row, and it had no mirror. The invoice row
had one and the receipt row had one, so a POP Finance verified on their task left
the declarant's copy reading "Pending Verification" for good. Measured on
production before this: 42 of 80 shipments disagreed with their finance twin.

The mirror is fixed going forward, but a POP verified before that fix stays stale,
because nothing re-runs on an untouched task.

What: walks the Shipping Line finance tasks that carry a verified POP and runs the
same mirror. It only ever sets verified = 1 where Finance already verified it, and
writes verified_by / verified_on from the finance row so the tick says who put it
there. A row already verified is left alone.

Idempotent: re-running corrects nothing further. One-time - retire per
docs/guides/patches.md once staging and production Patch Log show it.
"""

import frappe

PROFILE = "Shipping Line Application"


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
		sync_pop_verification_to_application_task,
	)

	profile = APPLICATION_FINANCE_PROFILES.get(PROFILE)
	if not profile or not profile.requires_pop:
		return

	task_names = frappe.db.sql(
		"""
		SELECT DISTINCT t.name
		FROM `tabTask Finance Line` l
		JOIN `tabTask` t ON l.parent = t.name
		WHERE l.parenttype = 'Task'
		  AND l.line_type = 'POP'
		  AND l.verified = 1
		  AND t.custom_task_role = 'Finance Payment'
		""",
		pluck=True,
	)

	corrected = 0
	for name in task_names:
		try:
			if sync_pop_verification_to_application_task(frappe.get_doc("Task", name), profile):
				corrected += 1
		except Exception:
			# One unusual shipment must not stop the rest; the mirror runs again on
			# the next save of that finance task.
			frappe.log_error(
				title="backfill_pop_verification", message=frappe.get_traceback()
			)

	if corrected:
		print(f"POP verification carried onto {corrected} application task(s)")
