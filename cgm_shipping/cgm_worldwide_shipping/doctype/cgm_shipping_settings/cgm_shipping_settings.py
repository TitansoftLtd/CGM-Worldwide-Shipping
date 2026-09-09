# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CGMShippingSettings(Document):
	def validate(self):
		# Obsolete document gate (IPA/PIC no longer used); strip if still present from older seed / import.
		field = "custom_workflow_stage_requirements"
		for row in list(self.get(field) or []):
			if (
				(row.shipment_workflow_state or "").strip() == "Permits Processing"
				and (row.required_stage or "").strip() == "Permits (pre-clearance)"
			):
				self.remove(row)

	def on_update(self):
		# Responsibility / role-group lookups are request-cached.
		frappe.clear_cache()
		try:
			frappe.cache().delete_value("cgm:sea_task_ui_sequence_lists")
		except Exception:
			pass
		if not self.flags.get("skip_package_visibility_apply"):
			from cgm_shipping.cgm_worldwide_shipping.customizations.package_field_visibility import (
				apply_package_field_depends_on,
			)

			apply_package_field_depends_on()
		if self.flags.get("skip_role_group_sync"):
			return
		_sync_role_groups_from_settings(self)


def _sync_role_groups_from_settings(settings: "CGMShippingSettings") -> None:
	"""Push Roles-tab MultiSelect lists into matching CGM Role Group masters.

	Edits on CGM Shipping Settings → Roles must drive task visibility, so the
	linked CGM Role Group stays aligned with what the admin just saved.
	"""
	if not frappe.db.exists("DocType", "CGM Role Group"):
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		DEFAULT_ROLE_GROUPS,
		SETTINGS_ROLE_FIELDS,
	)

	for group_name, fieldname in SETTINGS_ROLE_FIELDS.items():
		if not settings.meta.has_field(fieldname):
			continue
		wanted = {r.role for r in (settings.get(fieldname) or []) if r.role}
		if not frappe.db.exists("CGM Role Group", group_name):
			if not wanted:
				continue
			default_stems = DEFAULT_ROLE_GROUPS.get(group_name, ("", ()))[0]
			doc = frappe.get_doc(
				{
					"doctype": "CGM Role Group",
					"role_group_name": group_name,
					"department_stems": default_stems,
					"roles": [{"role": role} for role in sorted(wanted)],
				}
			)
			doc.flags.skip_settings_sync = True
			doc.insert(ignore_permissions=True)
			continue

		doc = frappe.get_doc("CGM Role Group", group_name)
		current = {r.role for r in (doc.get("roles") or []) if r.role}
		if wanted == current:
			continue
		doc.set("roles", [])
		for role in sorted(wanted):
			doc.append("roles", {"role": role})
		if not (doc.department_stems or "").strip():
			doc.department_stems = DEFAULT_ROLE_GROUPS.get(group_name, ("", ()))[0]
		doc.flags.ignore_permissions = True
		doc.flags.skip_settings_sync = True
		doc.save(ignore_permissions=True)
