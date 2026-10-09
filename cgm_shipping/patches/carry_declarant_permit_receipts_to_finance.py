"""Copy permit receipts the declarant attached onto the paired Finance task.

Why: the declarant's completion gate reads receipts off the Finance task's permit
rows, but a receipt only travelled there when the declarant's rows changed on a
save or Finance opened its form. Pairs nobody touched after the receipt went on
never synced, so the declarant was told "Receipt not attached" with the receipt
attached in front of them. TASK-2026-01055 had three receipts on since 31 Aug and
none on TASK-2026-01056; a copy of production from 3 Oct showed the same gap on
21 pairs.

What: for every permit application task with a receipt, fills the *empty*
receipt on the Finance row with the same permit, amendment flag and invoice.

This copies a file link and nothing else. No task is completed or reopened, no
tick or row status is changed, and no task's modified timestamp moves. A Finance
row that already has a receipt, or whose invoice differs from the declarant's, is
left alone.

The cause is fixed in `permit_rows_pending_verification`, which now carries the
receipt itself, so this is a one-off cleanup that makes the Finance rows right
before anyone presses Complete.

Idempotent. Retire per docs/guides/patches.md once staging and production Patch
Log show it.
"""

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		carry_application_receipts_to_finance,
		finance_permit_task_for_application,
		is_permit_application_task_doc,
	)

	candidates = frappe.db.sql_list(
		"""
		select distinct parent
		from `tabPermit Register`
		where parenttype = 'Task' and ifnull(payment_receipt, '') != ''
		order by parent
		"""
	)

	filled, failed = [], 0
	for name in candidates:
		try:
			app = frappe.get_doc("Task", name)
			if not is_permit_application_task_doc(app) or not app.project:
				continue
			fin_name = finance_permit_task_for_application(app)
			if not fin_name:
				continue
			carried = carry_application_receipts_to_finance(app, frappe.get_doc("Task", fin_name))
		except Exception:
			frappe.log_error(
				title="carry_declarant_permit_receipts_to_finance",
				message=f"{name}: {frappe.get_traceback()}",
			)
			failed += 1
			continue
		if carried:
			filled.append((name, fin_name, carried))

	frappe.db.commit()

	print(
		f"Tasks with permit receipts: {len(candidates)}; pairs filled: {len(filled)}; "
		f"could not check: {failed}"
	)
	for app_name, fin_name, carried in filled:
		print(f"  {app_name} -> {fin_name}: {carried} receipt(s)")
