"""Restore company branding from the temporary MFI identity back to CGM.

One-time / idempotent: if the company is still named MFI, rename it to
CGM Worldwide Shipping Company Limited, swap logos and letterheads to the
CGM assets, then delete leftover MFI logo files.
"""

from __future__ import annotations

import os
import re
import shutil

import frappe
from frappe.utils import get_files_path

CGM_COMPANY_NAME = "CGM Worldwide Shipping Company Limited"
CGM_APP_NAME = "CGM Worldwide Shipping"
CGM_LOGO_FILE = "CGM Logo.png"
CGM_ICON_FILE = "CGM Icon.png"
CGM_LOGO_URL = f"/files/{CGM_LOGO_FILE}"
CGM_ICON_URL = f"/files/{CGM_ICON_FILE}"

_MFI_COMPANY_NAMES = (
	"MFI Shipping Company",
	"MFI Shipping Company Limited",
)
_MFI_NAME_FRAGMENTS = ("MFI Shipping Company Limited", "MFI Shipping Company", "MFI")
_MFI_FILE_RE = re.compile(r"mfi", re.IGNORECASE)


def execute() -> None:
	company = _restore_company_name()
	_ensure_cgm_logo_files()
	if company:
		frappe.db.set_value("Company", company, "company_logo", CGM_LOGO_URL)
	_restore_website_and_navbar()
	_restore_letter_heads()
	_delete_mfi_logo_files()
	frappe.clear_cache()
	frappe.db.commit()


def _restore_company_name() -> str | None:
	if not frappe.db.table_exists("Company"):
		return None

	if frappe.db.exists("Company", CGM_COMPANY_NAME):
		return CGM_COMPANY_NAME

	mfi_name = _find_mfi_company()
	if not mfi_name:
		# Fall back to the only company on a single-company site.
		companies = frappe.get_all("Company", pluck="name")
		return companies[0] if len(companies) == 1 else None

	frappe.rename_doc(
		"Company",
		mfi_name,
		CGM_COMPANY_NAME,
		force=True,
		show_alert=False,
	)
	return CGM_COMPANY_NAME


def _find_mfi_company() -> str | None:
	for name in _MFI_COMPANY_NAMES:
		if frappe.db.exists("Company", name):
			return name
	matches = frappe.get_all(
		"Company",
		filters={"company_name": ["like", "%MFI%"]},
		pluck="name",
	)
	return matches[0] if matches else None


def _ensure_cgm_logo_files() -> None:
	files_dir = get_files_path(is_private=False)
	os.makedirs(files_dir, exist_ok=True)
	app_images = frappe.get_app_path("cgm_shipping", "public", "images")

	for filename in (CGM_LOGO_FILE, CGM_ICON_FILE, "cgm_icon.png"):
		dest_name = CGM_ICON_FILE if filename == "cgm_icon.png" else filename
		dest = os.path.join(files_dir, dest_name)
		if os.path.exists(dest):
			continue
		src = os.path.join(app_images, filename)
		if os.path.exists(src):
			shutil.copy2(src, dest)


def _restore_website_and_navbar() -> None:
	if frappe.db.exists("DocType", "Website Settings"):
		ws = frappe.get_single("Website Settings")
		ws.app_name = CGM_APP_NAME
		ws.app_logo = CGM_LOGO_URL
		ws.splash_image = CGM_LOGO_URL
		ws.banner_image = CGM_LOGO_URL
		ws.favicon = CGM_ICON_URL
		ws.brand_html = f'<img src="{CGM_LOGO_URL}" alt="{CGM_APP_NAME}">'
		ws.flags.ignore_permissions = True
		ws.save(ignore_permissions=True)

	if frappe.db.exists("DocType", "Navbar Settings"):
		nav = frappe.get_single("Navbar Settings")
		nav.app_logo = CGM_LOGO_URL
		nav.flags.ignore_permissions = True
		nav.save(ignore_permissions=True)

	if frappe.db.exists("DocType", "System Settings"):
		frappe.db.set_single_value("System Settings", "app_name", CGM_APP_NAME)


def _restore_letter_heads() -> None:
	if not frappe.db.exists("DocType", "Letter Head"):
		return
	for name in frappe.get_all("Letter Head", pluck="name"):
		doc = frappe.get_doc("Letter Head", name)
		changed = False
		if _is_mfi_url(doc.image):
			doc.image = CGM_LOGO_URL
			changed = True
		for field in ("content", "footer", "header"):
			if not doc.meta.has_field(field):
				continue
			value = doc.get(field)
			if not value:
				continue
			updated = _replace_mfi_branding(value)
			if updated != value:
				doc.set(field, updated)
				changed = True
		if changed:
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)


def _replace_mfi_branding(html: str) -> str:
	updated = html
	for old, new in (
		("/files/MFI Logo.png", CGM_LOGO_URL),
		("/files/mfi-logo.png", CGM_LOGO_URL),
		("/files/mfi-logo6c2d1c.png", CGM_LOGO_URL),
	):
		updated = re.sub(re.escape(old), new, updated, flags=re.IGNORECASE)
	for fragment in _MFI_NAME_FRAGMENTS:
		replacement = CGM_COMPANY_NAME if "Company" in fragment else CGM_APP_NAME
		updated = updated.replace(fragment, replacement)
	return updated


def _is_mfi_url(url: str | None) -> bool:
	return bool(url and _MFI_FILE_RE.search(url))


def _delete_mfi_logo_files() -> None:
	if not frappe.db.exists("DocType", "File"):
		return

	files = frappe.get_all(
		"File",
		filters={"file_url": ["like", "%mfi%"]},
		pluck="name",
	)
	files += frappe.get_all(
		"File",
		filters={"file_name": ["like", "%mfi%"]},
		pluck="name",
	)
	for name in dict.fromkeys(files):
		try:
			frappe.delete_doc("File", name, force=True, ignore_permissions=True)
		except Exception:
			frappe.log_error(
				title="CGM branding: could not delete MFI file",
				message=frappe.get_traceback(),
			)

	files_dir = get_files_path(is_private=False)
	if not os.path.isdir(files_dir):
		return
	for filename in os.listdir(files_dir):
		if _MFI_FILE_RE.search(filename):
			path = os.path.join(files_dir, filename)
			if os.path.isfile(path):
				os.remove(path)
