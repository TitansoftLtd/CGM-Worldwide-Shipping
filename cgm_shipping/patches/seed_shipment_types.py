"""Seed Shipment Type master records for CRM and Project links."""
from __future__ import annotations

from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_type_seed_data import (
	bootstrap_shipment_types,
)


def execute():
	bootstrap_shipment_types(only_fill_empty_fields=True)
