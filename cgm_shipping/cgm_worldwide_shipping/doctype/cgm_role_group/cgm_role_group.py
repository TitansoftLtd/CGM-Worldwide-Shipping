# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CGMRoleGroup(Document):
	def validate(self):
		self.role_group_name = (self.role_group_name or "").strip()
		if not self.role_group_name:
			frappe.throw("Role Group Name is required.")
		# Deduplicate roles
		seen = set()
		unique = []
		for row in self.get("roles") or []:
			if not row.role or row.role in seen:
				continue
			seen.add(row.role)
			unique.append({"role": row.role})
		self.set("roles", unique)

	def on_update(self):
		frappe.clear_cache()
		try:
			frappe.cache().delete_value("cgm:sea_task_ui_sequence_lists")
		except Exception:
			pass
		# Keep legacy Settings MultiSelect lists in sync for older callers.
		_sync_settings_role_multiselect(self)


def _sync_settings_role_multiselect(role_group: "CGMRoleGroup") -> None:
	field_by_name = {
		"Finance": "custom_finance_roles",
		"Declaration": "custom_declaration_roles",
		"Operations": "custom_operations_roles",
		"Transport": "custom_transport_roles",
	}
	fieldname = field_by_name.get(role_group.name)
	if not fieldname or not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return
	settings = frappe.get_doc("CGM Shipping Settings")
	if not settings.meta.has_field(fieldname):
		return
	wanted = {r.role for r in (role_group.get("roles") or []) if r.role}
	current = {r.role for r in (settings.get(fieldname) or []) if r.role}
	if wanted == current:
		return
	settings.set(fieldname, [])
	for role in sorted(wanted):
		settings.append(fieldname, {"role": role})
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)
