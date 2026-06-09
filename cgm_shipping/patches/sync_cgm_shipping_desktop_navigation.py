"""Force-sync Workspace Sidebar and Desktop Icon from app JSON into the database.

Pulling correct JSON from git does not update existing DB rows when the DB
``modified`` timestamp is newer than the file. Stale sidebars (e.g. Home →
Workspace "CGM", module "Projects") break desktop icon routing.
"""

import os

import frappe
from frappe.modules.import_file import import_file_by_path


def execute():
	app_path = frappe.get_app_path("cgm_shipping")
	paths = (
		os.path.join(app_path, "workspace_sidebar", "cgm_shipping.json"),
		os.path.join(app_path, "desktop_icon", "cgm_shipping.json"),
	)
	for path in paths:
		import_file_by_path(path, force=True, ignore_version=True)
	frappe.clear_cache()
