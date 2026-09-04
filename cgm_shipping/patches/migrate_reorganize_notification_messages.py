"""One-time: re-align seeded Notification copy to the shared body layout.

Why: notification emails had drifted into three different shapes - some a wall of
<p> tags, some naming the project as PROJ-####, some still on the pre-hyphen
subjects. Every seeded body now uses one layout: lead line, detail table
(shipment / task / reference / due), numbered "What to do" steps, optional note,
then the links.

What: rewrites ``subject``, ``message`` and ``message_type`` on the CGM seeded
Notifications only, from the code templates. Recipients, channel, event, enabled
and any Notification not seeded by this app are left untouched.

Note: this is a deliberate, one-off exception to "Desk is the source of truth
after seed" - it re-bases the seeded copy, and Desk stays authoritative again
afterwards. Retire once staging + production Patch Log show success.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.exists("DocType", "Notification"):
		return

	for name, subject, message in _templates():
		if not frappe.db.exists("Notification", name):
			continue
		values = {"message": message, "message_type": "HTML"}
		if subject:
			values["subject"] = subject
		frappe.db.set_value("Notification", name, values, update_modified=False)
		frappe.clear_document_cache("Notification", name)

	frappe.db.commit()


def _templates() -> list[tuple[str, str | None, str]]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		FINAL_DOCUMENT_NOTIFICATION,
		OPERATIONAL_UPDATE_NOTIFICATION,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
		sea_task_notification_definitions,
	)

	rows: list[tuple[str, str | None, str]] = [
		(spec["name"], spec["subject"], spec["message"])
		for spec in sea_task_notification_definitions()
	]

	from cgm_shipping.patches.ensure_final_document_review_notification import (
		final_document_review_message,
	)
	from cgm_shipping.patches.ensure_operational_update_notification import (
		operational_update_message,
	)

	# Subject left as-is on these two: it already reads well and is Desk-tuned.
	rows.append((FINAL_DOCUMENT_NOTIFICATION, None, final_document_review_message()))
	rows.append((OPERATIONAL_UPDATE_NOTIFICATION, None, operational_update_message()))
	return rows
