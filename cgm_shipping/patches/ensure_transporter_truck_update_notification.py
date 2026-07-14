"""Legacy patch — operational updates now use CGM Operational Update on Update."""

from __future__ import annotations

from cgm_shipping.patches.ensure_operational_update_notification import execute as ensure_operational


def execute() -> None:
	ensure_operational()
