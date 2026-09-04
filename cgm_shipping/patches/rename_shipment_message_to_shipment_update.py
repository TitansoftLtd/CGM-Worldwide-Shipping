"""Rename `Shipment Message` to `Shipment Update`.

The DocType was renamed from `Update` to `Shipment Message` earlier the same
day (see `rename_update_to_shipment_message`); `Shipment Update` is the name
that stuck. Sites that never saw the intermediate name skip this - the
previous patch leaves them on `Shipment Message` for a moment and this one
carries them the rest of the way in the same migrate.

Runs in `pre_model_sync` for the same reason as the first rename: the table
has to move before `shipment_update.json` syncs, or the new DocType would get
an empty table beside the populated one.
"""

from __future__ import annotations

import frappe

OLD = "Shipment Message"
NEW = "Shipment Update"


def execute() -> None:
	old_exists = bool(frappe.db.exists("DocType", OLD))
	new_exists = bool(frappe.db.exists("DocType", NEW))

	if not old_exists and not new_exists:
		return

	if old_exists and not new_exists:
		from frappe.model.rename_doc import rename_doc

		frappe.flags.ignore_route_conflict_validation = True
		rename_doc("DocType", OLD, NEW, force=True, ignore_permissions=True, show_alert=False, rebuild_search=False)

	# Always run: renaming a DocType is DDL, so a run that failed part-way
	# through leaves the table renamed but these references stale.
	_repoint_plain_references()

	frappe.clear_cache()
	frappe.db.commit()


def _repoint_plain_references() -> None:
	"""Update rows that store the DocType name as data, not as a Link."""
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
