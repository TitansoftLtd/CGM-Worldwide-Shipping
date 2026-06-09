# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ShipmentType(Document):
	def autoname(self):
		self.name = (self.shipment_type_name or "").strip()
