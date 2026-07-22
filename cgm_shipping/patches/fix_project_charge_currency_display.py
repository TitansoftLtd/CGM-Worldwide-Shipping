"""Show Project costing totals with each charge's currency instead of company default."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	_ensure_cf,
	_upsert_cf,
)

_CONTAINER_CHARGE_DISPLAY_FIELDS = (
	{
		"fieldname": "custom_demurrage_accrued_total_display",
		"label": "Demurrage/Detention Accrued Total",
		"fieldtype": "Data",
		"insert_after": "custom_section_container_charge_summary",
		"read_only": 1,
		"bold": 1,
	},
	{
		"fieldname": "custom_kpa_port_accrued_total_display",
		"label": "KPA Port Accrued Total",
		"fieldtype": "Data",
		"insert_after": "custom_demurrage_accrued_total_display",
		"read_only": 1,
		"bold": 1,
	},
	{
		"fieldname": "custom_demurrage_accrued_posted_total_display",
		"label": "Demurrage Posted to JE Total",
		"fieldtype": "Data",
		"insert_after": "custom_kpa_port_accrued_total_display",
		"read_only": 1,
	},
	{
		"fieldname": "custom_kpa_port_accrued_posted_total_display",
		"label": "KPA Port Posted to JE Total",
		"fieldtype": "Data",
		"insert_after": "custom_demurrage_accrued_posted_total_display",
		"read_only": 1,
	},
)

_LEGACY_NUMERIC_FIELDS = (
	"custom_demurrage_accrued_total",
	"custom_kpa_port_accrued_total",
	"custom_demurrage_accrued_posted_total",
	"custom_kpa_port_accrued_posted_total",
)


def execute() -> None:
	for values in _CONTAINER_CHARGE_DISPLAY_FIELDS:
		_upsert_cf("Project", values)

	for fieldname in _LEGACY_NUMERIC_FIELDS:
		name = f"Project-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			doc = frappe.get_doc("Custom Field", name)
			doc.hidden = 1
			doc.save(ignore_permissions=True)

	_upsert_cf(
		"Project",
		{
			"fieldname": "custom_finance_cost_total_display",
			"label": "Total Billed Amount (via Journal Entry)",
			"fieldtype": "Data",
			"insert_after": "custom_section_finance_cost_summary",
			"read_only": 1,
			"bold": 1,
		},
	)
	if frappe.db.exists("Custom Field", "Project-custom_finance_cost_total"):
		doc = frappe.get_doc("Custom Field", "Project-custom_finance_cost_total")
		doc.hidden = 1
		doc.label = "Total Billed Amount (via Journal Entry) — numeric"
		doc.save(ignore_permissions=True)

	frappe.clear_cache(doctype="Project")

	from cgm_shipping.cgm_worldwide_shipping.customizations.container_charges import (
		refresh_project_costing_display,
	)

	for project in frappe.get_all(
		"Container Tracker", filters={"project": ["is", "set"]}, pluck="project", distinct=True
	):
		try:
			refresh_project_costing_display(project)
		except Exception:
			frappe.log_error(title=f"Project costing display refresh failed: {project}")

	frappe.db.commit()
