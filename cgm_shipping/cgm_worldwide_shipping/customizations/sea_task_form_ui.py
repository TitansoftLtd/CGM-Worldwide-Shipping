"""
Per-task form visibility for sea clearance tasks (SEA_IMPORT_E2E).

Used by public/js/task.js via frappe.call or duplicated constants — keep in sync.
"""
from __future__ import annotations

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
	SEA_AUTO_COMPLETE_TASK_SEQS,
	SEA_PAYMENT_TASK_SEQS,
	SEA_TASK_FLOW_KEY,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
	SEA_PERMIT_APPLICATION_TASK_SEQS,
)

# Finance payment steps
PAYMENT_SEQS = SEA_PAYMENT_TASK_SEQS

# Steps where task-level document uploads are expected (incl. finance invoices).
DOCUMENT_TASK_SEQS = frozenset({3, 5, 7, 9, 10, 11, 13, 15, 16, 17, 19, 20, 21, 22, 23, 24}) | frozenset(
	PAYMENT_SEQS
)

# Tracking / coordination — description + ref only.
LIGHT_TASK_SEQS = frozenset({8})


def get_sea_task_form_ui(sequence_no: int) -> dict:
	"""Return UI flags for Task form (documents, payments, fields to hide)."""
	seq = int(sequence_no or 0)
	if seq in SEA_AUTO_COMPLETE_TASK_SEQS:
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
	if seq in SEA_PERMIT_APPLICATION_TASK_SEQS:
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
	if seq in PAYMENT_SEQS:
		return {
			"is_sea_task": True,
			"show_documents": True,
			"documents_read_only": False,
			"show_permits": seq == 6,
			"show_payments": True,
			"show_external_ref": True,
			"show_description": True,
			"auto_intake_intro": False,
			"hide_mark_complete": True,
		}
	if seq in LIGHT_TASK_SEQS:
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
	if seq in DOCUMENT_TASK_SEQS:
		return {
			"is_sea_task": True,
			"show_documents": True,
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
