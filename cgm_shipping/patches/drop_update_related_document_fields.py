"""Drop the Related Document Type / Related Document columns from Update.

Those two fields duplicated the links the Update already carries (project,
container_tracker, allocation) and, being a Link to DocType, offered every
DocType on the site in the picker. Removing them from the DocType stops
Frappe writing to the columns; this drops the orphaned columns so the stale
values do not linger in reports or exports.
"""

from __future__ import annotations

import frappe

_COLUMNS = ("related_doctype", "related_name")


def execute() -> None:
	if not frappe.db.table_exists("Shipment Update"):
		return

	existing = set(frappe.db.get_table_columns("Shipment Update"))
	for column in _COLUMNS:
		if column not in existing:
			continue
		frappe.db.sql_ddl(f"ALTER TABLE `tabShipment Update` DROP COLUMN `{column}`")

	frappe.clear_cache(doctype="Shipment Update")
