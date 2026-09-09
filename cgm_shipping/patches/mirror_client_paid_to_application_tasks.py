"""Settle Finance client-paid confirmations made before the shortcut existed.

Those tasks left the paired declarant task showing an empty "Paid directly by
client" box, and the payment step itself stayed Open because completion only
runs on save.
"""

from __future__ import annotations

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CLIENT_PAID_FIELD,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		on_task_update,
		sync_client_paid_to_application_task,
	)

	if not frappe.get_meta("Task").has_field(CLIENT_PAID_FIELD):
		return

	names = frappe.get_all(
		"Task",
		filters={CLIENT_PAID_FIELD: 1},
		pluck="name",
	)
	for name in names:
		try:
			task = frappe.get_doc("Task", name)
			sync_client_paid_to_application_task(task)
			if task.status not in ("Completed", "Cancelled"):
				on_task_update(task)
		except Exception:
			frappe.log_error(title=f"CGM: failed to settle client-paid task {name}")
