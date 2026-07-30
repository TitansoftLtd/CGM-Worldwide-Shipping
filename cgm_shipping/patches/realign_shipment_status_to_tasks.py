"""Pull Project shipment status back when it is ahead of completed clearance tasks.

Server projects sometimes show Post-clearance (or later) while Task 7 is still open,
because status sync previously only advanced and never rewound.
"""

from __future__ import annotations

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		sync_project_shipment_status_from_tasks,
	)

	projects = frappe.get_all(
		"Project",
		filters={"custom_mode_of_transport": "Sea"},
		pluck="name",
	)
	for name in projects:
		try:
			sync_project_shipment_status_from_tasks(name)
		except Exception:
			frappe.log_error(
				title=f"CGM: failed to realign shipment status for {name}",
			)
