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
	from cgm_shipping.cgm_worldwide_shipping.customizations.license_roles import (
		seed_license_settings,
	)
	from cgm_shipping.default_seed_data import seed_all_defaults

	seed_all_defaults()
	ensure_license_setup()
	# Reminder schedule defaults are fresh-install only, so removing a period on a
	# live site is not undone by the next migrate.
	seed_license_settings()


def after_migrate() -> None:
	"""Re-apply idempotent schema installers after every bench migrate."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.cargo_terminology import (
		ensure_cargo_terminology_renames,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.per_diem import (
		ensure_per_diem_setup,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		check_project_layout_export_drift,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.recruitment import (
		ensure_recruitment_schema,
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
		("customer invoice share fields", ensure_customer_invoice_share_schema),
		("sales invoice approval workflow", ensure_sales_invoice_workflow_setup),
		("funding workflow self-submit", ensure_funding_workflow_self_submit_setup),
		("task workflow masters", ensure_task_workflow_masters),
		("package field visibility", ensure_package_field_visibility),
		("licence register roles", ensure_license_setup),
		("recruitment schema", ensure_recruitment_schema),
		("hrms custom fields", ensure_hrms_custom_fields),
		("job group structure & per diems", ensure_per_diem_setup),
	):
		try:
			fn()
		except Exception:
			frappe.log_error(
				title=f"CGM after_migrate: {label}",
				message=frappe.get_traceback(),
			)


def ensure_hrms_custom_fields() -> None:
	"""Put back any HR custom field HRMS creates only at install time.

	HRMS adds its masters' fields - Company.default_expense_claim_payable_account,
	Department.payroll_cost_center, Designation.skills and the rest - in its
	`after_install`, and never again. Nothing restores them if they are later lost to
	a partial restore or an app reinstall, and the loss is invisible until a form asks
	for one: the desk then fails with *Field not permitted in query*, because the
	column survives in the table while the Custom Field record that describes it does
	not. Opening an Expense Claim hits exactly that, since it reads the Company field.

	Only missing fields are created (`update=False`). Fields already in place keep
	whatever the Customize Form exports in `custom/*.json` set on them - Employee's
	HR fields are exported there and must not be reverted to the HRMS defaults.
	Definitions are read from HRMS itself, so there is nothing here to drift.
	"""
	if "hrms" not in frappe.get_installed_apps():
		return

	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
	from hrms.setup import get_custom_fields

	create_custom_fields(get_custom_fields(), ignore_validate=True, update=False)
	frappe.db.commit()


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


def ensure_package_field_visibility() -> None:
	"""Copy live package-field rules into Settings (if empty) and write depends_on."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.package_field_visibility import (
		apply_package_field_depends_on,
		seed_package_visibility_defaults,
	)

	seed_package_visibility_defaults()
	apply_package_field_depends_on()
def ensure_license_setup() -> None:
	"""Roles the licence & permit register doctypes grant permissions to.

	Licence types and the permit rows themselves are entered by hand or via Data
	Import, which is enabled on both doctypes - nothing seeds them from code.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.license_roles import (
		ensure_license_roles,
	)

	ensure_license_roles()
	frappe.db.commit()


def ensure_customer_invoice_share_schema() -> None:
	"""Share-with-customer fields on Sales Invoice."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.customer_invoice_share import (
		ensure_customer_invoice_share_fields,
	)

	if frappe.db.exists("DocType", "Sales Invoice"):
		ensure_customer_invoice_share_fields()


def ensure_funding_workflow_self_submit_setup() -> None:
	"""Requesters can Submit their own Material Request / Funding Request drafts."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import (
		ensure_funding_workflow_self_submit,
	)

	ensure_funding_workflow_self_submit()


def ensure_sales_invoice_workflow_setup() -> None:
	"""Keep CGM Sales Invoice workflow states/transitions aligned with app code."""
	if not frappe.db.exists("DocType", "Workflow"):
		return
	from cgm_shipping.patches.ensure_sales_invoice_workflow import (
		_ensure_workflow_action_masters,
		_sync_workflow,
	)

	_ensure_workflow_action_masters()
	_sync_workflow()


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


def export_cgm_customizations(
	module: str = "CGM Worldwide Shipping",
	with_permissions: bool = True,
) -> None:
	"""Write desk customizations into custom/*.json for git (applied on migrate).

	Exports Custom Field, Property Setter, and Custom DocPerm for every doctype
	touched in *module*. Run after Customize Form / Role Permission Manager::

	    bench --site <site> execute cgm_shipping.install.export_cgm_customizations

	Workflows, Role Profiles, and User role assignments are **not** included —
	see ``export_cgm_customizations`` docstring in patches.md / admin-setup.
	"""
	from frappe.modules.utils import export_customizations

	doctypes: set[str] = set(
		frappe.get_all("Custom Field", filters={"module": module}, pluck="dt", distinct=True)
	)
	doctypes.update(
		frappe.get_all(
			"Property Setter", filters={"module": module}, pluck="doc_type", distinct=True
		)
	)

	exported: list[str] = []
	for doctype in sorted(doctypes):
		if not doctype:
			continue
		path = export_customizations(
			module=module,
			doctype=doctype,
			sync_on_migrate=1,
			with_permissions=with_permissions,
		)
		if path:
			exported.append(path)

	frappe.db.commit()
	if exported:
		print(f"Exported {len(exported)} customization file(s) for module: {module}")
		for path in exported:
			print(f"  - {path}")
	else:
		print(f"No customizations to export for module: {module}")


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
