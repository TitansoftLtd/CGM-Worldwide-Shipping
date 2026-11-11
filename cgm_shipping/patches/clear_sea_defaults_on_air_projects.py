"""Clear sea defaults stamped on air shipments.

Why: Berth Phase defaults to "Before Vessel Berth", so every air project carried
it. The form now hides the field, but the stored value still reaches reports.

What: on Air projects, clears Berth Phase when it is still the untouched default.
Container Tracker Mode is left: the Shipment Type backfill would restore it.

Idempotent. One-time - retire per docs/guides/patches.md.
"""

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.air_field_visibility import (
		clear_sea_defaults_on_existing_air_projects,
	)

	if not frappe.db.exists("DocType", "Project"):
		return
	touched = clear_sea_defaults_on_existing_air_projects()
	frappe.db.commit()
	print(f"clear_sea_defaults_on_air_projects: tidied {touched} air project(s)")
