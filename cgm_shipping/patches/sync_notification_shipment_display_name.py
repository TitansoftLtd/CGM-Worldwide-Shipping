"""Create missing sea Notifications only — never overwrite Desk templates.

Shipment display names (LJL-… / size / batch) are applied at send time via
``stamp_shipment_name_on_doc`` and Jinja in each Notification's own message.
Edit copy on the Notification document in Desk.
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
