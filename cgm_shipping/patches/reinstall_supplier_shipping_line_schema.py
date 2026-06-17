"""Force-create Supplier child-table fields (one-time fix when patch log blocked re-run)."""

from __future__ import annotations

from cgm_shipping.install import reinstall_supplier_shipping_line_schema


def execute():
	reinstall_supplier_shipping_line_schema()
