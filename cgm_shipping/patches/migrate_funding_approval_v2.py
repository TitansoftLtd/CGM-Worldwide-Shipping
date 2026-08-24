# Copyright (c) 2026, Titansoft Limited and contributors
# See license.txt
"""One-time Funding Request approval v2 data migration (no workflow installation)."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	FUNDING_REQUEST_STATE_APPROVED,
	FUNDING_REQUEST_STATE_DISBURSED,
	FUNDING_REQUEST_STATE_DISBURSEMENT,
	FUNDING_REQUEST_STATE_PENDING,
	MR_WORKFLOW_STATE_FIELD,
)

# Legacy workflow_state values on existing records only — not used at runtime.
_LEGACY_FUNDING_WORKFLOW_STATE_MAP = {
	"Pending Director Approval": FUNDING_REQUEST_STATE_PENDING,
	"Director Approved": FUNDING_REQUEST_STATE_APPROVED,
	"Funding in Progress": FUNDING_REQUEST_STATE_DISBURSEMENT,
	"Funded": FUNDING_REQUEST_STATE_DISBURSED,
	"Submit for Director Approval": "Submit for Approval",
}


def _migrate_funding_workflow_state_names() -> None:
	for old, new in _LEGACY_FUNDING_WORKFLOW_STATE_MAP.items():
		if old == new:
			continue
		if frappe.db.has_column("Funding Request", "workflow_state"):
			frappe.db.sql(
				"""
				UPDATE `tabFunding Request`
				SET workflow_state = %(new)s
				WHERE workflow_state = %(old)s
				""",
				{"old": old, "new": new},
			)
		if frappe.db.has_column("Material Request", MR_WORKFLOW_STATE_FIELD):
			frappe.db.sql(
				f"""
				UPDATE `tabMaterial Request`
				SET `{MR_WORKFLOW_STATE_FIELD}` = %(new)s
				WHERE `{MR_WORKFLOW_STATE_FIELD}` = %(old)s
				""",
				{"old": old, "new": new},
			)
		if frappe.db.exists("Workflow State", old) and not frappe.db.exists("Workflow State", new):
			try:
				frappe.rename_doc("Workflow State", old, new, force=1, merge=False)
			except Exception:
				pass


def _migrate_funding_approval_v2_columns() -> None:
	"""Director → approved_by; flip reduction columns to variance; backfill decision."""
	child = "Funding Request Material Request"
	parent = "Funding Request"
	if frappe.db.has_column(parent, "director") and not frappe.db.has_column(parent, "approved_by"):
		frappe.db.sql(f"ALTER TABLE `tab{parent}` CHANGE `director` `approved_by` varchar(140)")
	elif frappe.db.has_column(parent, "director") and frappe.db.has_column(parent, "approved_by"):
		frappe.db.sql(
			f"""
			UPDATE `tab{parent}`
			SET approved_by = director
			WHERE IFNULL(approved_by, '') = ''
			  AND IFNULL(director, '') != ''
			"""
		)
	if frappe.db.has_column(parent, "total_reduction") and not frappe.db.has_column(
		parent, "total_variance"
	):
		frappe.db.sql(
			f"ALTER TABLE `tab{parent}` CHANGE `total_reduction` `total_variance` decimal(21,9) not null default 0"
		)
	if frappe.db.has_column(child, "reduction_amount") and not frappe.db.has_column(child, "variance"):
		frappe.db.sql(
			f"ALTER TABLE `tab{child}` CHANGE `reduction_amount` `variance` decimal(21,9) not null default 0"
		)
		frappe.db.sql(f"UPDATE `tab{child}` SET variance = 0 - variance WHERE variance != 0")
	if frappe.db.has_column(child, "reduction_reason") and not frappe.db.has_column(
		child, "adjustment_reason"
	):
		frappe.db.sql(f"ALTER TABLE `tab{child}` CHANGE `reduction_reason` `adjustment_reason` text")
	if frappe.db.has_column(child, "decision"):
		frappe.db.sql(
			f"""
			UPDATE `tab{child}`
			SET decision = 'Approved'
			WHERE IFNULL(decision, '') = ''
			  AND IFNULL(approved_amount, 0) > 0
			"""
		)
		frappe.db.sql(
			f"""
			UPDATE `tab{child}`
			SET decision = 'Pending'
			WHERE IFNULL(decision, '') = ''
			"""
		)
	if frappe.db.has_column(child, "variance"):
		frappe.db.sql(
			f"""
			UPDATE `tab{child}`
			SET variance = IFNULL(approved_amount, 0) - IFNULL(requested_amount, 0)
			"""
		)


def execute():
	_migrate_funding_workflow_state_names()
	_migrate_funding_approval_v2_columns()
	frappe.clear_cache()
