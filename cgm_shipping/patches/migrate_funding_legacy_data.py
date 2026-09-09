"""One-time funding legacy data and grid property-setter cleanup."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	MATERIAL_REQUEST_TYPE_OPERATIONAL,
	MR_WORKFLOW_STATE_APPROVED,
	MR_WORKFLOW_STATE_CANCELLED,
	MR_WORKFLOW_STATE_DRAFT,
	MR_WORKFLOW_STATE_FIELD,
	MR_WORKFLOW_STATE_SUBMITTED,
	MR_WORKFLOW_STATE_UNFUNDED,
)


def _migrate_legacy_material_request_purpose_to_description() -> None:
	if not frappe.db.has_column("Material Request", "custom_purpose"):
		return
	if not frappe.db.has_column("Material Request", "custom_request_description"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabMaterial Request`
		SET custom_request_description = custom_purpose
		WHERE IFNULL(custom_request_description, '') = ''
		  AND IFNULL(custom_purpose, '') != ''
		"""
	)


def _backfill_material_request_funding_workflow_states() -> None:
	"""Copy legacy custom_funding_status onto workflow_state; fill missing states."""
	field = MR_WORKFLOW_STATE_FIELD
	if not frappe.db.has_column("Material Request", field):
		return
	if frappe.db.has_column("Material Request", "custom_funding_status"):
		frappe.db.sql(
			f"""
			UPDATE `tabMaterial Request`
			SET `{field}` = custom_funding_status
			WHERE IFNULL(`{field}`, '') = ''
			  AND IFNULL(custom_funding_status, '') != ''
			"""
		)
	frappe.db.sql(
		f"""
		UPDATE `tabMaterial Request`
		SET `{field}` = %(draft)s
		WHERE docstatus = 0
		  AND IFNULL(`{field}`, '') IN ('', %(unfunded)s)
		""",
		{"draft": MR_WORKFLOW_STATE_DRAFT, "unfunded": MR_WORKFLOW_STATE_UNFUNDED},
	)
	frappe.db.sql(
		f"""
		UPDATE `tabMaterial Request`
		SET `{field}` = %(submitted)s
		WHERE docstatus = 1
		  AND IFNULL(custom_funding_request, '') = ''
		  AND IFNULL(material_request_type, '') != %(oe)s
		  AND IFNULL(`{field}`, '') IN ('', %(unfunded)s)
		""",
		{
			"submitted": MR_WORKFLOW_STATE_SUBMITTED,
			"oe": MATERIAL_REQUEST_TYPE_OPERATIONAL,
			"unfunded": MR_WORKFLOW_STATE_UNFUNDED,
		},
	)
	frappe.db.sql(
		f"""
		UPDATE `tabMaterial Request`
		SET `{field}` = %(unfunded)s
		WHERE docstatus = 1
		  AND IFNULL(custom_funding_request, '') = ''
		  AND material_request_type = %(oe)s
		  AND IFNULL(`{field}`, '') = ''
		""",
		{"unfunded": MR_WORKFLOW_STATE_UNFUNDED, "oe": MATERIAL_REQUEST_TYPE_OPERATIONAL},
	)
	frappe.db.sql(
		f"""
		UPDATE `tabMaterial Request`
		SET `{field}` = %(cancelled)s
		WHERE docstatus = 2
		  AND IFNULL(`{field}`, '') IN ('', %(unfunded)s, %(draft)s)
		""",
		{
			"cancelled": MR_WORKFLOW_STATE_CANCELLED,
			"unfunded": MR_WORKFLOW_STATE_UNFUNDED,
			"draft": MR_WORKFLOW_STATE_DRAFT,
		},
	)
	if frappe.db.exists("DocType", "Funding Request Material Request"):
		frappe.db.sql(
			"""
			UPDATE `tabFunding Request Material Request`
			SET status = %(approved)s
			WHERE status = 'Reduced'
			""",
			{"approved": MR_WORKFLOW_STATE_APPROVED},
		)


def _backfill_purchase_order_funding_request_link() -> None:
	if not frappe.db.has_column("Purchase Order", "custom_funding_request"):
		return
	if not frappe.db.has_column("Material Request", "custom_funding_request"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabPurchase Order` po
		INNER JOIN `tabPurchase Order Item` poi ON poi.parent = po.name
		INNER JOIN `tabMaterial Request` mr ON mr.name = poi.material_request
		SET po.custom_funding_request = mr.custom_funding_request
		WHERE IFNULL(po.custom_funding_request, '') = ''
		  AND IFNULL(mr.custom_funding_request, '') != ''
		"""
	)


def _cleanup_material_request_item_grid_property_setters() -> None:
	"""Operational Expense grid layout is JS-only."""
	grid_fields = (
		"schedule_date",
		"warehouse",
		"from_warehouse",
		"description",
		"expense_account",
		"item_code",
	)
	for fieldname in grid_fields:
		for prop in ("in_list_view", "hidden", "columns"):
			name = f"Material Request Item-{fieldname}-{prop}"
			if frappe.db.exists("Property Setter", name):
				frappe.delete_doc("Property Setter", name, force=1)
	frappe.clear_cache(doctype="Material Request Item")


def execute() -> None:
	_migrate_legacy_material_request_purpose_to_description()
	_backfill_material_request_funding_workflow_states()
	_backfill_purchase_order_funding_request_link()
	_cleanup_material_request_item_grid_property_setters()
	frappe.db.commit()
