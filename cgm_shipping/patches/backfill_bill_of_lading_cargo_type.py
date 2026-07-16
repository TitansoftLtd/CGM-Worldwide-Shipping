"""Backfill missing cargo_type on Bill of Lading so FCL fields stay visible after submit."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
	ensure_bl_cargo_type,
)


def execute():
	if not frappe.db.table_exists("Bill of Lading"):
		return

	names = frappe.get_all(
		"Bill of Lading",
		filters={"cargo_type": ["in", ["", None]]},
		pluck="name",
	)
	for name in names:
		doc = frappe.get_doc("Bill of Lading", name)
		ensure_bl_cargo_type(doc)
		if (doc.get("cargo_type") or "").strip():
			frappe.db.set_value(
				"Bill of Lading",
				name,
				"cargo_type",
				doc.cargo_type,
				update_modified=False,
			)
