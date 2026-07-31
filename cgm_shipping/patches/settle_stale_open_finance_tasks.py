"""Settle sea finance payment tasks stuck Open after payment was already done.

Form vs List mismatch: auto-complete wrote Completed via set_value, then a later
stale save wrote Open back. Re-run completion for tasks that are clearly ready.
"""

from __future__ import annotations

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CLIENT_PAID_FIELD,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		finance_payment_sequences,
		is_permit_finance_payment_task,
		is_ucr_finance_payment_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		try_auto_complete_permit_finance_task,
		try_auto_complete_ucr_finance_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		can_complete_application_finance_task,
		is_application_finance_task,
		profile_for_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
		try_auto_complete_application_finance_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		task_flow_key_in_filter,
	)

	payment_seqs = list(finance_payment_sequences())
	if not payment_seqs:
		return

	# Narrow SQL first — avoid loading every Task on the site.
	filters = {
		"status": "Open",
		"custom_sequence_no": ("in", payment_seqs),
		"custom_task_flow_key": task_flow_key_in_filter(),
	}
	names = frappe.get_all("Task", filters=filters, pluck="name", limit=500)
	if not names:
		return

	for name in names:
		try:
			task = frappe.get_doc("Task", name)
			seq = int(task.get("custom_sequence_no") or 0)
			if is_ucr_finance_payment_task(seq):
				try_auto_complete_ucr_finance_task(task)
			elif is_permit_finance_payment_task(seq):
				try_auto_complete_permit_finance_task(task)
			else:
				profile = profile_for_task(task)
				if profile and is_application_finance_task(seq, profile):
					if can_complete_application_finance_task(task, profile):
						try_auto_complete_application_finance_task(task, profile)
		except Exception:
			frappe.log_error(title=f"CGM: failed to settle finance task status for {name}")
