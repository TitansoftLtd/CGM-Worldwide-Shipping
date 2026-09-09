"""Migrate has_deposit checkbox to deposit_arrangement select on Bill of Lading."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	DEPOSIT_ARRANGEMENT_CONTAINER,
)


def execute() -> None:
	meta = frappe.get_meta("Bill of Lading")
	if not meta.has_field("deposit_arrangement"):
		return
	if not meta.has_field("has_deposit") and not frappe.db.has_column(
		"Bill of Lading", "has_deposit"
	):
		return

	for row in frappe.get_all(
		"Bill of Lading",
		filters={"has_deposit": 1},
		fields=["name", "deposit_arrangement"],
	):
		if (row.deposit_arrangement or "").strip():
			continue
		frappe.db.set_value(
			"Bill of Lading",
			row.name,
			"deposit_arrangement",
			DEPOSIT_ARRANGEMENT_CONTAINER,
			update_modified=False,
		)

	# Drop per-container has_deposit if present
	if frappe.db.has_column("Container", "has_deposit"):
		try:
			frappe.db.sql_ddl("ALTER TABLE `tabContainer` DROP COLUMN `has_deposit`")
		except Exception:
			frappe.log_error(title="Drop Container.has_deposit", message=frappe.get_traceback())

	frappe.db.commit()
