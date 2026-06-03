"""Fix Finance pays UCR tasks stuck Open while verification is complete."""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
	try_auto_complete_ucr_finance_task,
	ucr_finance_ready_to_complete,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import SEA_TASK_FLOW_KEY


def execute():
	names = frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": 4,
			"status": ("not in", ("Completed", "Cancelled")),
		},
		pluck="name",
	)
	for name in names:
		task = frappe.get_doc("Task", name)
		if ucr_finance_ready_to_complete(task):
			try_auto_complete_ucr_finance_task(task)
	frappe.db.commit()
