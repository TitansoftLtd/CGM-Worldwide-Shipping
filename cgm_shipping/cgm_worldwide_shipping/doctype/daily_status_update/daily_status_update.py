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
		if self.rag_status in ("Red", "Yellow"):
			self._notify_supervisor()

	def _notify_supervisor(self):
		recipients = frappe.get_all(
			"Has Role",
			filters={"role": "Operations Manager", "parenttype": "User"},
			pluck="parent",
		)
		if not recipients:
			return
		level = self.rag_status
		frappe.sendmail(
			recipients=recipients,
			subject=f"{level} RAG daily status — {self.group_team} ({self.date})",
			message=frappe.render_template(
				"<p>Team <b>{{ group }}</b> reported <b>{{ level }}</b> RAG on {{ date }}.</p>"
				"<p>Dispatched: {{ dispatched }} · Deliveries: {{ deliveries }}</p>"
				"<p>Empty pending: {{ empty_pending }} · Returned today: {{ returned }}</p>"
				"<p><b>Delays:</b> {{ delays }}</p>"
				"<p><b>Actions:</b> {{ actions }}</p>",
				{
					"group": self.group_team,
					"date": self.date,
					"level": level,
					"dispatched": self.shipments_dispatched or 0,
					"deliveries": self.deliveries_completed or 0,
					"empty_pending": self.empty_containers_pending or 0,
					"returned": self.containers_returned_today or 0,
					"delays": self.delays_issues or "—",
					"actions": self.outstanding_actions or "—",
				},
			),
		)
