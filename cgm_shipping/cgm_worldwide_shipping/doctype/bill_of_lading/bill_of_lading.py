# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
import frappe
from frappe.model.document import Document
from cgm_shipping.cgm_worldwide_shipping.customizations.bl_containers import (
	sanitize_bill_of_lading_linked_opportunity,
)


def summarize_bl_container_quantities(bl_name: str | None) -> str:
    """Summarize container type counts for a Bill of Lading by name."""
    if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
        return ""
    doc = frappe.get_doc("Bill of Lading", bl_name)
    return doc._summarize_container_quantities()


class BillofLading(Document):
    def validate(self):
        sanitize_bill_of_lading_linked_opportunity(self)
        summary = self._summarize_container_quantities()
        if self.meta.has_field("container_summary"):
            self.container_summary = summary
        if self.meta.has_field("quantity"):
            self.quantity = summary

    def _summarize_container_quantities(self) -> str:
        """Return e.g. '6 x 40FT, 7 x 20FT' from this document's container rows."""
        if not self.container_information:
            return ""

        # Fetch order directly from Container Type DocType
        display_order = frappe.get_all(
            "Container Type",
            fields=["container_type"],
            order_by="idx asc",
            pluck="container_type"
        )

        counts: dict[str, int] = {}
        for row in self.container_information:
            container_type = (row.type_of_container or "").strip()
            if not container_type:
                continue
            counts[container_type] = counts.get(container_type, 0) + 1

        if not counts:
            return ""

        ordered = [t for t in display_order if t in counts]
        for t in sorted(counts):
            if t not in ordered:
                ordered.append(t)

        return ", ".join(f"{counts[t]} x {t}" for t in ordered)