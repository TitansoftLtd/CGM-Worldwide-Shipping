"""Map legacy custom_shipment_type Import/Export to operational values (Sea FCL, …)."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	normalize_shipment_classification,
)


def execute():
	legacy_values = ("Import", "Export", "Road Import")
	for doctype in ("Project", "Lead", "Opportunity"):
		meta = frappe.get_meta(doctype)
		if not meta.has_field("custom_shipment_type"):
			continue
		rows = frappe.get_all(
			doctype,
			filters={"custom_shipment_type": ["in", list(legacy_values)]},
			fields=["name", "custom_shipment_type", "custom_mode_of_transport"],
		)
		for row in rows:
			st, mode = normalize_shipment_classification(
				row.custom_shipment_type,
				row.custom_mode_of_transport,
			)
			if not st or st == row.custom_shipment_type:
				continue
			values = {"custom_shipment_type": st}
			if meta.has_field("custom_mode_of_transport") and mode:
				values["custom_mode_of_transport"] = mode
			frappe.db.set_value(doctype, row.name, values, update_modified=False)

	frappe.db.commit()
