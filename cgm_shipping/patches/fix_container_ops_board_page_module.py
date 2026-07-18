"""Point Container Ops Board (and other stale pages) at CGM Worldwide Shipping.

Older sites created the page under the legacy ``mfi_shipping`` module. Frappe then
resolves assets to ``apps/frappe/frappe/mfi_shipping/page/...`` and raises
FileNotFoundError when loading ``container-ops-board``.
"""

from __future__ import annotations

import frappe

TARGET_MODULE = "CGM Worldwide Shipping"
LEGACY_MODULES = ("mfi_shipping", "MFI Shipping", "Mfi Shipping")


def execute() -> None:
	if not frappe.db.table_exists("Page"):
		return

	_pages = frappe.get_all(
		"Page",
		filters={"module": ["in", list(LEGACY_MODULES)]},
		pluck="name",
	)
	for name in _pages:
		frappe.db.set_value("Page", name, "module", TARGET_MODULE, update_modified=False)

	# Explicit fix even if module casing differs in the DB.
	if frappe.db.exists("Page", "container-ops-board"):
		current = frappe.db.get_value("Page", "container-ops-board", "module")
		if current != TARGET_MODULE:
			frappe.db.set_value(
				"Page",
				"container-ops-board",
				"module",
				TARGET_MODULE,
				update_modified=False,
			)

	frappe.db.commit()
	frappe.clear_cache(doctype="Page")
