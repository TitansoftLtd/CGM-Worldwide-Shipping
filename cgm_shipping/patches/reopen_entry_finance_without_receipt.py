"""Reopen Entry Slip finance tasks completed before receipt verification was required."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
	APPLICATION_FINANCE_PROFILES,
	can_complete_application_finance_task,
)


def execute():
	profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
	names = frappe.get_all(
		"Task",
		filters={
			"status": "Completed",
			"custom_task_role": "Finance Payment",
			"custom_payment_kind": "ENTRY_SLIP",
		},
		pluck="name",
	)
	for name in names:
		task = frappe.get_doc("Task", name)
		if can_complete_application_finance_task(task, profile):
			continue
		frappe.db.set_value(
			"Task",
			name,
			{
				"status": "Open",
				"progress": 0,
				"completed_by": None,
				"completed_on": None,
			},
			update_modified=True,
		)
