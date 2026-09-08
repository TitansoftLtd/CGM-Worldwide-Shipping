# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
	APPLICATION_FINANCE_PROFILES,
	can_complete_application_task,
	task_matches_application,
)


def execute() -> None:
	"""Reopen Entry application tasks that were Completed before Finance paid."""
	profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
	if not frappe.get_meta("Task").has_field("custom_payment_kind"):
		return

	tasks = frappe.get_all(
		"Task",
		filters={
			"status": "Completed",
			"custom_task_role": "Application",
			"custom_payment_kind": "ENTRY_SLIP",
		},
		fields=["name"],
	)
	if not tasks:
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import _reopen_sea_task

	frappe.flags.cgm_reopening_task = True
	try:
		for row in tasks:
			task = frappe.get_doc("Task", row.name)
			if not task_matches_application(task, profile):
				continue
			if can_complete_application_task(task, profile):
				continue
			if not _reopen_sea_task(
				task,
				reason="Finance payment not yet settled for Entry Slip invoice",
			):
				continue
			frappe.db.set_value(
				"Task",
				task.name,
				{
					"status": "Open",
					"progress": 0,
					"completed_by": None,
					"completed_on": None,
				},
				update_modified=True,
			)
	finally:
		frappe.flags.cgm_reopening_task = False

	frappe.clear_cache(doctype="Task")
