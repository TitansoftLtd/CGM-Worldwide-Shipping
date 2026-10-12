"""A cancelled Booking Confirmation lets go of the shipment it was on.

Frappe refuses to link a cancelled document, so a link left behind by a cancelled
booking stopped the shipment creating a Bill of Lading at all: "Cannot link
cancelled document: Booking Confirmation: 2X40-7" (CRM-OPP-2026-00031 /
PROJ-0028), which is also how the containers could not be entered.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.doctype.booking_confirmation import (
	booking_confirmation as bc,
)


class TestNewestSubmittedAmendment(unittest.TestCase):
	def _chain(self, links):
		def get_all(_doctype, filters=None, **kwargs):
			return links.get(filters["amended_from"], [])

		return patch.object(frappe, "get_all", side_effect=get_all)

	def test_no_amendment(self):
		with self._chain({}):
			self.assertIsNone(bc.newest_submitted_amendment("BC-1"))

	def test_follows_the_chain_to_the_submitted_one(self):
		links = {
			"BC-1": [frappe._dict(name="BC-1-1", docstatus=2)],
			"BC-1-1": [frappe._dict(name="BC-1-2", docstatus=1)],
		}
		with self._chain(links):
			self.assertEqual(bc.newest_submitted_amendment("BC-1"), "BC-1-2")

	def test_a_cancelled_amendment_with_no_successor_is_not_a_replacement(self):
		with self._chain({"BC-1": [frappe._dict(name="BC-1-1", docstatus=2)]}):
			self.assertIsNone(bc.newest_submitted_amendment("BC-1"))


class TestBookingLinkRelease(unittest.TestCase):
	def _holders(self):
		return [("Opportunity", "CRM-OPP-1", "custom_booking_confirmation"), ("Project", "PROJ-1", "custom_booking_confirmation")]

	def test_cancelling_clears_the_link_when_nothing_replaced_it(self):
		with (
			patch.object(bc, "_booking_link_holders", return_value=self._holders()),
			patch.object(bc, "newest_submitted_amendment", return_value=None),
			patch.object(frappe.db, "set_value") as set_value,
			patch.object(frappe, "clear_document_cache"),
		):
			changed = bc.release_cancelled_booking_links(frappe._dict(name="BC-1"))
		self.assertEqual(len(changed), 2)
		for call in set_value.call_args_list:
			self.assertIsNone(call.args[3])

	def test_cancelling_hands_the_link_to_the_replacement(self):
		with (
			patch.object(bc, "_booking_link_holders", return_value=self._holders()),
			patch.object(bc, "newest_submitted_amendment", return_value="BC-1-1"),
			patch.object(frappe.db, "set_value") as set_value,
			patch.object(frappe, "clear_document_cache"),
		):
			bc.release_cancelled_booking_links(frappe._dict(name="BC-1"))
		for call in set_value.call_args_list:
			self.assertEqual(call.args[3], "BC-1-1")

	def test_an_amendment_takes_the_links_over_on_submit(self):
		with (
			patch.object(bc, "_booking_link_holders", return_value=self._holders()) as holders,
			patch.object(frappe.db, "set_value") as set_value,
			patch.object(frappe, "clear_document_cache"),
		):
			changed = bc.take_over_links_from_amended_booking(
				frappe._dict(name="BC-1-1", amended_from="BC-1")
			)
		holders.assert_called_once_with("BC-1")
		self.assertEqual(len(changed), 2)
		for call in set_value.call_args_list:
			self.assertEqual(call.args[3], "BC-1-1")

	def test_a_first_booking_takes_nothing_over(self):
		with patch.object(bc, "_booking_link_holders") as holders:
			self.assertEqual(
				bc.take_over_links_from_amended_booking(frappe._dict(name="BC-2", amended_from=None)), []
			)
		holders.assert_not_called()
