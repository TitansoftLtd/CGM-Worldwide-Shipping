"""Close permit Finance tasks whose application the declarant already completed.

complete_permit_finance_when_application_done now closes Finance as the
declarant completes a pre- or post-clearance permit application. It fires on
that transition only, so pairs already sitting in this state - application
Completed, Finance still Open - are closed here. Finance stays open wherever a
payable row is still unpaid; verification is not re-checked once the declarant
has completed.

Idempotent: acts only on Completed applications whose Finance is still Open,
so re-running is a no-op. One-time repair - retire once staging and
production Patch Log both show it (docs/guides/patches.md).
"""

from __future__ import annotations

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		complete_permit_finance_when_application_done,
	)

	if not frappe.db.has_column("Task", "custom_task_role"):
		return

	closed = skipped = 0
	for name in frappe.get_all(
		"Task",
		filters={"custom_task_role": "Permit Application", "status": "Completed"},
		pluck="name",
	):
		# One bad record must not abort the migrate or undo pairs already closed.
		frappe.db.savepoint("cgm_close_permit_finance")
		try:
			finance = complete_permit_finance_when_application_done(frappe.get_doc("Task", name))
		except Exception as exc:
			frappe.db.rollback(save_point="cgm_close_permit_finance")
			skipped += 1
			print(f"  {name}: skipped ({type(exc).__name__}: {exc})")
			continue
		if finance:
			closed += 1
			print(f"  {name}: closed Finance {finance}")

	frappe.db.commit()
	print(f"Permit Finance closed for completed applications: {closed} closed, {skipped} skipped")
