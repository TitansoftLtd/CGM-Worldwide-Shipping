"""Reseed Sea Transit Import Workflow to the standalone 15-step transit plan.

Replaces the old Sea Import extension (6 tasks chained after seq 25) with the
full transit workflow (B/L, shipping line, entry/taxes, KPA, dispatch). Idempotent.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.clearance_charge_item import (
	ensure_payment_kinds,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
	SEA_IMPORT_TEMPLATE,
	SEA_TRANSIT_IMPORT_TEMPLATE,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
	sea_transit_import_tasks,
)

_LEGACY_SUBJECTS = (
	"Obtain KPA release order",
	"Book trucks with KPA using release order",
)


def _needs_reseed(doc) -> bool:
	if (doc.extends_template or "").strip() == SEA_IMPORT_TEMPLATE:
		return True
	rows = list(doc.get("tasks") or [])
	if len(rows) <= 6:
		return True
	subjects = {(row.subject or "").strip() for row in rows}
	if "Receive B/L and import documents" not in subjects:
		return True
	if "Finance pays transit entry taxes" not in subjects:
		return True
	if any(s in subjects for s in _LEGACY_SUBJECTS) and len(rows) < 10:
		return True
	return False


def execute() -> None:
	if not frappe.db.exists("DocType", "CGM Task Template"):
		return
	if not frappe.db.exists("CGM Task Template", SEA_TRANSIT_IMPORT_TEMPLATE):
		return

	ensure_payment_kinds()

	doc = frappe.get_doc("CGM Task Template", SEA_TRANSIT_IMPORT_TEMPLATE)
	if doc.get("tasks") and not _needs_reseed(doc):
		return

	doc.description = (
		"Sea transit import: B/L and shipping line charges, transit-country entry "
		"and taxes, KPA release, then truck dispatch to border/warehouse."
	)
	doc.extends_template = None
	doc.set("tasks", [])
	for task in sea_transit_import_tasks():
		doc.append("tasks", task)
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
