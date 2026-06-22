"""Install or update CGM Quotation print formats."""

from __future__ import annotations

from pathlib import Path

import frappe

MODULE = "CGM Worldwide Shipping"
BASE_DIR = Path(__file__).resolve().parents[1] / "cgm_worldwide_shipping" / "print_format"

PRINT_FORMATS = (
	{
		"name": "CGM Quotation Shipping",
		"doc_type": "Quotation",
		"template": BASE_DIR / "cgm_quotation_shipping" / "cgm_quotation_shipping.html",
		"default_for": "Quotation",
	},
)


def execute() -> None:
	for spec in PRINT_FORMATS:
		_upsert_print_format(spec)
	frappe.db.commit()


def _upsert_print_format(spec: dict) -> None:
	html = spec["template"].read_text(encoding="utf-8")
	values = {
		"doc_type": spec["doc_type"],
		"module": MODULE,
		"custom_format": 1,
		"print_format_type": "Jinja",
		"standard": "Yes",
		"disabled": 0,
		"html": html,
	}

	if frappe.db.exists("Print Format", spec["name"]):
		doc = frappe.get_doc("Print Format", spec["name"])
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "Print Format", "name": spec["name"], **values})
		doc.insert(ignore_permissions=True)

	if spec.get("default_for"):
		ps_name = f"{spec['default_for']}-main-default_print_format"
		if frappe.db.exists("Property Setter", ps_name):
			frappe.db.set_value(
				"Property Setter",
				ps_name,
				"value",
				spec["name"],
				update_modified=False,
			)
		else:
			frappe.make_property_setter(
				{
					"doctype": spec["default_for"],
					"property": "default_print_format",
					"value": spec["name"],
					"property_type": "Data",
				},
				ignore_validate=True,
				is_system_generated=0,
			)
