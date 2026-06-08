"""Bootstrap Shipment Type master rows (fill missing only; never overwrite Desk edits)."""
import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_type_seed_data import (
	bootstrap_shipment_types,
)


def execute():
	bootstrap_shipment_types(only_fill_empty_fields=True)
	frappe.db.commit()
