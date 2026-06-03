"""Backfill UCR invoice verification from Finance pays UCR → Create UCR tasks."""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
	sync_ucr_verification_to_application_task,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import SEA_TASK_FLOW_KEY


def execute():
	finance_tasks = frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": 4,
		},
		pluck="name",
	)
	for name in finance_tasks:
		sync_ucr_verification_to_application_task(frappe.get_doc("Task", name))
	frappe.db.commit()
