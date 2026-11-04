"""Take permits the declarant marked Foreign off their Finance task.

Why: origin was not part of the permit fingerprint, so flipping a permit to
Foreign saved silently and never reached the paired Finance task. The stale Local
copy stayed in Finance's payable set owing a receipt nobody would ever attach,
and the declarant's task could not close. TASK-2026-00889 is one: KEBS reads
Foreign on the declarant's task and Local on TASK-2026-00890.

What: for each permit application carrying a Foreign row, re-runs the normal
application-to-finance sync, which now drops a row the declarant has marked
Foreign rather than trusting the finance copy's own origin. Then asks whether the
application may close, using its own completion gate - so a Local row still needs
its invoice, receipt and certificate, and an unverified one still holds it open.

Nothing about permits is decided here. The sync and the gate are the same ones the
form uses.

Idempotent: a finance task with no stale rows is left alone. One-time - retire per
docs/guides/patches.md once staging and production Patch Log show it.
"""

import frappe

APPLICATION_ROLE = "Permit Application"


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		TASK_PERMITS_FIELD,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		close_permit_application_if_finance_already_done,
		finance_permit_task_for_application,
		sync_permit_invoices_to_finance_task,
	)

	app_names = frappe.get_all(
		"Task", filters={"custom_task_role": APPLICATION_ROLE}, pluck="name"
	)

	resynced, closed = [], []
	for name in app_names:
		try:
			app = frappe.get_doc("Task", name)
			foreign = {
				(r.get("permit_type") or "").strip()
				for r in (app.get(TASK_PERMITS_FIELD) or [])
				if r.get("permit_type") and (r.get("origin") or "Local").strip() == "Foreign"
			}
			if not foreign:
				continue

			fin_name = finance_permit_task_for_application(app)
			if not fin_name:
				continue
			fin = frappe.get_doc("Task", fin_name)
			stale = [
				r
				for r in (fin.get(TASK_PERMITS_FIELD) or [])
				if (r.get("permit_type") or "").strip() in foreign
			]
			if not stale:
				continue

			sync_permit_invoices_to_finance_task(fin, save=True)
			resynced.append(f"{fin_name} ({', '.join(r.permit_type for r in stale)})")

			# It may now be ready; its own gate decides, not this patch.
			if close_permit_application_if_finance_already_done(frappe.get_doc("Task", name)):
				closed.append(name)
		except Exception:
			# One odd shipment must not stop the rest; it keeps today's behaviour.
			frappe.log_error(
				title="drop_stale_foreign_permit_rows", message=frappe.get_traceback()
			)

	print(f"Finance tasks resynced: {len(resynced)}; applications closed: {len(closed)}")
	for line in resynced:
		print(f"   resynced {line}")
	for name in closed:
		print(f"   closed   {name}")
