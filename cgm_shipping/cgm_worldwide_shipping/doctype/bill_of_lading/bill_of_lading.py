# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_bill_of_lading import (
	sanitize_bill_of_lading_linked_opportunity,
)


class BillofLading(Document):
	def validate(self):
		sanitize_bill_of_lading_linked_opportunity(self)
