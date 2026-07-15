# Copyright (c) 2026, Titansoft Limited and contributors
"""Backward-compatible shim — use operational_updates instead."""

from cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates import (  # noqa: F401
	TRANSPORTER_SUBJECTS as UPDATE_TYPES,
	format_latest_update_summary,
	get_allocation_truck_updates,
	get_latest_updates_for_trackers,
	get_tracker_truck_updates,
	get_updates_for_allocation_item,
	get_updates_for_container_tracker,
	notify_operations as notify_transport_officers,
	post_truck_update,
	serialize_update as serialize_truck_update,
)
