# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CGMShippingSettings(Document):
	def validate(self):
		# Obsolete document gate (IPA/PIC no longer used); strip if still present from older seed / import.
		field = "custom_workflow_stage_requirements"
		for row in list(self.get(field) or []):
			if (
				(row.shipment_workflow_state or "").strip() == "Permits Processing"
				and (row.required_stage or "").strip() == "Permits (pre-clearance)"
			):
				self.remove(row)
