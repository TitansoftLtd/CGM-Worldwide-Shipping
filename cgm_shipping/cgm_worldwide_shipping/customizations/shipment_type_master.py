"""Backward-compatible re-exports - prefer shipment_type.service and shipment_type_seed_data."""
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_type.service import (
	cgm_ref_prefix_from_master,
	get_allowed_shipment_types,
	get_shipment_type_record,
	is_sea_import_enabled,
	mode_from_master,
	requires_air_waybill,
	requires_bill_of_lading,
	sea_import_enabled_for_project,
	validate_shipment_type_exists,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_type_seed_data import (
	SHIPMENT_TYPE_BOOTSTRAP_DATA,
	bootstrap_shipment_types,
)

# Deprecated aliases - bootstrap only; do not import at runtime.
DEFAULT_SHIPMENT_TYPES = SHIPMENT_TYPE_BOOTSTRAP_DATA
seed_shipment_types = bootstrap_shipment_types
