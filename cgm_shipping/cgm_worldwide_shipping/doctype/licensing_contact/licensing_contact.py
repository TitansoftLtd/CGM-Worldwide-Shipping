# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from cgm_shipping.cgm_worldwide_shipping.doctype.license_type.license_type import normalise_name


class LicensingContact(Document):
	def autoname(self):
		self.contact_name = normalise_name(self.contact_name)
		if not self.contact_name:
			frappe.throw(_("Name is required."), title=_("Missing Name"))

		self.name = self.contact_name

	def after_rename(self, old_name, new_name, merge=False):
		if self.contact_name != new_name:
			frappe.db.set_value(self.doctype, new_name, "contact_name", new_name)
