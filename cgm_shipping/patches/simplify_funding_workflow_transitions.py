"""Remove role-copied Submit/Cancel transitions from funding workflows.

One business step becomes one Workflow Transition. DocType permissions
decide who can open the document.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import (
	simplify_funding_workflow_records,
)


def execute() -> None:
	simplify_funding_workflow_records()
	frappe.db.commit()
