"""Move Container Allocation off random hashes onto the ALC naming series.

Allocations were named `hash`, so an ops user quoting one to a haulier had to
read out `jbdjf7nb2r`. They now follow the same compact convention as Shipment
Update - prefix, two-digit year, five digits: `ALC2600001`.

Existing rows are renamed oldest first so the sequence reads chronologically,
and the series counter is pointed past the highest number in use so the next
allocation follows on rather than colliding.
"""

from __future__ import annotations

import re

import frappe
from frappe.model.naming import make_autoname

SERIES = "ALC.YY.#####"
_ALREADY_NAMED = re.compile(r"^ALC\d{7}$")


def execute() -> None:
	if not frappe.db.table_exists("Container Allocation"):
		return

	from frappe.model.rename_doc import rename_doc
	_clear_series_property_setters()

	rows = frappe.get_all("Container Allocation", fields=["name"], order_by="creation asc")
	targets = [row.name for row in rows if not _ALREADY_NAMED.match(row.name)]

	renamed = 0
	for old_name in targets:
		new_name = make_autoname(SERIES, "Container Allocation")
		if frappe.db.exists("Container Allocation", new_name):
			continue
		rename_doc(
			"Container Allocation",
			old_name,
			new_name,
			force=True,
			ignore_permissions=True,
			show_alert=False,
			# Bulk renaming would enqueue one global-search rebuild per row and
			# swamp the queue; migrate rebuilds the index anyway.
			rebuild_search=False,
		)
		frappe.db.set_value(
			"Container Allocation", new_name, "naming_series", SERIES, update_modified=False
		)
		renamed += 1

	_backfill_series_field()
	_align_series_counter()
	if renamed:
		print(f"Container Allocation: renamed {renamed} allocation(s) to {SERIES}.")
	frappe.db.commit()


def _clear_series_property_setters() -> None:
	for name in frappe.get_all(
		"Property Setter",
		filters={"doc_type": "Container Allocation", "field_name": "naming_series"},
		pluck="name",
	):
		frappe.delete_doc("Property Setter", name, force=True, ignore_permissions=True)
	frappe.clear_cache(doctype="Container Allocation")


def _backfill_series_field() -> None:
	"""The field is reqd, so a row carrying no series would fail its next save."""
	if not frappe.db.has_column("Container Allocation", "naming_series"):
		return
	frappe.db.sql(
		"UPDATE `tabContainer Allocation` SET naming_series = %s "
		"WHERE naming_series IS NULL OR naming_series = ''",
		(SERIES,),
	)


def _align_series_counter() -> None:
	"""Point the series at the highest number in use, so the next one follows on."""
	key = f"ALC{frappe.utils.nowdate()[2:4]}"
	highest = frappe.db.sql(
		"""
		SELECT MAX(CAST(SUBSTRING(name, %s) AS UNSIGNED))
		FROM `tabContainer Allocation`
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
