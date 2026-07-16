"""Idempotent renames: Container Type/Size → Cargo Type/Size on existing sites."""

from __future__ import annotations

import frappe
from frappe.model.rename_doc import rename_doc
from frappe.model.utils.rename_field import rename_field


def ensure_cargo_doctype_renames_before_migrate() -> None:
	"""Rename legacy DocTypes before JSON schema sync (filesystem folders already renamed)."""
	_rename_doctypes()
	frappe.db.commit()
	frappe.clear_cache()


def ensure_cargo_field_renames_after_migrate() -> None:
	"""Rename legacy fields after schema sync (requires new fieldnames in DocField meta)."""
	_rename_standard_fields()
	_rename_custom_fields()
	frappe.db.commit()
	frappe.clear_cache()


def ensure_cargo_terminology_renames() -> None:
	"""Full pass after migrate — doctypes (if missed) plus all field renames."""
	_rename_doctypes()
	_rename_standard_fields()
	_rename_custom_fields()
	frappe.db.commit()
	frappe.clear_cache()


def _rename_doctypes() -> None:
	"""Rename DocTypes in the database only — app folders were already renamed in code."""
	pairs = (
		("Container Type", "Cargo Type"),
		("Container Size", "Cargo Size"),
	)
	for old, new in pairs:
		if not frappe.db.exists("DocType", old):
			continue
		if frappe.db.exists("DocType", new):
			_remove_empty_stub_doctype(new, old)
			if frappe.db.exists("DocType", new):
				continue
		_rename_doctype_without_files(old, new)


def _rename_doctype_without_files(old: str, new: str) -> None:
	"""Use rename_doc but skip filesystem moves (source folders already use new names)."""
	frappe.flags.in_patch = True
	try:
		rename_doc("DocType", old, new, force=True, merge=False)
	finally:
		frappe.flags.in_patch = False


def _remove_empty_stub_doctype(stub: str, source: str) -> None:
	"""Drop an empty DocType created by migrate when the legacy DocType still exists."""
	if not frappe.db.exists("DocType", source):
		return
	if frappe.db.count(stub):
		return
	frappe.delete_doc("DocType", stub, force=True, ignore_on_trash=True)
	frappe.db.commit()


def _rename_standard_fields() -> None:
	field_renames = (
		("Cargo Type", "container_type", "cargo_type"),
		("Cargo Size", "container_size", "cargo_size"),
		("Bill of Lading", "container_type", "cargo_type"),
		("Booking Confirmation", "requested_container_type", "requested_cargo_type"),
		("Requested Containers", "container_size", "cargo_size"),
		("Container", "type_of_container", "cargo_size"),
		("Container Tracker", "type_of_container", "cargo_size"),
		("Shipping Line Demurrage Tier", "container_type", "cargo_type"),
		("Shipping Line Detention Tier", "container_type", "cargo_type"),
		("Container Allocation Item", "type_of_container", "cargo_type"),
		("Task Container Update", "type_of_container", "cargo_type"),
	)
	for doctype, old_field, new_field in field_renames:
		_rename_field_if_needed(doctype, old_field, new_field)


def _rename_custom_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import rename_fieldname

	custom_renames = (
		("Opportunity", "custom_container_type_", "custom_cargo_type_"),
		("Opportunity", "custom_container_type", "custom_cargo_type"),
		("Project", "custom_container_type", "custom_cargo_type"),
		("Task", "custom_type_of_container", "custom_cargo_type"),
	)
	for doctype, old_field, new_field in custom_renames:
		cf_name = f"{doctype}-{old_field}"
		if not frappe.db.exists("Custom Field", cf_name):
			continue
		if frappe.db.exists("Custom Field", f"{doctype}-{new_field}"):
			continue
		rename_fieldname(cf_name, new_field)


def _rename_field_if_needed(doctype: str, old_field: str, new_field: str) -> None:
	if not frappe.db.exists("DocType", doctype):
		return
	meta = frappe.get_meta(doctype, cached=False)
	if not meta.has_field(new_field):
		return
	if meta.issingle:
		has_old = True
	else:
		has_old = frappe.db.has_column(doctype, old_field)
	if not has_old:
		return
	try:
		if meta.has_field(old_field) and not meta.issingle:
			rename_field(doctype, old_field, new_field, validate=True)
			return
		# JSON sync dropped old DocField but the legacy DB column may still hold data.
		rename_field(doctype, old_field, new_field, validate=False)
	except Exception:
		frappe.log_error(
			title=f"Cargo terminology rename: {doctype}.{old_field}",
			message=frappe.get_traceback(),
		)
