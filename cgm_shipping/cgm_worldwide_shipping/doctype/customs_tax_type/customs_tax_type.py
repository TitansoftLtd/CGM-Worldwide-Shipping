# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_calculation import (
	parse_allowed_modes,
)


class CustomsTaxType(Document):
	def validate(self):
		self._normalize_allowed_modes()
		self._validate_allowed_modes()
		self._validate_default_mode()

	def _normalize_allowed_modes(self):
		modes = parse_allowed_modes(self.allowed_calculation_modes)
		self.allowed_calculation_modes = "\n".join(modes) if modes else None

	def _validate_allowed_modes(self):
		if not parse_allowed_modes(self.allowed_calculation_modes):
			frappe.throw(_("Please set at least one Allowed Calculation Mode."))

	def _validate_default_mode(self):
		modes = parse_allowed_modes(self.allowed_calculation_modes)
		default_mode = (self.default_calculation_mode or "").strip()
		if not default_mode:
			frappe.throw(_("Default Calculation Mode is required."))
		if default_mode not in modes:
			frappe.throw(
				_(
					"Default Calculation Mode '{0}' must be one of the Allowed Calculation Modes: {1}."
				).format(default_mode, ", ".join(modes))
			)
