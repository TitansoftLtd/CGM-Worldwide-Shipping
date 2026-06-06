"""Install 24-step Sea Freight Clearance task template (ordered chart)."""
from __future__ import annotations

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_template_seed_data import (
	seed_sea_import_task_template_to_settings,
)


def execute():
	seed_sea_import_task_template_to_settings()
