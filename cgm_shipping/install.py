"""App install / migrate hooks for cgm_shipping."""

from __future__ import annotations

import frappe


def before_migrate() -> None:
	"""Rename legacy container DocTypes before schema sync."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.cargo_terminology import (
		ensure_cargo_doctype_renames_before_migrate,
	)

	ensure_cargo_doctype_renames_before_migrate()


def after_install() -> None:
	"""Seed default masters and CGM Shipping Settings on a fresh site."""
	from cgm_shipping.default_seed_data import seed_all_defaults

	seed_all_defaults()


def after_migrate() -> None:
	"""Re-apply idempotent schema installers after every bench migrate."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.cargo_terminology import (
		ensure_cargo_terminology_renames,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		check_project_layout_export_drift,
	)

	missing_layout_fields = check_project_layout_export_drift()
	if missing_layout_fields:
		frappe.log_error(
			title="CGM Project layout not exported",
			message=(
				"The following Project custom fields are missing from "
				"Project-main-field_order and will not appear on forms after migrate:\n"
				+ "\n".join(f"- {fn}" for fn in missing_layout_fields)
				+ "\n\nExport Customize Form to custom/project.json "
				"(bench execute cgm_shipping.install.export_cgm_customizations)."
			),
		)

	for label, fn in (
		("cargo terminology renames", ensure_cargo_terminology_renames),
		("supplier shipping line schema", reinstall_supplier_shipping_line_schema),
		("task container schema", ensure_task_container_schema),
		("shipment type transport defaults", ensure_shipment_type_transport_defaults),
		("shipment document versioning", ensure_shipment_document_versioning),
		("finance cost ledger schema", ensure_finance_cost_ledger_schema),
		("transporter portal setup", ensure_transporter_portal_setup),
		("task workflow masters", ensure_task_workflow_masters),
	):
		try:
			fn()
		except Exception:
			frappe.log_error(
				title=f"CGM after_migrate: {label}",
				message=frappe.get_traceback(),
			)


def ensure_task_workflow_masters() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.clearance_charge_item import (
		repair_clearance_charge_item_setup,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		ensure_transit_project_fields,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		ensure_task_behaviour_fields,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		seed_task_workflow_masters,
	)
	from cgm_shipping.default_seed_data import seed_cgm_shipping_settings

	if frappe.db.exists("DocType", "Project"):
		ensure_transit_project_fields()
	if frappe.db.exists("DocType", "Task"):
		ensure_task_behaviour_fields()
	seed_task_workflow_masters()
	seed_cgm_shipping_settings()
	repair_clearance_charge_item_setup()
	frappe.db.commit()


def ensure_transporter_portal_setup() -> None:
	"""Role, portal menu, and portal user accounts for transporter suppliers."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share import (
		ensure_transporter_invoice_share_fields,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_supplier import (
		sync_all_transporter_portal_users,
	)

	if frappe.db.exists("DocType", "Purchase Invoice"):
		ensure_transporter_invoice_share_fields()
	sync_all_transporter_portal_users()


def ensure_transporter_role() -> None:
	"""Backward-compatible entry point for bench execute."""
	ensure_transporter_portal_setup()


def ensure_finance_cost_ledger_schema() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		ensure_project_finance_cost_fields,
	)

	if frappe.db.exists("DocType", "Project"):
		ensure_project_finance_cost_fields()
	frappe.db.commit()


def ensure_shipment_document_versioning() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		ensure_shipment_document_version_fields,
		migrate_initial_attachment_to_draft_documents,
		migrate_legacy_shipment_document_attachments,
		remove_initial_attachment_field,
	)

	if not frappe.db.exists("DocType", "Shipment Document"):
		return
	migrate_initial_attachment_to_draft_documents()
	remove_initial_attachment_field()
	ensure_shipment_document_version_fields()
	migrate_legacy_shipment_document_attachments()
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		hide_computed_shipment_document_columns,
	)

	hide_computed_shipment_document_columns()
	frappe.db.commit()


def ensure_shipment_type_transport_defaults() -> None:
	"""Seed Shipment Type.transport_documents when empty (derived from master flags)."""
	from cgm_shipping.cgm_worldwide_shipping.services.shipment_type_service import (
		ensure_shipment_type_transport_document_defaults,
	)

	ensure_shipment_type_transport_document_defaults()
	frappe.db.commit()


def ensure_task_container_schema() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		ensure_shipment_document_version_fields,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		ensure_client_inspection_task_fields,
		ensure_client_paid_task_fields,
		ensure_container_tracking_settings_fields,
		ensure_field_officer_task_fields,
		ensure_project_inspection_notification_fields,
		ensure_project_port_arrival_fields,
		ensure_task_container_update_fields,
	)

	ensure_shipment_document_version_fields()

	if frappe.db.exists("DocType", "Task Container Update"):
		ensure_container_tracking_settings_fields()
		ensure_task_container_update_fields()
	if frappe.db.exists("DocType", "Task"):
		ensure_field_officer_task_fields()
		ensure_client_inspection_task_fields()
		ensure_client_paid_task_fields()
		frappe.db.commit()
	if frappe.db.exists("DocType", "Project"):
		ensure_project_inspection_notification_fields()
		ensure_project_port_arrival_fields()
		frappe.db.commit()


def reinstall_supplier_shipping_line_schema() -> None:
	"""Create/update Supplier Table fields for shipping line child doctypes."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		ensure_supplier_container_charge_fields,
	)

	for doctype in (
		"Shipping Line Free Days Rule",
		"Shipping Line Demurrage Tier",
	):
		if not frappe.db.exists("DocType", doctype):
			frappe.throw(
				f"{doctype} is missing. Run: bench --site <site> migrate"
			)

	ensure_supplier_container_charge_fields()
	frappe.db.commit()


def export_cgm_customizations(module: str = "CGM Worldwide Shipping") -> None:
	"""Write desk customizations (field order, labels) into custom/*.json for git.

	Run after saving Customize Form so production ``bench migrate`` matches dev::

	    bench --site <site> execute cgm_shipping.install.export_cgm_customizations
	"""
	from frappe.modules.utils import export_customizations

	export_customizations(module=module, sync_on_migrate=1)
	frappe.db.commit()
	print(f"Exported customizations for module: {module}")


def run() -> None:
	"""bench execute cgm_shipping.install.run"""
	reinstall_supplier_shipping_line_schema()
	ensure_transporter_portal_setup()
	meta = frappe.get_meta("Supplier")
	for field in (
		"custom_shipping_line_free_days_rules",
		"custom_shipping_line_demurrage_tiers",
	):
		print(field, ":", meta.has_field(field))
