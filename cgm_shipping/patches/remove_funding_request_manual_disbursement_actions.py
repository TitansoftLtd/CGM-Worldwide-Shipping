"""Remove manual Start/Record Disbursement actions from Funding Request.

Disbursement in Progress and Disbursed are driven by Journal Entries,
Purchase Orders, and recorded payments instead.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import (
	simplify_funding_workflow_records,
)


def execute() -> None:
	simplify_funding_workflow_records()
	frappe.db.commit()
