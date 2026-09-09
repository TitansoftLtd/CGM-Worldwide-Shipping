"""One-time: swap em dashes in Notification copy for plain hyphens.

Why: seeds are create-only (see ``ensure_sea_task_notifications``), so sites that
already hold the sea Task Notifications keep the em dashes the old seed templates
shipped with. Code templates now use hyphens; this realigns live docs.

What: on Notification ``subject`` and ``message`` only — the `" — "` separator
becomes `" - "`, and the Jinja fallback `'—'` (shown when a task has no shipment)
becomes `'-'`. Every other Desk edit (recipients, condition, channel) is left
untouched.

Idempotent: yes (re-running finds nothing to change), but it is a one-time data
rewrite — retire once staging + production Patch Log show success.
"""

from __future__ import annotations

import frappe

REPLACEMENTS = ((" — ", " - "), ("'—'", "'-'"))
FIELDS = ("subject", "message")


def _rewrite(value: str | None) -> str | None:
	if not value:
		return value
	for old, new in REPLACEMENTS:
		value = value.replace(old, new)
	return value


def execute() -> None:
	if not frappe.db.exists("DocType", "Notification"):
		return

	rows: dict[str, frappe._dict] = {}
	for field in FIELDS:
		for row in frappe.get_all(
			"Notification",
			filters={field: ("like", "%—%")},
			fields=["name", *FIELDS],
		):
			rows[row.name] = row

	updated = 0
	for name, row in rows.items():
		values = {
			field: _rewrite(row.get(field))
			for field in FIELDS
			if row.get(field) and _rewrite(row.get(field)) != row.get(field)
		}
		if not values:
			continue
		frappe.db.set_value("Notification", name, values, update_modified=False)
		frappe.clear_document_cache("Notification", name)
		updated += 1

	if updated:
		frappe.db.commit()
