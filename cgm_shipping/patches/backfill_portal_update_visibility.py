"""Backfill portal visibility flags on existing Update rows.

`Update.visible_to_customer` / `visible_to_transporter` decide what each
portal conversation shows. Updates written before those fields existed have
them at 0, which would hide a customer's own past messages from them. A
party's own post is always visible to that party, so set the flag to match
the source. Internal / Customs / Finance rows are deliberately left at 0 -
they were never portal-facing and must not become so retroactively.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.exists("DocType", "Shipment Update"):
		return

	meta = frappe.get_meta("Shipment Update")
	if not (meta.has_field("visible_to_customer") and meta.has_field("visible_to_transporter")):
		return

	frappe.db.sql(
		"""
		UPDATE `tabShipment Update`
		SET visible_to_customer = 1
		WHERE update_source = 'Customer'
		  AND IFNULL(visible_to_customer, 0) = 0
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabShipment Update`
		SET visible_to_transporter = 1
		WHERE update_source = 'Transporter'
		  AND IFNULL(visible_to_transporter, 0) = 0
		"""
	)
	frappe.db.commit()
