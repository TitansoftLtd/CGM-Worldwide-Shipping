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
		if self.rag_status == "Red":
			self._notify_supervisor()

	def _notify_supervisor(self):
		recipients = frappe.get_all(
			"Has Role",
			filters={"role": "Operations Manager", "parenttype": "User"},
			pluck="parent",
		)
		if not recipients:
			return
		frappe.sendmail(
			recipients=recipients,
			subject=f"Red RAG daily status — {self.group_team} ({self.date})",
			message=frappe.render_template(
				"<p>Team <b>{{ group }}</b> reported Red RAG on {{ date }}.</p>"
				"<p>{{ delays }}</p>",
				{"group": self.group_team, "date": self.date, "delays": self.delays_issues or ""},
			),
		)
