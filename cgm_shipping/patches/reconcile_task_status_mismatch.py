"""Reconcile Task.status for sea clearance rows stuck Open after payment gates passed.

Idempotent — safe to re-run on migrate.
"""

from __future__ import annotations

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_status import (
		reconcile_open_tasks_ready_to_complete,
	)

	result = reconcile_open_tasks_ready_to_complete(dry_run=False)
	if result.get("reconciled"):
		frappe.logger("cgm_shipping").info(f"Task status reconciliation: {result}")
