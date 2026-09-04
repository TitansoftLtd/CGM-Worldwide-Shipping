# Copyright (c) 2026, Titansoft Limited and contributors
"""A message on a shipment: a question from a portal party, or CGM's update.

Almost every row is written through
`cgm_worldwide_shipping.customizations.operational_updates.create_update`,
which fills the bookkeeping fields. A row created by hand in Desk skips all of
that, so the same defaults are applied here - otherwise it lands with no
`posted_on`, sorts to the bottom of every feed, and shows a blank date in the
portal.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

PARTY_SOURCES = ("Customer", "Transporter")


class ShipmentUpdate(Document):
	def before_insert(self):
		if not self.posted_on:
			self.posted_on = now_datetime()
		if not self.posted_by:
			self.posted_by = frappe.session.user

	def validate(self):
		self.set_defaults()
		self.set_subject()
		self.sync_denormalised_fields()
		self.sync_audience()
		self.sync_response_state()

	def set_defaults(self):
		if not self.posted_on:
			self.posted_on = now_datetime()
		# A thread's activity is at least its own message.
		if not self.last_activity_on or self.last_activity_on < self.posted_on:
			self.last_activity_on = self.posted_on

	def set_subject(self):
		"""Portal users write a message, not a subject line."""
		if (self.subject or "").strip():
			return
		from cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates import (
			derive_subject,
		)

		self.subject = derive_subject(self.message)

	def sync_audience(self):
		"""A party's message reaches that party's portal, and no other.

		The form only offers the relevant box, but the rule has to hold here
		too: a haulier must never be able to read the customer's messages, or
		the customer the haulier's. CGM's own updates may go to either or both.
		"""
		if self.update_source == "Customer":
			self.visible_to_customer = 1
			self.visible_to_transporter = 0
		elif self.update_source == "Transporter":
			self.visible_to_transporter = 1
			self.visible_to_customer = 0

	def sync_denormalised_fields(self):
		if self.project and not self.customer:
			self.customer = frappe.db.get_value("Project", self.project, "customer")
		if self.container_tracker and not self.container_number:
			self.container_number = frappe.db.get_value(
				"Container Tracker", self.container_tracker, "container_number"
			)
		if self.container_tracker and not self.project:
			self.project = frappe.db.get_value(
				"Container Tracker", self.container_tracker, "project"
			)

	def sync_response_state(self):
		"""Only a party's message is a question CGM owes an answer to."""
		if self.update_source in PARTY_SOURCES:
			if not self.response_status:
				self.response_status = "Open"
		else:
			self.response_status = None
			self.responded_by = None
			self.responded_on = None
			self.response_update = None
