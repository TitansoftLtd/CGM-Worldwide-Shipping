"""Repoint Cargo Size Link values that no longer match a master record.

``Cargo Size`` is named by field, so a master edited by hand (``40FT`` becoming
``40 Ft``) leaves every stored row pointing at a name that no longer exists.
Frappe runs ``_validate_links`` *before* ``before_save`` hooks, so the existing
``resolve_cargo_size_link`` normalisation in the save path never gets a chance
to repair those rows: any save of the parent (Project, Bill of Lading,
Opportunity, Task cascades during migrate) dies with
``Could not find Row #N: Cargo Size: 40FT``.

Rewrite stored values onto the matching master via the shared resolver, which
matches case / space insensitively and creates a master when nothing matches,
so no cargo size is lost. Idempotent: a site with clean links does nothing.
"""

from __future__ import annotations

import frappe


def _cargo_size_link_fields() -> list[tuple[str, str]]:
	"""Every (doctype, fieldname) Link pointing at Cargo Size."""
	fields = {
		(row.parent, row.fieldname)
		for row in frappe.get_all(
			"DocField",
			filters={"fieldtype": "Link", "options": "Cargo Size"},
			fields=["parent", "fieldname"],
		)
	}
	fields |= {
		(row.dt, row.fieldname)
		for row in frappe.get_all(
			"Custom Field",
			filters={"fieldtype": "Link", "options": "Cargo Size"},
			fields=["dt", "fieldname"],
		)
	}
	return sorted(fields)


def execute():
	if not frappe.db.exists("DocType", "Cargo Size"):
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
		resolve_cargo_size_link,
	)

	repaired = False
	for doctype, fieldname in _cargo_size_link_fields():
		if not frappe.db.has_column(doctype, fieldname):
			continue

		table = f"tab{doctype}"
		stored = frappe.db.sql_list(
			f"SELECT DISTINCT `{fieldname}` FROM `{table}` WHERE IFNULL(`{fieldname}`, '') <> ''"
		)
		for value in stored:
			if frappe.db.exists("Cargo Size", value):
				continue

			target = resolve_cargo_size_link(value)
			if not target or target == value:
				continue

			rows = frappe.db.count(doctype, {fieldname: value})
			frappe.db.sql(
				f"UPDATE `{table}` SET `{fieldname}` = %s WHERE `{fieldname}` = %s",
				(target, value),
			)
			repaired = True
			print(f"  {doctype}.{fieldname}: {value} -> {target} ({rows} row(s))")

	if not repaired:
		print("  All Cargo Size links already resolve to a master.")
