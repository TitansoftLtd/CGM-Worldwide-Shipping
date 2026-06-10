# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class DocumentType(Document):
	def autoname(self):
		# Name by the document Code (naming_rule: "By script").
		if not self.code:
			frappe.throw(frappe._("Code is required"))
		self.name = self.code.strip()
