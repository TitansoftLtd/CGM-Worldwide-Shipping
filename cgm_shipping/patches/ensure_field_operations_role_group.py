"""Ensure Field Operations has its own Settings role list and CGM Role Group."""

from __future__ import annotations


def execute():
	import frappe

	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		migrate_field_operations_role_group,
	)

	if not frappe.db.exists("DocType", "CGM Role Group"):
		return
	migrate_field_operations_role_group()
