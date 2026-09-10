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

	# Container status table - one source for colours, pills and return tracking
	# on both sides. Plain constants, so it cannot fail at boot.
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		container_status_boot,
	)

	bootinfo["cgm_container_statuses"] = container_status_boot()
