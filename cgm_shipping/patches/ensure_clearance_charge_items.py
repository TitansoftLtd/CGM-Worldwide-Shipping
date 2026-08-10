"""Seed Clearance Charge Item master rows (UCR Invoice, UCR Receipt, …)."""

from __future__ import annotations

import frappe


def execute() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.clearance_charge_item import (
		backfill_task_finance_line_charge_items,
		ensure_clearance_charge_items,
	)

	created = ensure_clearance_charge_items()
	backfilled = backfill_task_finance_line_charge_items()
	if created or backfilled:
		frappe.db.commit()
