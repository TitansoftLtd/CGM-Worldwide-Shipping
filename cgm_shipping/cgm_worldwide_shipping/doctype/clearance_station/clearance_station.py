# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ClearanceStation(Document):
	def autoname(self):
		self.name = (self.cfs_name or "").strip()
