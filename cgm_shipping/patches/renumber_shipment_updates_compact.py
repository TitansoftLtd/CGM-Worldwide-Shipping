"""Renumber Shipment Update references without separators.

The first pass numbered them `MSG-26-00001`; the reference reads better as
`MSG2600001`, so sites that already ran that pass are renumbered here. A site
seeing the rename for the first time gets the compact form directly and this
finds nothing to do.

Order is preserved: rows are renumbered oldest first, so the sequence still
reads chronologically.
"""

from __future__ import annotations

import re

import frappe
from frappe.model.naming import make_autoname

SERIES = "MSG.YY.#####"
_HYPHENATED = re.compile(r"^MSG-(\d{2})-(\d{5})$")


def execute() -> None:
	if not frappe.db.table_exists("Shipment Update"):
		return

	from frappe.model.rename_doc import rename_doc

	rows = frappe.get_all(
		"Shipment Update", fields=["name"], order_by="posted_on asc, creation asc"
	)
	targets = [r.name for r in rows if _HYPHENATED.match(r.name)]
	if not targets:
		# Names are already compact, but the property setters may still pin the
		# old series onto new rows.
		_clear_series_property_setters()
		_align_series_counter()
		frappe.db.commit()
		return

	for old_name in targets:
		match = _HYPHENATED.match(old_name)
		# Keep the number it already had; only the separators go.
		new_name = f"MSG{match.group(1)}{match.group(2)}"
		if frappe.db.exists("Shipment Update", new_name):
			new_name = make_autoname(SERIES, "Shipment Update")
		rename_doc(
			"Shipment Update",
			old_name,
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

	_clear_series_property_setters()
	_align_series_counter()
	print(f"Shipment Update: renumbered {len(targets)} references to {SERIES}.")
	frappe.db.commit()


def _clear_series_property_setters() -> None:
	"""Let the app's DocType define the series.

	Frappe writes Property Setters for `naming_series` options and default the
	first time a series is synced. They then win over the DocType JSON, so a
	change to the series in the app would be silently ignored - which is how
	new rows kept getting the old hyphenated reference.
	"""
	for name in frappe.get_all(
		"Property Setter",
		filters={"doc_type": "Shipment Update", "field_name": "naming_series"},
		pluck="name",
	):
		frappe.delete_doc("Property Setter", name, force=True, ignore_permissions=True)
	frappe.clear_cache(doctype="Shipment Update")


def _align_series_counter() -> None:
	"""Point the series at the highest number in use, so the next one follows on."""
	prefix = frappe.utils.nowdate()[2:4]
	key = f"MSG{prefix}"
	highest = frappe.db.sql(
		"""
		SELECT MAX(CAST(SUBSTRING(name, %s) AS UNSIGNED))
		FROM `tabShipment Update`
		WHERE name LIKE %s
		""",
		(len(key) + 1, key + "%"),
	)[0][0]
	if not highest:
		return
	frappe.db.sql(
		"INSERT INTO `tabSeries` (name, current) VALUES (%s, %s) "
		"ON DUPLICATE KEY UPDATE current = GREATEST(current, VALUES(current))",
		(key, highest),
	)
