"""Rename Container Tracker type_of_container → cargo_size after container→cargo rename."""

from __future__ import annotations

import frappe


def execute():
	table = "`tabContainer Tracker`"
	if not frappe.db.has_column("Container Tracker", "type_of_container"):
		return
	if frappe.db.has_column("Container Tracker", "cargo_size"):
		frappe.db.sql(
			f"""
			UPDATE {table}
			SET cargo_size = type_of_container
			WHERE IFNULL(cargo_size, '') = '' AND IFNULL(type_of_container, '') != ''
			"""
		)
		frappe.db.sql_ddl(f"ALTER TABLE {table} DROP COLUMN `type_of_container`")
		return

	frappe.db.sql_ddl(
		f"ALTER TABLE {table} CHANGE COLUMN `type_of_container` `cargo_size` varchar(140)"
	)
