"""
Per-task form visibility for sea clearance tasks (SEA_IMPORT_E2E).

Client task.js loads sequence lists from get_sea_task_ui_sequences (Settings-driven).
"""
from __future__ import annotations

from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements.service import (
	finance_payment_with_supplier_invoice_sequences,
	is_auto_complete_task,
	is_finance_payment_task,
	is_light_proof_task,
	is_permit_application_task,
	is_permit_finance_payment_task,
	is_ucr_application_task,
	is_ucr_finance_payment_task,
)


def get_sea_task_form_ui(sequence_no: int) -> dict:
	"""Return UI flags for Task form (documents, payments, fields to hide)."""
	seq = int(sequence_no or 0)
	if is_auto_complete_task(seq):
		return {
			"is_sea_task": True,
			"show_documents": True,
			"documents_read_only": True,
			"show_payments": False,
			"show_external_ref": False,
			"show_description": True,
			"auto_intake_intro": True,
			"hide_mark_complete": True,
		}
	if is_ucr_application_task(seq):
		return {
			"is_sea_task": True,
			"is_ucr_application": True,
			"show_finance_lines": True,
			"show_documents": True,
			"documents_read_only": False,
			"show_permits": False,
			"show_payments": False,
			"show_external_ref": True,
			"show_description": True,
			"auto_intake_intro": False,
			"hide_mark_complete": True,
		}
	if is_permit_application_task(seq):
		return {
			"is_sea_task": True,
			"show_documents": False,
			"documents_read_only": False,
			"show_permits": True,
			"show_payments": False,
			"show_external_ref": True,
			"show_description": True,
			"auto_intake_intro": False,
			"hide_mark_complete": True,
		}
	if is_finance_payment_task(seq):
		ucr_finance = is_ucr_finance_payment_task(seq)
		return {
			"is_sea_task": True,
			"is_ucr_application": False,
			"is_ucr_finance": ucr_finance,
			"show_finance_lines": ucr_finance,
			"show_documents": seq in finance_payment_with_supplier_invoice_sequences(),
			"documents_read_only": False,
			"show_permits": is_permit_finance_payment_task(seq),
			"show_payments": True,
			"show_external_ref": True,
			"show_description": True,
			"auto_intake_intro": False,
			"hide_mark_complete": True,
		}
	if is_light_proof_task(seq):
		return {
			"is_sea_task": True,
			"show_documents": False,
			"documents_read_only": False,
			"show_payments": False,
			"show_external_ref": True,
			"show_description": True,
			"auto_intake_intro": False,
			"hide_mark_complete": False,
		}
	return {
		"is_sea_task": True,
		"show_documents": True,
		"documents_read_only": False,
		"show_payments": False,
		"show_external_ref": seq >= 3,
		"show_description": True,
		"auto_intake_intro": False,
		"hide_mark_complete": False,
	}


# Standard Task fields to hide on all sea clearance tasks (reduce noise).
SEA_TASK_HIDDEN_FIELDS = (
	"is_template",
	"issue",
	"type",
	"color",
	"is_milestone",
	"task_weight",
	"exp_start_date",
	"exp_end_date",
	"expected_time",
	"duration",
	"progress",
	"total_costing_amount",
	"total_billing_amount",
	"total_expense_claim",
	"review_date",
	"closing_date",
	"template_tasks",
)
