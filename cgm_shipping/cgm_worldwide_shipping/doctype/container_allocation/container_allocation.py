# Copyright (c) 2026, Titansoft Limited and contributors

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation import (
	assign_trackers_on_submit,
	validate_active_allocation_uniqueness,
	validate_transporter_supplier,
)


class ContainerAllocation(Document):
	def validate(self):
		validate_transporter_supplier(self.transporter)
		validate_active_allocation_uniqueness(self)
		if not self.containers:
			frappe.throw(_("Add at least one container to allocate."))

	def on_submit(self):
		assign_trackers_on_submit(self)
		self.db_set("status", "Allocated", update_modified=False)

	def on_cancel(self):
		self.db_set("status", "Draft", update_modified=False)
