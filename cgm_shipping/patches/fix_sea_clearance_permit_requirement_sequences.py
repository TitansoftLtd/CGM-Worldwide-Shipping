"""Align sea clearance requirement sequences so Task Permits shows on seq 15.

Some sites drifted so Post-clearance Permit Application was on seq 16 (Finance)
instead of seq 15 (Prepare Post-Clearance Permits). That made the application
task show only Task Documents.
"""

from __future__ import annotations

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	ensure_sea_clearance_task_requirements,
)


def execute() -> None:
	ensure_sea_clearance_task_requirements()
