"""PI/PE custom fields + finance task linking."""
import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link import (
		ensure_finance_custom_fields,
	)

	ensure_finance_custom_fields()
	frappe.clear_cache()
