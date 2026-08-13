"""Create missing sea Notifications only — never overwrite Desk edits.

Historically this patch realigned recipients/messages from code. That fought
server-side Notification edits. Desk + CGM Shipping Settings → Workflow
notifications are now the source of truth after first seed.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
		ensure_sea_task_notifications,
	)

	created = ensure_sea_task_notifications()
	if created:
		frappe.db.commit()
