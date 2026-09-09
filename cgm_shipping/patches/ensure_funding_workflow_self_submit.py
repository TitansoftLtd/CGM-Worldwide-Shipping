"""No-op. Workflow transitions are configured in Desk, not from Python.

Allow Self Approval on Submit / Submit Request must be set on the live
CGM Material Request Funding and CGM Funding Request Approval workflows.
"""

from __future__ import annotations


def execute() -> None:
	return
