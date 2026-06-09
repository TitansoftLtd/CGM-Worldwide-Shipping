"""Seed UCR Receipt row on Create UCR tasks; copy legacy finance-only receipts to declarant task."""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
	TASK_FINANCE_FIELD,
	LINE_RECEIPT,
	PAYMENT_UCR,
	UCR_RECEIPT_LABEL,
	seed_ucr_finance_lines,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
	get_ucr_application_task,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import SEA_TASK_FLOW_KEY


def execute():
	app_tasks = frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": 3,
		},
		pluck="name",
	)
	for name in app_tasks:
		task = frappe.get_doc("Task", name)
		seed_ucr_finance_lines(task)
		try:
			task.save(ignore_permissions=True)
		except Exception:
			pass

	finance_tasks = frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": 4,
		},
		pluck="name",
	)
	for name in finance_tasks:
		task = frappe.get_doc("Task", name)
		if not task.project:
			continue
		fin_rec = next(
			(
				r
				for r in task.get(TASK_FINANCE_FIELD) or []
				if r.line_type == LINE_RECEIPT and (r.payment_item or PAYMENT_UCR) == PAYMENT_UCR
			),
			None,
		)
		if not fin_rec or not fin_rec.attachment:
			continue
		app_name = get_ucr_application_task(task.project)
		if not app_name:
			continue
		app = frappe.get_doc("Task", app_name)
		seed_ucr_finance_lines(app)
		app_rec = next(
			(
				r
				for r in app.get(TASK_FINANCE_FIELD) or []
				if r.line_type == LINE_RECEIPT and (r.payment_item or PAYMENT_UCR) == PAYMENT_UCR
			),
			None,
		)
		if app_rec and not app_rec.attachment:
			app_rec.attachment = fin_rec.attachment
			if fin_rec.amount and not app_rec.amount:
				app_rec.amount = fin_rec.amount
			app.save(ignore_permissions=True)

	frappe.db.commit()
