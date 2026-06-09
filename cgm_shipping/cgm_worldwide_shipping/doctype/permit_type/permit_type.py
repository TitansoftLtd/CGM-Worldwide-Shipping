# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PermitType(Document):
	def autoname(self):
		# Name by the Permit Name (naming_rule: "By script").
		if not self.permit_name:
			frappe.throw(frappe._("Permit Name is required"))
		self.name = self.permit_name.strip()
