"""Backfill permit invoice rows on Finance pays Pre-Clearance Permits tasks."""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
	ensure_finance_permit_rows_saved,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import SEA_TASK_FLOW_KEY


def execute():
	names = frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": 6,
		},
		pluck="name",
	)
	for name in names:
		task = frappe.get_doc("Task", name)
		ensure_finance_permit_rows_saved(task)
	frappe.db.commit()
