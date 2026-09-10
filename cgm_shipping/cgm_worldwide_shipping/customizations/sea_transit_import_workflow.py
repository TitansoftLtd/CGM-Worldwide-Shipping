"""Sea Transit Import task automation.

Its shipment status gates are on the Sea Transit Import CGM Task Template
(Shipment Status Gates).
"""

from __future__ import annotations

# Receive B/L and import documents - auto-complete when CRM CI/PKL already on the Project.
SEA_TRANSIT_IMPORT_AUTO_COMPLETE_SEQS: frozenset[int] = frozenset({1})


def get_sea_transit_import_auto_complete_sequences() -> frozenset[int]:
	return SEA_TRANSIT_IMPORT_AUTO_COMPLETE_SEQS
