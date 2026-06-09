"""Remove legacy Shipment Dossier DocType and Shipment Clearance Workflow."""
from __future__ import annotations

import frappe

WORKFLOW_NAME = "Shipment Clearance Workflow"
DOCTYPE = "Shipment Dossier"


def execute():
	_deactivate_and_delete_workflow()
	_delete_dossier_documents()
	_delete_doctype()
	frappe.db.commit()
	frappe.clear_cache()


def _deactivate_and_delete_workflow() -> None:
	if not frappe.db.exists("Workflow", WORKFLOW_NAME):
		return
	frappe.delete_doc("Workflow", WORKFLOW_NAME, force=1, ignore_permissions=True)


def _delete_dossier_documents() -> None:
	if not frappe.db.table_exists(f"tab{DOCTYPE}"):
		return
	for name in frappe.get_all(DOCTYPE, pluck="name"):
		frappe.delete_doc(DOCTYPE, name, force=1, ignore_permissions=True)


def _delete_doctype() -> None:
	if not frappe.db.exists("DocType", DOCTYPE):
		return
	frappe.delete_doc("DocType", DOCTYPE, force=1, ignore_permissions=True)
