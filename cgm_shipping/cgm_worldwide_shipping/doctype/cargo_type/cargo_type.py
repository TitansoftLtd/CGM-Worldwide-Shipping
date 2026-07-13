# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CargoType(Document):
	def autoname(self):
		if not self.cargo_type:
			frappe.throw(frappe._("Cargo Type is required"))
		self.name = self.cargo_type.strip()
