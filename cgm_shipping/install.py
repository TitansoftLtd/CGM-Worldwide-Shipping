"""App install / migrate hooks for cgm_shipping."""

from __future__ import annotations

import frappe


def after_migrate() -> None:
	"""Re-apply idempotent schema installers after every bench migrate."""
	reinstall_supplier_shipping_line_schema()
	ensure_task_container_schema()


def ensure_task_container_schema() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		ensure_task_container_update_fields,
	)

	if frappe.db.exists("DocType", "Task Container Update"):
		ensure_task_container_update_fields()
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
	meta = frappe.get_meta("Supplier")
	for field in (
		"custom_shipping_line_free_days_rules",
		"custom_shipping_line_demurrage_tiers",
		"custom_shipping_line_detention_tiers",
	):
		print(field, ":", meta.has_field(field))
