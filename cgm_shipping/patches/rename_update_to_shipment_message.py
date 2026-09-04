"""Rename the `Update` DocType to `Shipment Message`.

"Update" was a bare English word that read as a verb in half the places it
appeared, and the DocType long ago stopped being one-way status posts - it now
carries questions from customers and transporters, CGM's replies, and the
response tracking on each.

This runs in `pre_model_sync`: the rename has to happen while the DB still
holds the old DocType, otherwise the synced `shipment_message.json` would
create an empty table alongside the populated `tabUpdate`.

`frappe.rename_doc` moves the table and rewrites Link values pointing at the
old name. The fix-ups afterwards cover the places that hold the DocType name
as plain data rather than as a Link.
"""

from __future__ import annotations

import frappe

OLD = "Update"
NEW = "Shipment Message"


def execute() -> None:
	old_exists = bool(frappe.db.exists("DocType", OLD))
	new_exists = bool(frappe.db.exists("DocType", NEW))

	if not old_exists and not new_exists:
		return

	if old_exists and not new_exists:
		# frappe.rename_doc (the top-level alias) takes no ignore_permissions;
		# the model function does, and a patch runs as Administrator anyway.
		from frappe.model.rename_doc import rename_doc

		frappe.flags.ignore_route_conflict_validation = True
		rename_doc("DocType", OLD, NEW, force=True, ignore_permissions=True, show_alert=False, rebuild_search=False)

	# Always run: renaming a DocType is DDL, so a run that failed part-way
	# through leaves the table renamed but these references stale.
	_repoint_plain_references()

	frappe.clear_cache()
	frappe.db.commit()


def _repoint_plain_references() -> None:
	"""Update rows that store the DocType name as data, not as a Link.

	Each of these keeps the doctype name in its own column, so
	`rename_doc`'s Link rewriting does not reach them.
	"""
	for doctype, field in (
		("Custom DocPerm", "parent"),
		("Property Setter", "doc_type"),
		("Custom Field", "dt"),
		("DocType Layout", "document_type"),
		("Notification", "document_type"),
		("Workspace Link", "link_to"),
		("Workspace Shortcut", "link_to"),
		("Workspace Sidebar Item", "link_to"),
		("Desktop Icon", "_doctype"),
	):
		if not frappe.db.table_exists(doctype):
			continue
		if field not in frappe.db.get_table_columns(doctype):
			continue
		frappe.db.sql(
			f"UPDATE `tab{doctype}` SET `{field}` = %s WHERE `{field}` = %s", (NEW, OLD)
		)
