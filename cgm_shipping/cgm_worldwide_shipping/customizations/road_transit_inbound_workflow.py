"""Road Transit Inbound task automation.

Its shipment status gates are on the Road Transit Inbound CGM Task Template
(Shipment Status Gates).
"""

from __future__ import annotations

# Receive shipment documents - auto-complete when CRM CI/PKL already on the Project.
ROAD_TRANSIT_INBOUND_AUTO_COMPLETE_SEQS: frozenset[int] = frozenset({1})


def get_road_transit_inbound_auto_complete_sequences() -> frozenset[int]:
	return ROAD_TRANSIT_INBOUND_AUTO_COMPLETE_SEQS
