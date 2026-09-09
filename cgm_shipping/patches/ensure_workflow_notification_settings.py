"""Seed CGM Shipping Settings → Workflow notifications map (add missing events only)."""

from __future__ import annotations

import frappe


def execute() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
		ensure_sea_task_notifications,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_notifications import (
		ensure_workflow_notification_settings,
	)

	ensure_sea_task_notifications()
	if ensure_workflow_notification_settings():
		frappe.db.commit()
