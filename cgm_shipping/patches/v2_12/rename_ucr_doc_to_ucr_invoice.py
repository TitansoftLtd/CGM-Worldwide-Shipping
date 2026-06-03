"""Rename misleading UCR_DOC document type to UCR Invoice."""
from __future__ import annotations

import frappe

TARGET_CODE = "UCR Invoice"
LEGACY_NAMES = ("UCR_DOC", "UCR_INV")


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
		ensure_task_document_types,
	)

	ensure_task_document_types()
	target_name = frappe.db.get_value("Document Type", {"code": TARGET_CODE}, "name") or TARGET_CODE

	for legacy in LEGACY_NAMES:
		if legacy == target_name or not frappe.db.exists("Document Type", legacy):
			continue
		_migrate_legacy_document_type(legacy, target_name)

	_update_shipment_document_links(target_name)
	frappe.clear_cache(doctype="Document Type")
	frappe.db.commit()


def _migrate_legacy_document_type(legacy_name: str, target_name: str) -> None:
	"""Point child-table links at UCR Invoice and remove old Document Type rows."""
	frappe.db.sql(
		"""
		UPDATE `tabShipment Document`
		SET document_type = %s
		WHERE document_type = %s
		""",
		(target_name, legacy_name),
	)
	legacy = frappe.get_doc("Document Type", legacy_name)
	if legacy.docstatus == 1:
		legacy.cancel()
	if legacy.docstatus == 1:
		return
	frappe.delete_doc("Document Type", legacy_name, force=1, ignore_permissions=True)


def _update_shipment_document_links(target_name: str) -> None:
	"""Re-link rows that still reference legacy codes by code lookup."""
	for legacy_code in LEGACY_NAMES:
		legacy_name = frappe.db.get_value("Document Type", {"code": legacy_code}, "name")
		if legacy_name and legacy_name != target_name:
			frappe.db.sql(
				"""
				UPDATE `tabShipment Document`
				SET document_type = %s
				WHERE document_type = %s
				""",
				(target_name, legacy_name),
			)
