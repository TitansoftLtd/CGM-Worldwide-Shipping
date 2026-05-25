"""Install 24-step Sea Freight Clearance task template (ordered chart)."""
from __future__ import annotations

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
	sync_sea_task_template_to_settings,
)


def execute():
	sync_sea_task_template_to_settings()
