"""Complete open UCR tasks that already satisfy the new auto-complete rules."""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
	auto_complete_ucr_application_for_project,
	try_auto_complete_ucr_finance_task,
	ucr_finance_ready_to_complete,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import SEA_TASK_FLOW_KEY


def execute():
	projects = frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": 3,
			"status": ("not in", ("Completed", "Cancelled")),
		},
		pluck="project",
		distinct=True,
	)
	for project in projects:
		if project:
			auto_complete_ucr_application_for_project(project)

	finance_tasks = frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": 4,
			"status": ("not in", ("Completed", "Cancelled")),
		},
		pluck="name",
	)
	for name in finance_tasks:
		task = frappe.get_doc("Task", name)
		if ucr_finance_ready_to_complete(task):
			try_auto_complete_ucr_finance_task(task)

	frappe.db.commit()
