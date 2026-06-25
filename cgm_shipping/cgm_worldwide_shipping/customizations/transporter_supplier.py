# Copyright (c) 2026, Titansoft Limited and contributors
"""Keep transporter Supplier portal users aligned with the transporter portal."""

from __future__ import annotations

import frappe
from frappe import _


def _ensure_transporter_role_record() -> None:
	"""Create/update the Transporter role (desk disabled). Idempotent."""
	role_name = "Transporter"
	if not frappe.db.exists("Role", role_name):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 0,
			}
		).insert(ignore_permissions=True)
	else:
		frappe.db.set_value("Role", role_name, "desk_access", 0, update_modified=False)


def sync_transporter_supplier_portal_users(doc, method=None) -> None:
	"""When a transporter Supplier is saved, ensure portal users can reach `/transporter`."""
	if not doc.get("is_transporter"):
		return
	for row in doc.get("portal_users") or []:
		if row.user:
			ensure_transporter_portal_user(row.user)


def ensure_transporter_portal_user(user: str) -> None:
	"""Ensure Transporter role + portal-friendly defaults for a Supplier portal user."""
	_ensure_transporter_role_record()

	if not frappe.db.exists("User", user):
		return

	user_doc = frappe.get_doc("User", user)
	changed = False

	if user_doc.get("default_app"):
		user_doc.default_app = ""
		changed = True

	roles = {r.role for r in user_doc.roles}
	if "Transporter" not in roles:
		user_doc.add_roles("Transporter")
		changed = True

	if changed:
		user_doc.save(ignore_permissions=True)
		frappe.clear_cache(user=user)


def ensure_transporter_portal_menu() -> None:
	"""Register `/transporter` on Portal Settings (same mechanism as customer portal nav)."""
	if not frappe.db.exists("DocType", "Portal Settings"):
		return

	settings = frappe.get_single("Portal Settings")
	for row in settings.get("menu") or []:
		if (row.route or "").strip("/") == "transporter":
			return

	settings.append(
		"menu",
		{
			"title": _("Transporter Portal"),
			"route": "transporter",
			"enabled": 1,
			"role": "Transporter",
		},
	)
	settings.save(ignore_permissions=True)


def sync_all_transporter_portal_users() -> None:
	"""One-time / migrate sync for existing transporter suppliers."""
	_ensure_transporter_role_record()
	ensure_transporter_portal_menu()

	suppliers = frappe.get_all(
		"Supplier",
		filters={"is_transporter": 1, "disabled": 0},
		pluck="name",
	)
	for supplier_name in suppliers:
		doc = frappe.get_doc("Supplier", supplier_name)
		sync_transporter_supplier_portal_users(doc)
	frappe.db.commit()
