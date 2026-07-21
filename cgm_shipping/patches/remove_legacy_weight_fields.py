"""Remove legacy Opportunity weight custom fields absent from the customization export.

``custom_weight_nw`` / ``custom_weight_gw`` on Opportunity were superseded by
``custom_net_weight`` / ``custom_gross_weight`` (which live in
``custom/opportunity.json`` and sync on migrate). The legacy fields are Float
columns whose ``decimal(21,9)`` conversion fails on unsanitized legacy data
(MySQL 1265, "Data truncated"), breaking ``sync_customizations``. Removing the
Custom Field and dropping the column *before* ``sync_customizations`` both
propagates the deletion to every site and unblocks migrate.

Scope: Opportunity only. The Project copies of these fields are left untouched.
"""

from __future__ import annotations

import frappe

DOCTYPE = "Opportunity"
LEGACY_WEIGHT_FIELDS = ("custom_weight_nw", "custom_weight_gw")


def execute() -> None:
	for fieldname in LEGACY_WEIGHT_FIELDS:
		# Delete the Custom Field definition on Opportunity if it still exists.
		name = frappe.db.get_value(
			"Custom Field", {"dt": DOCTYPE, "fieldname": fieldname}
		)
		if name:
			frappe.delete_doc("Custom Field", name, force=1, ignore_permissions=True)

		# Drop the leftover column — covers sites where the Custom Field was already
		# deleted in the UI but the column (and its dirty data) still remain.
		if frappe.db.table_exists(DOCTYPE) and frappe.db.has_column(DOCTYPE, fieldname):
			frappe.db.sql_ddl(f"ALTER TABLE `tab{DOCTYPE}` DROP COLUMN `{fieldname}`")

	frappe.clear_cache(doctype=DOCTYPE)
	frappe.db.commit()
