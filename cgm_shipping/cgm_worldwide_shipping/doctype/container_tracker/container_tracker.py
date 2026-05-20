# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, date_diff, getdate, today


class ContainerTracker(Document):
	def validate(self):
		self._calc_expected_empty_return()
		self._calc_demurrage_detention()
		self._update_status()

	def _calc_expected_empty_return(self):
		if self.gate_out_date_port and self.free_days:
			self.expected_empty_return = add_days(self.gate_out_date_port, self.free_days)

	def _calc_demurrage_detention(self):
		self.demurrage_days = 0
		self.detention_days = 0
		self.demurrage_amount = 0

		if self.discharging_date and self.gate_out_date_port:
			port_free = date_diff(self.gate_out_date_port, self.discharging_date)
			agreed = self.free_days or 0
			self.demurrage_days = max(0, port_free - agreed)

		if self.gate_out_date_port and self.actual_empty_return:
			self.detention_days = max(0, date_diff(self.actual_empty_return, self.gate_out_date_port))

		rate = self.daily_demurrage_rate or 0
		self.demurrage_amount = self.demurrage_days * rate

	def _update_status(self):
		if self.actual_empty_return:
			self.status = "Empty Returned"
			return
		if self.expected_empty_return and not self.actual_empty_return:
			if getdate(today()) > getdate(self.expected_empty_return):
				self.status = "Overdue"
				return
		if self.delivery_date and not self.actual_empty_return:
			self.status = "Empty Pending"
		elif self.gate_out_date_port:
			self.status = "Dispatched"
