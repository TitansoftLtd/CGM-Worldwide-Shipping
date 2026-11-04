"""Close permit applications whose Finance task finished before they were ready.

Why: the application is closed by `close_permit_application_when_finance_done`,
which fires on the Finance task's save and nothing else. An application that was
not ready at that instant - a certificate still to come, or a row not yet marked
Foreign - was never looked at again, and sat Open with Finance long since closed.
TASK-2026-00889 is one: its partner TASK-2026-00890 has been Completed for weeks.

What: for each Open permit application whose Finance task is already Completed,
asks the task's own completion gate whether it may close, and closes it if so.

It decides nothing about permits itself. The gate is
`validate_permit_application_can_complete`, the same one the Complete button uses,
so a Local row still needs its invoice, receipt and certificate, and a Foreign row
still needs its certificate and is never asked for a payment it never makes. An
unverified invoice or receipt also still holds it open.

Skips the client-pays path: the declarant closes those themselves, as before.

Idempotent: a closed task is skipped. One-time - retire per docs/guides/patches.md
once staging and production Patch Log show it.
"""

import frappe

OPEN_STATES = ("Open", "Working", "Pending Review", "Overdue")


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		close_permit_application_if_finance_already_done,
	)

	names = frappe.get_all(
		"Task",
		filters={"custom_task_role": "Permit Application", "status": ["in", OPEN_STATES]},
		pluck="name",
	)

	closed = []
	for name in names:
		try:
			if close_permit_application_if_finance_already_done(frappe.get_doc("Task", name)):
				closed.append(name)
		except Exception:
			# One odd shipment must not stop the rest. It stays Open and can be
			# completed by hand, which is the behaviour it had before this patch.
			frappe.log_error(
				title="close_permit_applications_finance_finished",
				message=frappe.get_traceback(),
			)

	print(
		f"Permit applications checked: {len(names)}; closed as Finance had finished: {len(closed)}"
	)
	for name in closed:
		print(f"   closed {name}")
