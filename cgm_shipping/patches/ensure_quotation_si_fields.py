"""Ensure Quotation and Sales Invoice custom fields for billing workflow."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _upsert_cf

MODULE = "CGM Worldwide Shipping"


def execute() -> None:
	_ensure_quotation_reference_fields()
	frappe.db.commit()


def _ensure_quotation_reference_fields() -> None:
	_upsert_cf(
		"Quotation",
		{
			"fieldname": "custom_section_shipment_refs",
			"label": "Shipment References",
			"fieldtype": "Section Break",
			"insert_after": "opportunity",
			"collapsible": 1,
		},
	)
	_upsert_cf(
		"Quotation",
		{
			"fieldname": "custom_shipment",
			"label": "Shipment",
			"fieldtype": "Link",
			"options": "Project",
			"insert_after": "custom_section_shipment_refs",
		},
	)
	_upsert_cf(
		"Quotation",
		{
			"fieldname": "custom_coo",
			"label": "Country of Origin",
			"fieldtype": "Data",
			"insert_after": "custom_shipment",
			"fetch_from": "opportunity.custom_country_of_origin",
			"fetch_if_empty": 1,
		},
	)
	_upsert_cf(
		"Quotation",
		{
			"fieldname": "custom_idfno",
			"label": "IDF No",
			"fieldtype": "Data",
			"insert_after": "custom_coo",
			"fetch_from": "custom_shipment.custom_idf_number",
			"fetch_if_empty": 1,
		},
	)
	_upsert_cf(
		"Quotation",
		{
			"fieldname": "custom_client_ref_no",
			"label": "Client Ref No",
			"fieldtype": "Data",
			"insert_after": "custom_idfno",
			"fetch_from": "custom_shipment.custom_client_ref_no",
			"fetch_if_empty": 1,
		},
	)
	_upsert_cf(
		"Quotation",
		{
			"fieldname": "custom_our_ref_no",
			"label": "Our Ref No",
			"fieldtype": "Data",
			"insert_after": "custom_client_ref_no",
			"fetch_from": "custom_shipment.custom_cgm_ref_no",
			"fetch_if_empty": 1,
		},
	)
	_upsert_cf(
		"Quotation",
		{
			"fieldname": "custom_freight_approved_by",
			"label": "Finance Approved By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "custom_our_ref_no",
			"read_only": 1,
			"allow_on_submit": 1,
		},
	)
