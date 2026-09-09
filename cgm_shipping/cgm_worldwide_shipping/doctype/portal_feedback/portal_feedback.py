# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""Feedback left by a customer or transporter on a shipment.

Feedback hangs off the Project. The `containers` child table optionally narrows
it to particular boxes on that shipment, so a haulier can say "these three ran
badly" without the rating becoming a separate per-container record.

Rows are written from the portal through
`cgm_worldwide_shipping.customizations.portal_feedback`, never by the party
directly - the portal user holds no role on this DocType. Ops reads and
answers feedback in Desk.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

RATING_MAX = 5


class PortalFeedback(Document):
	def validate(self):
		self.validate_rating()
		self.validate_containers()
		self.sync_denormalised_fields()
		self.set_title()

	def before_insert(self):
		if not self.submitted_by:
			self.submitted_by = frappe.session.user
		if not self.submitted_on:
			self.submitted_on = now_datetime()
		if not self.status:
			self.status = "New"

	def on_update(self):
		self.stamp_response()

	def validate_rating(self):
		# Frappe stores Rating as a 0-1 float; the portal posts 0.5-5 stars.
		rating = flt(self.rating)
		if rating > 1:
			rating = rating / RATING_MAX
		if rating <= 0 or rating > 1:
			frappe.throw(_("Give a rating between 0.5 and {0} stars.").format(RATING_MAX))
		self.rating = rating

	def validate_containers(self):
		"""Every ticked container must belong to this shipment."""
		if not self.get("containers"):
			return
		if not self.project:
			frappe.throw(_("Select the shipment before naming containers."))

		seen: set[str] = set()
		rows = []
		for row in self.containers:
			if not row.container_tracker or row.container_tracker in seen:
				continue
			project = frappe.db.get_value(
				"Container Tracker", row.container_tracker, "project"
			)
			if project != self.project:
				frappe.throw(
					_("Container {0} is not on shipment {1}.").format(
						row.container_tracker, self.project
					)
				)
			seen.add(row.container_tracker)
			rows.append(row)

		self.containers = rows
		for idx, row in enumerate(self.containers, start=1):
			row.idx = idx

	def sync_denormalised_fields(self):
		if self.submitted_by_party == "Customer":
			self.transporter = None
			if not self.customer and self.project:
				self.customer = frappe.db.get_value("Project", self.project, "customer")
		elif self.submitted_by_party == "Transporter":
			self.customer = None

	def set_title(self):
		reference = self.project or ""
		if self.submitted_by_party == "Customer" and self.customer:
			party_label = (
				frappe.db.get_value("Customer", self.customer, "customer_name") or self.customer
			)
		elif self.submitted_by_party == "Transporter" and self.transporter:
			party_label = (
				frappe.db.get_value("Supplier", self.transporter, "supplier_name")
				or self.transporter
			)
		else:
			party_label = self.submitted_by or ""
		self.title = " - ".join(p for p in (reference, party_label) if p) or _("Feedback")

	def stamp_response(self):
		"""Record who answered, the first time a response is written."""
		if not (self.response or "").strip():
			return
		if self.responded_by and self.responded_on:
			return
		frappe.db.set_value(
			self.doctype,
			self.name,
			{
				"responded_by": frappe.session.user,
				"responded_on": now_datetime(),
				"status": self.status if self.status != "New" else "Acknowledged",
			},
			update_modified=False,
		)
