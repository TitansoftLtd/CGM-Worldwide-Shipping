"""Clear `response_status` on CGM-authored Shipment Updates.

`response_status` tracks a question CGM owes an answer to, so it belongs only
on messages raised by a customer or transporter. The field shipped with a
default of "Open", which Frappe applied on insert even though the write path
passes None for CGM sources - leaving internal updates looking like
unanswered questions in the detail dialog and in reports.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates import PARTY_SOURCES


def execute() -> None:
	if not frappe.db.table_exists("Shipment Update"):
		return
	if "response_status" not in frappe.db.get_table_columns("Shipment Update"):
		return

	placeholders = ", ".join(["%s"] * len(PARTY_SOURCES))
	frappe.db.sql(
		f"""
		UPDATE `tabShipment Update`
		SET response_status = NULL, responded_by = NULL, responded_on = NULL,
		    response_update = NULL
		WHERE update_source NOT IN ({placeholders})
		  AND IFNULL(response_status, '') != ''
		""",
		tuple(PARTY_SOURCES),
	)
	frappe.clear_cache(doctype="Shipment Update")
	frappe.db.commit()
