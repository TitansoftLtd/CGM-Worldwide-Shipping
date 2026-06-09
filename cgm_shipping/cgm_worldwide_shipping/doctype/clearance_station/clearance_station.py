# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ClearanceStation(Document):
	def autoname(self):
		code = (self.station_code or "").strip()
		name = (self.cfs_name or "").strip()
		self.name = f"{code} - {name}"
