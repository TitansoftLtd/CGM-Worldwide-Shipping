# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CFSLocation(Document):
	def autoname(self):
		self.name = (self.location_name or "").strip()
