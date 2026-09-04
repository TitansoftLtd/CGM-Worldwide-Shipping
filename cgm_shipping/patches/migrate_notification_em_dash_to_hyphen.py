"""One-time: swap the em dash separator in Notification copy for a plain hyphen.

Why: seeds are create-only (see ``ensure_sea_task_notifications``), so sites that
already hold the sea Task Notifications keep the `" — "` separator the old seed
templates shipped with. Code templates now use `" - "`; this realigns live docs.

What: literal `" — "` → `" - "` on Notification ``subject`` and ``message`` only.
Every other Desk edit (recipients, condition, channel) is left untouched.

Idempotent: yes (re-running finds nothing to change), but it is a one-time data
rewrite — retire once staging + production Patch Log show success.
"""

from __future__ import annotations

import frappe

OLD = " — "
NEW = " - "


def execute() -> None:
	if not frappe.db.exists("DocType", "Notification"):
		return

	rows: dict[str, frappe._dict] = {}
	for field in ("subject", "message"):
		for row in frappe.get_all(
			"Notification",
			filters={field: ("like", f"%{OLD}%")},
			fields=["name", "subject", "message"],
		):
			rows[row.name] = row

	updated = 0
	for name, row in rows.items():
		values = {
			field: row.get(field).replace(OLD, NEW)
			for field in ("subject", "message")
			if row.get(field) and OLD in row.get(field)
		}
		if not values:
			continue
		frappe.db.set_value("Notification", name, values, update_modified=False)
		frappe.clear_document_cache("Notification", name)
		updated += 1

	if updated:
		frappe.db.commit()
