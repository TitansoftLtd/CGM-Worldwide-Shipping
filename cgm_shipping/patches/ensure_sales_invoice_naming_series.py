"""Sales Invoice naming series: INV-MMYY-#### and CR-MMYY-####."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	SALES_INVOICE_CREDIT_NOTE_NAMING_SERIES,
	SALES_INVOICE_NAMING_SERIES,
)

MODULE = "CGM Worldwide Shipping"


def execute() -> None:
	_ensure_sales_invoice_naming_series_options()
	frappe.db.commit()


def _ensure_sales_invoice_naming_series_options() -> None:
	desired = "\n".join(
		(SALES_INVOICE_NAMING_SERIES, SALES_INVOICE_CREDIT_NOTE_NAMING_SERIES)
	)
	name = "Sales Invoice-naming_series-options"
	if frappe.db.exists("Property Setter", name):
		current = frappe.db.get_value("Property Setter", name, "value")
		if current == desired:
			return
		frappe.db.set_value("Property Setter", name, "value", desired, update_modified=False)
		return

	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": "Sales Invoice",
			"field_name": "naming_series",
			"property": "options",
			"property_type": "Text",
			"value": desired,
			"module": MODULE,
			"name": name,
		}
	).insert(ignore_permissions=True)
