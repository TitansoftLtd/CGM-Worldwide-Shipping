"""Re-resolve sea task departments from project company (Finance - C → Finance - CWSCL)."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	SEA_TASK_FLOW_KEY,
	load_sea_task_template,
	normalize_department_stem,
	resolve_department_name,
)


def execute():
	template = load_sea_task_template()
	if not template:
		return

	updated = 0
	tasks = frappe.get_all(
		"Task",
		filters={"custom_task_flow_key": SEA_TASK_FLOW_KEY},
		fields=["name", "project", "department", "custom_sequence_no"],
	)
	for row in tasks:
		if not row.project:
			continue
		company = frappe.db.get_value("Project", row.project, "company")
		if not company:
			continue
		seq = int(row.custom_sequence_no or 0)
		if seq < 1 or seq > len(template):
			continue
		stem = normalize_department_stem(template[seq - 1].get("department"))
		if not stem:
			continue
		try:
			new_dept = resolve_department_name(stem, company=company)
		except Exception:
			frappe.log_error(
				title="CGM resync sea task department",
				message=f"Task {row.name} seq {seq} company {company} stem {stem}",
			)
			continue
		if new_dept and new_dept != row.department:
			frappe.db.set_value(
				"Task", row.name, "department", new_dept, update_modified=False
			)
			updated += 1

	frappe.clear_cache(doctype="Task")
	if updated:
		frappe.logger().info("CGM: resynced department on %s sea tasks", updated)
