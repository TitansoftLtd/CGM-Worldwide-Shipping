"""Remove obsolete UOM.custom_is_volume_uom; use standard UOM.category instead."""

from __future__ import annotations

import frappe


def execute() -> None:
	if frappe.db.exists("Custom Field", {"dt": "UOM", "fieldname": "custom_is_volume_uom"}):
		frappe.delete_doc(
			"Custom Field",
			frappe.db.get_value(
				"Custom Field",
				{"dt": "UOM", "fieldname": "custom_is_volume_uom"},
				"name",
			),
			force=1,
		)
		frappe.db.commit()
