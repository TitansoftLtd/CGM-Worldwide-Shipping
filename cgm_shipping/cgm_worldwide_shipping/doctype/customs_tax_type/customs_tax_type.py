# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_calculation import (
	VALID_CALCULATION_MODES,
	VALID_PERCENTAGE_BASES,
	allowed_modes_from_doc,
	normalize_percentage_base,
)


class CustomsTaxType(Document):
	def validate(self):
		self._validate_allowed_modes()
		self._validate_default_mode()
		self._validate_percentage_base()

	def _validate_allowed_modes(self):
		modes = allowed_modes_from_doc(self)
		if not modes:
			frappe.throw(_("Please select at least one Allowed Calculation Mode."))

		invalid = [m for m in modes if m not in VALID_CALCULATION_MODES]
		if invalid:
			frappe.throw(
				_(
					"Unknown Calculation Mode(s): {0}. "
					"Supported modes: {1}."
				).format(", ".join(invalid), ", ".join(sorted(VALID_CALCULATION_MODES)))
			)

	def _validate_default_mode(self):
		modes = allowed_modes_from_doc(self)
		default_mode = (self.default_calculation_mode or "").strip()
		if not default_mode:
			frappe.throw(_("Default Calculation Mode is required."))
		if default_mode not in modes:
			frappe.throw(
				_(
					"Default Calculation Mode '{0}' must be one of the Allowed Calculation Modes: {1}."
				).format(default_mode, ", ".join(modes))
			)

	def _validate_percentage_base(self):
		base = normalize_percentage_base(self.percentage_base)
		if base not in VALID_PERCENTAGE_BASES:
			frappe.throw(
				_(
					"Invalid Percentage Base '{0}'. Valid options: {1}."
				).format(self.percentage_base or _("(empty)"), ", ".join(sorted(VALID_PERCENTAGE_BASES)))
			)
		self.percentage_base = base
