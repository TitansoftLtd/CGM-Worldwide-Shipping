"""Drop the manual Partially Approve workflow action on Funding Request.

Partially Approved is derived after Approve when rows were rejected or amounts
were reduced below the requested total.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import (
	simplify_funding_workflow_records,
)


def execute() -> None:
	simplify_funding_workflow_records()
	frappe.db.commit()
