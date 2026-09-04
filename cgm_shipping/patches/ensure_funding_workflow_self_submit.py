"""Let requesters submit their own Material / Funding Requests.

Idempotent: turns on Allow Self Approval for Submit / Submit Request only.
Approve and Reject stay checker-only.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import (
	ensure_funding_workflow_self_submit,
)


def execute() -> None:
	ensure_funding_workflow_self_submit()
	frappe.db.commit()
