"""CGM branding for a new site: logo files, website and navbar logo, app name.

Runs from after_install only, so a new site starts as CGM; after that the desk
owns these settings and migrate never touches them.
"""

from __future__ import annotations

import os
import shutil

import frappe
from frappe.utils import get_files_path

CGM_APP_NAME = "CGM Worldwide Shipping"
CGM_LOGO_FILE = "CGM Logo.png"
CGM_ICON_FILE = "CGM Icon.png"
CGM_LOGO_URL = f"/files/{CGM_LOGO_FILE}"
CGM_ICON_URL = f"/files/{CGM_ICON_FILE}"


def apply_cgm_branding() -> None:
	_copy_logo_files()
	_set_website_and_navbar()
	_set_company_logo()
	frappe.clear_cache()


def _copy_logo_files() -> None:
	files_dir = get_files_path(is_private=False)
	os.makedirs(files_dir, exist_ok=True)
	app_images = frappe.get_app_path("cgm_shipping", "public", "images")
	for source, target in (
		(CGM_LOGO_FILE, CGM_LOGO_FILE),
		(CGM_ICON_FILE, CGM_ICON_FILE),
		("cgm_icon.png", CGM_ICON_FILE),
	):
		dest = os.path.join(files_dir, target)
		src = os.path.join(app_images, source)
		if not os.path.exists(dest) and os.path.exists(src):
			shutil.copy2(src, dest)


def _set_website_and_navbar() -> None:
	if frappe.db.exists("DocType", "Website Settings"):
		ws = frappe.get_single("Website Settings")
		ws.app_name = CGM_APP_NAME
		ws.app_logo = CGM_LOGO_URL
		ws.splash_image = CGM_LOGO_URL
		ws.banner_image = CGM_LOGO_URL
		ws.favicon = CGM_ICON_URL
		ws.brand_html = f'<img src="{CGM_LOGO_URL}" alt="{CGM_APP_NAME}">'
		ws.save(ignore_permissions=True)

	if frappe.db.exists("DocType", "Navbar Settings"):
		nav = frappe.get_single("Navbar Settings")
		nav.app_logo = CGM_LOGO_URL
		nav.save(ignore_permissions=True)

	if frappe.db.exists("DocType", "System Settings"):
		frappe.db.set_single_value("System Settings", "app_name", CGM_APP_NAME)


def _set_company_logo() -> None:
	if not frappe.db.table_exists("Company"):
		return
	companies = frappe.get_all("Company", fields=["name", "company_logo"])
	if len(companies) == 1 and not companies[0].company_logo:
		frappe.db.set_value("Company", companies[0].name, "company_logo", CGM_LOGO_URL)
