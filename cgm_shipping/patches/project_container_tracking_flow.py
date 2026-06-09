"""Before/after berth Project fields + Container Tracker field expansion."""
import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		ensure_project_container_tracking_fields,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		ensure_project_tracking_layout,
	)

	ensure_project_tracking_layout()
	ensure_project_container_tracking_fields()
	frappe.clear_cache()
