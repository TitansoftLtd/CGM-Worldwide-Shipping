"""Seed ERPNext Notifications for sea clearance Task handoffs (create-if-missing)."""

from __future__ import annotations

import frappe


def execute() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
		ensure_sea_task_notifications,
	)

	created = ensure_sea_task_notifications()
	if created:
		frappe.db.commit()
