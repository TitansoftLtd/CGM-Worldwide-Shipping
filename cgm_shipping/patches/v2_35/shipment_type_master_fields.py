"""Add Shipment Type master fields, seed rows, and align CRM/Project Select options."""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_type_master import (
	seed_shipment_types,
)
from cgm_shipping.patches.v2_16.migrate_legacy_shipment_type_import import execute as migrate_legacy_shipment_types

# Operational values returned by normalize_shipment_classification / Shipment Type master.
OPERATIONAL_SHIPMENT_TYPE_OPTIONS = (
	"\nAir Import\nSea FCL\nSea LCL\nCross-Border Road Import\n"
	"Motor Vehicle Import\nExport\nTransit"
)


def execute():
	frappe.reload_doc("CGM Worldwide Shipping", "DocType", "Shipment Type")
	seed_shipment_types()
	_update_shipment_type_select_options()
	migrate_legacy_shipment_types()
	frappe.clear_cache(doctype="Shipment Type")
	for dt in ("Project", "Lead", "Opportunity"):
		frappe.clear_cache(doctype=dt)


def _update_shipment_type_select_options():
	for dt in ("Project", "Lead", "Opportunity"):
		cf_name = f"{dt}-custom_shipment_type"
		if frappe.db.exists("Custom Field", cf_name):
			frappe.db.set_value(
				"Custom Field",
				cf_name,
				"options",
				OPERATIONAL_SHIPMENT_TYPE_OPTIONS,
				update_modified=False,
			)
