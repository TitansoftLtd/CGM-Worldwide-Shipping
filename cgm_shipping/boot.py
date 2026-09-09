# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from cgm_shipping.cgm_worldwide_shipping.customizations.package_field_visibility import (
	get_package_visibility_config,
)


def extend_bootinfo(bootinfo) -> None:
	try:
		bootinfo["cgm_package_visibility"] = get_package_visibility_config()
	except Exception:
		bootinfo["cgm_package_visibility"] = {"modes": [], "cargo_types": []}
