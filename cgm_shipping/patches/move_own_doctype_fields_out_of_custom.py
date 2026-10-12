"""Take the app's own doctypes out of custom/*.json.

Container, Permit Register and Bill of Lading are cgm_shipping doctypes, so their
fields belong in the DocType JSON, not in Custom Fields exported to custom/*.json.

- Container.kpa_days and Permit Register.custom_source_task are now native fields
  with the same names, so their columns and data stay.
- Container.demurrage_amount / kpa_amount (fetched from Container Tracker fields
  production removed) and Bill of Lading.custom_linked_opportunity (a duplicate of
  linked_opportunity) are dropped.

Runs before model sync so a moved field never exists as both a Custom Field and a
DocField. Re-runnable: it only deletes the Custom Field records that still exist.
"""

import frappe

CUSTOM_FIELDS = (
	"Container-kpa_days",
	"Permit Register-custom_source_task",
	"Container-demurrage_amount",
	"Container-kpa_amount",
	"Bill of Lading-custom_linked_opportunity",
)


def execute():
	for name in CUSTOM_FIELDS:
		if frappe.db.exists("Custom Field", name):
			frappe.db.delete("Custom Field", {"name": name})
	for doctype in ("Container", "Permit Register", "Bill of Lading"):
		frappe.clear_cache(doctype=doctype)
