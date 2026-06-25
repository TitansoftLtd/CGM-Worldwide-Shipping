"""Remove duplicate DocField rows on CGM Shipping Settings (bad field_order merge)."""
from __future__ import annotations

import json
import os

import frappe


DOCTYPE = "CGM Shipping Settings"


def _field_order_from_app_json() -> list[str]:
	"""field_order exists in the doctype JSON file, not on the DocType DB record."""
	path = os.path.join(
		frappe.get_app_path("cgm_shipping"),
		"cgm_worldwide_shipping",
		"doctype",
		"cgm_shipping_settings",
		"cgm_shipping_settings.json",
	)
	if not os.path.exists(path):
		return []
	with open(path, encoding="utf-8") as handle:
		data = json.load(handle)
	order = list(data.get("field_order") or [])
	# Preserve order, drop duplicate names.
	return list(dict.fromkeys(order))


def _renumber_docfields(field_order: list[str]) -> None:
	"""Apply idx from JSON field_order; append any extra DB fields at the end."""
	existing = frappe.get_all(
		"DocField",
		filters={"parent": DOCTYPE, "parenttype": "DocType"},
		pluck="fieldname",
	)
	existing_set = set(existing)
	ordered = [fn for fn in field_order if fn in existing_set]
	for fn in existing:
		if fn not in ordered:
			ordered.append(fn)

	for idx, fieldname in enumerate(ordered, start=1):
		frappe.db.set_value(
			"DocField",
			{"parent": DOCTYPE, "parenttype": "DocType", "fieldname": fieldname},
			"idx",
			idx,
			update_modified=False,
		)


def execute() -> None:
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	rows = frappe.get_all(
		"DocField",
		filters={"parent": DOCTYPE, "parenttype": "DocType"},
		fields=["name", "fieldname", "idx"],
		order_by="idx asc, creation asc",
	)

	seen: set[str] = set()
	duplicate_names: list[str] = []
	for row in rows:
		if row.fieldname in seen:
			duplicate_names.append(row.name)
			continue
		seen.add(row.fieldname)

	for name in duplicate_names:
		frappe.delete_doc("DocField", name, force=1, ignore_permissions=True)

	field_order = _field_order_from_app_json()
	if field_order:
		_renumber_docfields(field_order)
	elif rows:
		# Fallback: keep surviving rows in current idx order.
		_renumber_docfields([r.fieldname for r in rows if r.name not in duplicate_names])

	frappe.clear_cache(doctype=DOCTYPE)
	frappe.db.commit()
