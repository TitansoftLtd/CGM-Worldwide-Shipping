"""Copy live package visibility rules into CGM Shipping Settings and apply them."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.package_field_visibility import (
	apply_package_field_depends_on,
	seed_package_visibility_defaults,
)


def execute():
	seed_package_visibility_defaults()
	apply_package_field_depends_on()
	frappe.clear_cache(doctype="Opportunity")
	frappe.clear_cache(doctype="Project")
