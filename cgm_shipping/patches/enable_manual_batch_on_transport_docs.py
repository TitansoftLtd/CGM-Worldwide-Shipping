"""Make Batch No editable on Booking Confirmation and Bill of Lading."""

from __future__ import annotations

import frappe


def execute():
	for doctype in ("Booking Confirmation", "Bill of Lading"):
		frappe.db.set_value(
			"DocField",
			{"parent": doctype, "fieldname": "batch_no"},
			"read_only",
			0,
			update_modified=False,
		)

	frappe.clear_cache(doctype="Booking Confirmation")
	frappe.clear_cache(doctype="Bill of Lading")
