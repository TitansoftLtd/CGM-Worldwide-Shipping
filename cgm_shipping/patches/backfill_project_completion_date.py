"""Stamp the completion date on shipments that were already finished.

Why: `custom_completion_date` is written from now on by
`customizations.project_completion`, but every shipment completed before that has
it empty. Left empty, a report of "shipments completed in September" would show
nothing for any month before this deploy, which reads as though no work was done.

What: for each project whose shipment status is already a finished one, fills the
date with the day its last task was completed, falling back to the project's own
modified date rather than today, since today would claim every historical shipment
finished on the day of the deploy.

Touches nothing that already carries a date, and nothing that is not finished.
Idempotent. Retire per docs/guides/patches.md once staging and production Patch Log
show it.
"""

import frappe
from frappe.modules.utils import sync_customizations
from frappe.utils import getdate

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	COMPLETED_SHIPMENT_STATUSES,
)

FIELD = "custom_completion_date"


def execute() -> None:
	# sync_customizations runs after post_model_sync patches, so the field this fills
	# is not on the table yet on the deploy that introduces it.
	sync_customizations("cgm_shipping")
	frappe.clear_cache(doctype="Project")

	if not frappe.get_meta("Project").has_field(FIELD):
		return

	projects = frappe.get_all(
		"Project",
		filters={
			"custom_shipment_status": ["in", sorted(COMPLETED_SHIPMENT_STATUSES)],
			FIELD: ["is", "not set"],
		},
		fields=["name", "modified"],
	)
	if not projects:
		return

	for project in projects:
		frappe.db.set_value(
			"Project",
			project.name,
			FIELD,
			_completion_date(project.name, project.modified),
			update_modified=False,
		)

	frappe.db.commit()


def _completion_date(project: str, fallback) -> str:
	latest = frappe.db.sql(
		"""
		SELECT MAX(completed_on)
		FROM `tabTask`
		WHERE project = %s AND status = 'Completed' AND completed_on IS NOT NULL
		""",
		project,
	)
	value = latest[0][0] if latest and latest[0] else None
	return str(getdate(value or fallback))
