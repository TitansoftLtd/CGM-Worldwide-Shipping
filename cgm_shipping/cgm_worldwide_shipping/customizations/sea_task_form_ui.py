"""
Per-task form visibility for sea clearance tasks (SEA_IMPORT_E2E).

Client task.js loads sequence lists from get_sea_task_ui_sequences (Settings-driven).
"""
from __future__ import annotations

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
