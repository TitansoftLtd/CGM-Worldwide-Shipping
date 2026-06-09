# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document


class DailyStatusUpdate(Document):
	def before_insert(self):
		if not self.submitted_by:
			self.submitted_by = frappe.session.user

	def on_submit(self):
		if self.rag_status not in ("Red", "Yellow"):
			return
		from cgm_shipping.cgm_worldwide_shipping.customizations.notifications_service import (
			DAILY_STATUS_RAG_ALERT,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.notifications_service import (
			send_notification,
		)

		send_notification(DAILY_STATUS_RAG_ALERT, self, audience="Operations")
