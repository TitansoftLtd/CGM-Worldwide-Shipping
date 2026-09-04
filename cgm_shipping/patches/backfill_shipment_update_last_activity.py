"""Backfill `last_activity_on` on Shipment Update.

The ops feed lists one row per thread and orders by the thread's newest
message. Rows written before the field existed have it empty, which would
sort them as though nothing had happened since the question was raised.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.table_exists("Shipment Update"):
		return
	if "last_activity_on" not in frappe.db.get_table_columns("Shipment Update"):
		return

	# Start everyone at their own posted_on...
	frappe.db.sql(
		"""
		UPDATE `tabShipment Update`
		SET last_activity_on = posted_on
		WHERE last_activity_on IS NULL
		"""
	)
	# ...then lift each thread root to its newest reply.
	frappe.db.sql(
		"""
		UPDATE `tabShipment Update` q
		JOIN (
			SELECT parent_update, MAX(posted_on) AS newest
			FROM `tabShipment Update`
			WHERE IFNULL(parent_update, '') != ''
			GROUP BY parent_update
		) r ON r.parent_update = q.name
		SET q.last_activity_on = r.newest
		WHERE r.newest > IFNULL(q.last_activity_on, q.posted_on)
		"""
	)
	frappe.db.commit()
