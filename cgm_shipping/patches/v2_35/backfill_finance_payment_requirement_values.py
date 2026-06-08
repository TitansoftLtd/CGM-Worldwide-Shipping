"""Set Finance Payment subflow values (UCR / Permit / Standard) on existing settings rows."""
import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements.seed_data import (
	DEFAULT_FINANCE_KIND_BY_SEQ,
)


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field("custom_sea_clearance_task_requirements"):
		return

	settings = frappe.get_single("CGM Shipping Settings")
	changed = False
	for row in settings.get("custom_sea_clearance_task_requirements") or []:
		if row.requirement_type != "Finance Payment":
			continue
		if (row.value or "").strip():
			continue
		seq = int(row.sequence_no or 0)
		kind = DEFAULT_FINANCE_KIND_BY_SEQ.get(seq)
		if not kind:
			continue
		row.value = kind
		changed = True

	if changed:
		settings.save(ignore_permissions=True)
		frappe.db.commit()
