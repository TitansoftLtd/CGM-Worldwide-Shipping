"""Rename orphaned Project Custom Field document names from early typos.

Some sites created ``custom__cargo_cutoff_`` / ``custom__voyage_number_`` before
the fieldnames were corrected to ``custom_cargo_cutoff`` / ``custom_voyage_number``.
The DB column and fieldname were fixed, but the Custom Field *name* stayed on the
old value. Customize Form then fails with "already exists" when saving new fields.
"""

from __future__ import annotations

import json

import frappe

LEGACY_RENAMES = (
	("Project-custom__cargo_cutoff_", "Project-custom_cargo_cutoff", "custom_cargo_cutoff"),
	("Project-custom__voyage_number_", "Project-custom_voyage_number", "custom_voyage_number"),
)

LEGACY_FIELDNAMES = {
	"custom__cargo_cutoff_": "custom_cargo_cutoff",
	"custom__voyage_number_": "custom_voyage_number",
}


def _rename_custom_field(old_name: str, new_name: str, fieldname: str) -> None:
	if not frappe.db.exists("Custom Field", old_name):
		return
	if frappe.db.exists("Custom Field", new_name):
		frappe.delete_doc("Custom Field", old_name, force=1, ignore_permissions=True)
		return

	frappe.db.sql(
		"""
		UPDATE `tabCustom Field`
		SET name = %s, fieldname = %s
		WHERE name = %s
		""",
		(new_name, fieldname, old_name),
	)


def _fix_insert_after_references() -> None:
	for old_fieldname, new_fieldname in LEGACY_FIELDNAMES.items():
		for row in frappe.get_all(
			"Custom Field",
			filters={"dt": "Project", "insert_after": old_fieldname},
			pluck="name",
		):
			frappe.db.set_value(
				"Custom Field",
				row,
				"insert_after",
				new_fieldname,
				update_modified=False,
			)


def _fix_field_order() -> None:
	prop_name = frappe.db.get_value(
		"Property Setter",
		{"doc_type": "Project", "property": "field_order", "field_name": None},
		"name",
	)
	if not prop_name:
		return

	raw = frappe.db.get_value("Property Setter", prop_name, "value")
	if not raw:
		return

	try:
		order = json.loads(raw)
	except (TypeError, ValueError):
		return

	changed = False
	new_order = []
	for entry in order:
		replacement = LEGACY_FIELDNAMES.get(entry, entry)
		if replacement != entry:
			changed = True
		if replacement not in new_order:
			new_order.append(replacement)
		else:
			changed = True

	if changed:
		frappe.db.set_value(
			"Property Setter",
			prop_name,
			"value",
			json.dumps(new_order),
			update_modified=False,
		)


def execute() -> None:
	for old_name, new_name, fieldname in LEGACY_RENAMES:
		_rename_custom_field(old_name, new_name, fieldname)

	_fix_insert_after_references()
	_fix_field_order()

	frappe.db.commit()
	frappe.clear_cache(doctype="Project")
