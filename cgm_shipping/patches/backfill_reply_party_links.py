"""Give replies the party links of the message they answer.

`create_update` derives `customer` from the shipment, so a reply to a general
query - which has no shipment - came out with no customer at all. Such a reply
drops out of the customer's own thread and out of the notification recipients,
so the answer never reaches them. The write path now inherits the party from
the parent; this repairs rows written before it did.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.table_exists("Shipment Update"):
		return

	columns = set(frappe.db.get_table_columns("Shipment Update"))
	if not {"parent_update", "customer", "transporter"} <= columns:
		return

	for field in ("customer", "transporter"):
		frappe.db.sql(
			f"""
			UPDATE `tabShipment Update` reply
			JOIN `tabShipment Update` parent ON parent.name = reply.parent_update
			SET reply.`{field}` = parent.`{field}`
			WHERE IFNULL(reply.`{field}`, '') = ''
			  AND IFNULL(parent.`{field}`, '') != ''
			"""
		)
	frappe.db.commit()
