"""Remove unused Opportunity Cargo Cut-off duplicate (custom_cargo_cut_off).

Keep custom_cargo_cutoff — it matches Project and Booking Confirmation sync.
Idempotent: no-op when the unused Custom Field is already gone.
"""

from __future__ import annotations

import json

import frappe

DT = "Opportunity"
KEEP = "custom_cargo_cutoff"
DROP = "custom_cargo_cut_off"


def execute() -> None:
	_copy_values_then_drop_duplicate()
	_update_field_order()
	frappe.clear_cache(doctype=DT)


def _copy_values_then_drop_duplicate() -> None:
	keep_name = f"{DT}-{KEEP}"
	drop_name = f"{DT}-{DROP}"
	if not frappe.db.exists("Custom Field", drop_name):
		return

	if frappe.db.exists("Custom Field", keep_name) and frappe.db.has_column(DT, DROP):
		frappe.db.sql(
			f"""
			UPDATE `tab{DT}`
			SET `{KEEP}` = `{DROP}`
			WHERE ifnull(`{KEEP}`, '') = ''
				AND ifnull(`{DROP}`, '') != ''
			"""
		)

	frappe.delete_doc("Custom Field", drop_name, force=1)


def _update_field_order() -> None:
	name = "Opportunity-main-field_order"
	if not frappe.db.exists("Property Setter", name):
		return
	raw = frappe.db.get_value("Property Setter", name, "value") or ""
	try:
		order = json.loads(raw)
	except (TypeError, ValueError):
		return
	if not isinstance(order, list):
		return

	changed = False
	if DROP in order:
		order = [KEEP if field == DROP else field for field in order]
		changed = True
	if KEEP not in order:
		anchor = "custom_etd" if "custom_etd" in order else "custom_eta"
		if anchor in order:
			idx = order.index(anchor) + 1
			order.insert(idx, KEEP)
			changed = True
	seen = set()
	deduped = []
	for field in order:
		if field == KEEP and field in seen:
			changed = True
			continue
		seen.add(field)
		deduped.append(field)
	if changed:
		frappe.db.set_value(
			"Property Setter", name, "value", json.dumps(deduped), update_modified=False
		)
