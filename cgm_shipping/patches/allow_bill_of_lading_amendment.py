"""Allow amended Bills of Lading to reuse the same B/L number."""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.table_exists("Bill of Lading"):
		return

	indexes = frappe.db.sql(
		"""
		SHOW INDEX FROM `tabBill of Lading`
		WHERE Column_name = 'bl_number' AND Non_unique = 0
		""",
		as_dict=True,
	)
	for row in indexes:
		key_name = row.get("Key_name")
		if key_name:
			frappe.db.sql_ddl(f"ALTER TABLE `tabBill of Lading` DROP INDEX `{key_name}`")
