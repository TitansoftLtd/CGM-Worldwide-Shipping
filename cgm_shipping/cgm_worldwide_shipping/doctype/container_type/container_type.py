# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ContainerType(Document):
	def autoname(self):
		if not self.container_type:
			frappe.throw(frappe._("Container Type is required"))
		self.name = self.container_type.strip()
