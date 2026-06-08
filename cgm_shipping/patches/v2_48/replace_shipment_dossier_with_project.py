"""Remove Shipment Dossier artifacts and replace navigation with Project."""

from __future__ import annotations

import os

import frappe
from frappe.modules.import_file import import_file_by_path

DOCTYPE = "Shipment Dossier"
WORKFLOW_NAME = "Shipment Clearance Workflow"
PAGE_NAMES = ("Shipment Dossier", "shipment-dossier")
ROUTE_SLUG = "shipment-dossier"


def execute():
	_purge_shipment_dossier_doctype_and_workflow()
	_replace_dossier_navigation_with_project()
	_purge_dossier_metadata()
	_purge_dossier_route_history()
	_force_import_navigation_json()
	frappe.db.commit()
	frappe.clear_cache()


def _purge_shipment_dossier_doctype_and_workflow() -> None:
	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		frappe.delete_doc("Workflow", WORKFLOW_NAME, force=1, ignore_permissions=True)

	if frappe.db.table_exists(f"tab{DOCTYPE}"):
		for name in frappe.get_all(DOCTYPE, pluck="name"):
			frappe.delete_doc(DOCTYPE, name, force=1, ignore_permissions=True)

	if frappe.db.exists("DocType", DOCTYPE):
		frappe.delete_doc("DocType", DOCTYPE, force=1, ignore_permissions=True)

	for page_name in PAGE_NAMES:
		if frappe.db.exists("Page", page_name):
			frappe.delete_doc("Page", page_name, force=1, ignore_permissions=True)


def _replace_dossier_navigation_with_project() -> None:
	for ws_name in frappe.get_all("Workspace", pluck="name"):
		ws = frappe.get_doc("Workspace", ws_name)
		changed = _replace_dossier_rows(ws.links, ws.shortcuts)
		if ws.content and DOCTYPE in ws.content:
			ws.content = ws.content.replace(DOCTYPE, "Project")
			changed = True
		if changed:
			ws.save(ignore_permissions=True)

	for sidebar_name in frappe.get_all("Workspace Sidebar", pluck="name"):
		sidebar = frappe.get_doc("Workspace Sidebar", sidebar_name)
		changed = False
		for item in sidebar.items:
			if item.link_to == DOCTYPE:
				item.label = "Project"
				item.link_to = "Project"
				item.link_type = "DocType"
				item.type = "Link"
				changed = True
		if changed:
			sidebar.save(ignore_permissions=True)

	for icon_name in frappe.get_all("Desktop Icon", filters={"link_to": DOCTYPE}, pluck="name"):
		icon = frappe.get_doc("Desktop Icon", icon_name)
		icon.link_to = "Project"
		icon.link_type = "DocType"
		icon.save(ignore_permissions=True)


def _replace_dossier_rows(links, shortcuts) -> bool:
	changed = False
	for row in links:
		if row.link_to == DOCTYPE:
			row.label = "Project"
			row.link_to = "Project"
			row.link_type = "DocType"
			changed = True
	for row in shortcuts:
		if row.link_to == DOCTYPE:
			row.label = "Project"
			row.link_to = "Project"
			row.type = "DocType"
			changed = True
	return changed


def _purge_dossier_metadata() -> None:
	for name in frappe.get_all("Property Setter", filters={"doc_type": DOCTYPE}, pluck="name"):
		frappe.delete_doc("Property Setter", name, force=1, ignore_permissions=True)

	for name in frappe.get_all("Custom Field", filters={"dt": DOCTYPE}, pluck="name"):
		frappe.delete_doc("Custom Field", name, force=1, ignore_permissions=True)

	for name in frappe.get_all("Custom Field", filters={"options": DOCTYPE}, pluck="name"):
		frappe.delete_doc("Custom Field", name, force=1, ignore_permissions=True)

	for name in frappe.get_all("Client Script", filters={"dt": DOCTYPE}, pluck="name"):
		frappe.delete_doc("Client Script", name, force=1, ignore_permissions=True)

	for doctype, field in (
		("Notification", "document_type"),
		("Assignment Rule", "document_type"),
		("Form Tour", "reference_doctype"),
		("Print Format", "doc_type"),
		("Web Form", "doc_type"),
	):
		if not frappe.db.exists("DocType", doctype):
			continue
		for name in frappe.get_all(doctype, filters={field: DOCTYPE}, pluck="name"):
			frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)

	if frappe.db.exists("List View Settings", DOCTYPE):
		frappe.delete_doc("List View Settings", DOCTYPE, force=1, ignore_permissions=True)

	for name in frappe.get_all("Report", filters={"ref_doctype": DOCTYPE}, pluck="name"):
		frappe.delete_doc("Report", name, force=1, ignore_permissions=True)


def _purge_dossier_route_history() -> None:
	frappe.db.delete("Route History", {"route": ["like", f"%{ROUTE_SLUG}%"]})
	frappe.db.delete("DefaultValue", {"defvalue": ["like", f"%{ROUTE_SLUG}%"]})
	frappe.db.delete("DefaultValue", {"defvalue": ["like", f"%{DOCTYPE}%"]})


def _force_import_navigation_json() -> None:
	app_path = frappe.get_app_path("cgm_shipping")
	paths = (
		os.path.join(
			app_path,
			"cgm_worldwide_shipping",
			"workspace",
			"cgm_worldwide_shipping",
			"cgm_worldwide_shipping.json",
		),
		os.path.join(app_path, "workspace_sidebar", "cgm_shipping.json"),
		os.path.join(app_path, "desktop_icon", "cgm_shipping.json"),
	)
	for path in paths:
		import_file_by_path(path, force=True, ignore_version=True)
