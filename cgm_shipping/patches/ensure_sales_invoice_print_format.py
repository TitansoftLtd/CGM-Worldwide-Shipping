"""Install CGM Sales Invoice print format from JSON fixture (idempotent)."""

from __future__ import annotations

import json
from pathlib import Path

import frappe

PRINT_FORMAT_NAME = "CGM Sales Invoice Default"
JSON_FILE = "cgm_sales_invoice_default/cgm_sales_invoice_default.json"


def execute() -> None:
	if not frappe.db.exists("DocType", "Print Format"):
		return

	json_path = (
		Path(__file__).resolve().parents[1]
		/ "cgm_worldwide_shipping"
		/ "print_format"
		/ JSON_FILE
	)
	if not json_path.is_file():
		frappe.log_error(
			title="CGM Sales Invoice Print Format",
			message=f"Print Format JSON not found: {json_path}",
		)
		return

	data = json.loads(json_path.read_text(encoding="utf-8"))
	html = data.get("html")
	if not html:
		frappe.log_error(
			title="CGM Sales Invoice Print Format",
			message=f"No html field in Print Format JSON: {json_path}",
		)
		return

	_upsert_print_format(html)
	frappe.db.commit()


def _upsert_print_format(html: str) -> None:
	if frappe.db.exists("Print Format", PRINT_FORMAT_NAME):
		doc = frappe.get_doc("Print Format", PRINT_FORMAT_NAME)
		doc.html = html
		doc.disabled = 0
		doc.pdf_generator = "chrome"
		doc.margin_top = 10
		doc.margin_bottom = 12
		doc.margin_left = 12
		doc.margin_right = 12
		doc.save(ignore_permissions=True)
		return

	doc = frappe.new_doc("Print Format")
	doc.name = PRINT_FORMAT_NAME
	doc.doc_type = "Sales Invoice"
	doc.module = "CGM Worldwide Shipping"
	doc.custom_format = 1
	doc.standard = "Yes"
	doc.print_format_type = "Jinja"
	doc.print_format_for = "DocType"
	doc.disabled = 0
	doc.font_size = 14
	doc.margin_top = 10
	doc.margin_bottom = 12
	doc.margin_left = 12
	doc.margin_right = 12
	doc.page_number = "Hide"
	doc.pdf_generator = "chrome"
	doc.html = html
	doc.insert(ignore_permissions=True)
