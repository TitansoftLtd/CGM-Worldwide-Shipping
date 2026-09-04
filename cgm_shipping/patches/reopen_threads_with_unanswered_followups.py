"""Reopen threads whose latest party message is still unanswered.

The ops feed lists one row per thread, so the thread's first message carries
its response status. A customer or transporter coming back on a thread now
reopens it; rows written before that did not, leaving a follow-up sitting
unanswered inside a thread the board showed as Answered.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.table_exists("Shipment Update"):
		return
	columns = set(frappe.db.get_table_columns("Shipment Update"))
	if not {"parent_update", "response_status", "update_source"} <= columns:
		return

	frappe.db.sql(
		"""
		UPDATE `tabShipment Update` root
		JOIN (
			SELECT parent_update
			FROM `tabShipment Update`
			WHERE IFNULL(parent_update, '') != ''
			  AND update_source IN ('Customer', 'Transporter')
			  AND IFNULL(response_status, '') = 'Open'
			GROUP BY parent_update
		) open_followups ON open_followups.parent_update = root.name
		SET root.response_status = 'Open', root.is_read = 0
		WHERE root.update_source IN ('Customer', 'Transporter')
		"""
	)
	frappe.db.commit()
