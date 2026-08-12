"""Sync Road Transit Inbound Workflow template to Declaration→Finance pairs.

Replaces the collapsed apply+pay plan (and combined Book trucks / C2) with the
current ``road_transit_inbound_tasks`` seed. Idempotent.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
	ROAD_TRANSIT_INBOUND_TEMPLATE,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
	road_transit_inbound_tasks,
)

# Markers of the pre-split template — if any remain, reseed the whole plan.
_LEGACY_SUBJECTS = (
	"IDF application and UCR payment",
	"Apply and pay pre-clearance permits",
	"Book trucks and obtain C2",
	"Taxes paid",
	"Post-clearance permits",
)


def _needs_reseed(rows: list) -> bool:
	subjects = {(row.subject or "").strip() for row in rows}
	if any(s in subjects for s in _LEGACY_SUBJECTS):
		return True
	# Also reseed when expected Finance pays UCR row is missing (partial edits).
	if "Finance pays UCR" not in subjects or "Book trucks" not in subjects or "Obtain C2" not in subjects:
		return True
	return False


def execute() -> None:
	if not frappe.db.exists("DocType", "CGM Task Template"):
		return
	if not frappe.db.exists("CGM Task Template", ROAD_TRANSIT_INBOUND_TEMPLATE):
		return

	doc = frappe.get_doc("CGM Task Template", ROAD_TRANSIT_INBOUND_TEMPLATE)
	rows = list(doc.get("tasks") or [])
	if rows and not _needs_reseed(rows):
		return

	doc.set("tasks", [])
	for task in road_transit_inbound_tasks():
		doc.append("tasks", task)
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
