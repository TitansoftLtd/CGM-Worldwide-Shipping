"""App install / migrate hooks for cgm_shipping."""

from __future__ import annotations

import frappe


def after_migrate() -> None:
	"""Re-apply idempotent schema installers after every bench migrate."""
	reinstall_supplier_shipping_line_schema()
	ensure_task_container_schema()
	ensure_shipment_document_versioning()
	ensure_finance_cost_ledger_schema()
	ensure_transporter_portal_setup()


def ensure_transporter_portal_setup() -> None:
	"""Role, portal menu, and portal user accounts for transporter suppliers."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_supplier import (
		sync_all_transporter_portal_users,
	)

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
		migrate_legacy_shipment_document_attachments,
	)

	if not frappe.db.exists("DocType", "Shipment Document"):
		return
	ensure_shipment_document_version_fields()
	migrate_legacy_shipment_document_attachments()
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		hide_computed_shipment_document_columns,
	)

	hide_computed_shipment_document_columns()
	frappe.db.commit()


def ensure_task_container_schema() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		ensure_shipment_document_version_fields,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		ensure_client_inspection_task_fields,
		ensure_field_officer_task_fields,
		ensure_project_inspection_notification_fields,
		ensure_project_port_arrival_fields,
		ensure_task_container_update_fields,
	)

	ensure_shipment_document_version_fields()

	if frappe.db.exists("DocType", "Task Container Update"):
		ensure_task_container_update_fields()
	if frappe.db.exists("DocType", "Task"):
		ensure_field_officer_task_fields()
		ensure_client_inspection_task_fields()
		frappe.db.commit()
	if frappe.db.exists("DocType", "Project"):
		ensure_project_inspection_notification_fields()
		ensure_project_port_arrival_fields()
		from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
			ensure_opportunity_universal_fields,
			ensure_transit_project_fields,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_intake_wizard import (
			ensure_opportunity_intake_wizard_layout,
		)

		ensure_opportunity_universal_fields()
		ensure_opportunity_intake_wizard_layout()
		ensure_transit_project_fields()
		frappe.db.commit()


def reinstall_supplier_shipping_line_schema() -> None:
	"""Create/update Supplier Table fields for shipping line child doctypes."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		ensure_supplier_container_charge_fields,
	)

	for doctype in (
		"Shipping Line Free Days Rule",
		"Shipping Line Demurrage Tier",
		"Shipping Line Detention Tier",
	):
		if not frappe.db.exists("DocType", doctype):
			frappe.throw(
				f"{doctype} is missing. Run: bench --site <site> migrate"
			)

	ensure_supplier_container_charge_fields()
	frappe.db.commit()


def run() -> None:
	"""bench execute cgm_shipping.install.run"""
	reinstall_supplier_shipping_line_schema()
	ensure_transporter_portal_setup()
	meta = frappe.get_meta("Supplier")
	for field in (
		"custom_shipping_line_free_days_rules",
		"custom_shipping_line_demurrage_tiers",
		"custom_shipping_line_detention_tiers",
	):
		print(field, ":", meta.has_field(field))
