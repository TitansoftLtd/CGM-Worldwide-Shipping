# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LicenseType(Document):
	def autoname(self):
		self.type_name = normalise_name(self.type_name)
		if not self.type_name:
			frappe.throw(_("Type Name is required."), title=_("Missing Name"))

		self.name = self.type_name

	def after_rename(self, old_name, new_name, merge=False):
		if self.type_name != new_name:
			frappe.db.set_value(self.doctype, new_name, "type_name", new_name)


def normalise_name(value):
	"""Trim and collapse runs of whitespace so "  Business   Licence " names cleanly."""
	return " ".join((value or "").split())
