"""Let the Funding Request owner use Actions when they have the transition role.

Frappe hides Approve / Reject / disbursement actions from the document owner
unless Allow Self Approval is on. Finance users who also approve were blocked
on their own drafts.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.exists("Workflow", "CGM Funding Request Approval"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabWorkflow Transition`
		SET allow_self_approval = 1
		WHERE parent = 'CGM Funding Request Approval'
		"""
	)
	frappe.clear_cache()
	frappe.db.commit()
