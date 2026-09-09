"""Give every Shipment Update a readable reference number.

The DocType was named by random hash, so a message had no reference anyone
could quote - not in an email, not on the phone. It now uses the series
`MSG.YY.#####` (MSG2600001); this renames the existing hash-named rows into that series
in the order they were posted, so the numbers read chronologically.

`frappe.rename_doc` rewrites the Link and Dynamic Link values pointing at each
row, which is what keeps `parent_update`, `response_update` and the Email Queue
references intact.
"""

from __future__ import annotations

import re

import frappe
from frappe.model.naming import make_autoname

SERIES = "MSG.YY.#####"
# Anything already in the series is left alone, so this is safe to re-run.
_SERIES_PATTERN = re.compile(r"^MSG\d{2}\d{5}$")


def execute() -> None:
	if not frappe.db.table_exists("Shipment Update"):
		return
	if "naming_series" not in frappe.db.get_table_columns("Shipment Update"):
		return

	from frappe.model.rename_doc import rename_doc

	rows = frappe.get_all(
		"Shipment Update",
		fields=["name"],
		order_by="posted_on asc, creation asc",
	)
	renamed = 0
	for row in rows:
		if _SERIES_PATTERN.match(row.name):
			continue
		new_name = make_autoname(SERIES, "Shipment Update")
		rename_doc(
			"Shipment Update",
			row.name,
			new_name,
			force=True,
			ignore_permissions=True,
			show_alert=False,
			# Renaming in bulk would enqueue one global-search rebuild per row
			# and swamp the queue; migrate rebuilds the index anyway.
			rebuild_search=False,
		)
		frappe.db.set_value(
			"Shipment Update", new_name, "naming_series", SERIES, update_modified=False
		)
		renamed += 1

	if renamed:
		print(f"Shipment Update: renamed {renamed} rows into {SERIES}.")
	frappe.db.commit()
