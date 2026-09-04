# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""Customer / transporter portal engagement: visibility, threads, feedback."""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates import (
	AUDIENCE_CUSTOMER,
	AUDIENCE_TRANSPORTER,
	CGM_SOURCES,
	_customer_can_access_update,
	_thread_payload,
	_transporter_can_access_update,
	default_audience_for_source,
	post_published_update,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.portal_feedback import (
	RATING_MAX,
	RATING_STEP,
	feedback_summary,
	rating_from_stars,
	stars_from_rating,
)

_MODULE = "cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates"


def _row(**kwargs):
	values = {
		"name": "UPD-1",
		"update_source": "Customer",
		"subject": "Question",
		"message": "Where is my container?",
		"posted_on": "2026-09-01 09:00:00",
		"posted_by": "customer@example.com",
		"is_read": 0,
		"project": "PROJ-0001",
		"customer": "CUST-0001",
		"container_tracker": None,
		"container_number": None,
		"transporter": None,
		"allocation": None,
		"allocation_item": None,
		"attachment": None,
		"event_date": None,
		"truck_number": None,
		"driver_name": None,
		"driver_contact": None,
		"visible_to_customer": 1,
		"visible_to_transporter": 0,
		"parent_update": None,
		"customer_read_on": None,
		"transporter_read_on": None,
		"response_status": "Open",
		"responded_by": None,
		"responded_on": None,
		"response_update": None,
	}
	values.update(kwargs)
	return values


class TestUpdateAudienceDefaults(unittest.TestCase):
	def test_party_posts_are_visible_to_that_party_only(self):
		self.assertEqual(default_audience_for_source("Customer"), (True, False))
		self.assertEqual(default_audience_for_source("Transporter"), (False, True))

	def test_cgm_sources_default_to_internal(self):
		for source in CGM_SOURCES:
			self.assertEqual(
				default_audience_for_source(source),
				(False, False),
				msg=f"{source} must not reach a portal unless published",
			)


class TestThreadPayload(unittest.TestCase):
	"""`_thread_payload` decides which side of the conversation a row sits on."""

	def setUp(self):
		patcher_ref = patch(f"{_MODULE}._project_display_ref", return_value="LJL-2606-0468")
		patcher_value = patch("frappe.db.get_value", return_value="Acme Ltd")
		patcher_name = patch("frappe.utils.get_fullname", return_value="A Person")
		for p in (patcher_ref, patcher_value, patcher_name):
			p.start()
			self.addCleanup(p.stop)

	def test_party_message_is_outgoing_and_never_unread(self):
		[message] = _thread_payload([_row()], audience=AUDIENCE_CUSTOMER)
		self.assertEqual(message["direction"], "out")
		self.assertFalse(message["from_cgm"])
		self.assertFalse(message["unread"])

	def test_cgm_message_is_incoming_and_unread_until_stamped(self):
		rows = [_row(name="UPD-2", update_source="Internal", subject="Vessel berthed")]
		[message] = _thread_payload(rows, audience=AUDIENCE_CUSTOMER)
		self.assertEqual(message["direction"], "in")
		self.assertTrue(message["unread"])

		rows[0]["customer_read_on"] = "2026-09-02 10:00:00"
		[message] = _thread_payload(rows, audience=AUDIENCE_CUSTOMER)
		self.assertFalse(message["unread"])

	def test_read_state_is_tracked_per_audience(self):
		rows = [
			_row(
				name="UPD-3",
				update_source="Internal",
				visible_to_customer=1,
				visible_to_transporter=1,
				customer_read_on="2026-09-02 10:00:00",
			)
		]
		[for_customer] = _thread_payload(rows, audience=AUDIENCE_CUSTOMER)
		[for_transporter] = _thread_payload(rows, audience=AUDIENCE_TRANSPORTER)
		self.assertFalse(for_customer["unread"])
		self.assertTrue(for_transporter["unread"])

	def test_duplicate_rows_from_overlapping_scopes_collapse(self):
		rows = [_row(), _row()]
		self.assertEqual(len(_thread_payload(rows, audience=AUDIENCE_CUSTOMER)), 1)

	def test_messages_are_ordered_oldest_first(self):
		rows = [
			_row(name="UPD-LATE", posted_on="2026-09-03 09:00:00"),
			_row(name="UPD-EARLY", posted_on="2026-09-01 09:00:00"),
		]
		names = [m["name"] for m in _thread_payload(rows, audience=AUDIENCE_CUSTOMER)]
		self.assertEqual(names, ["UPD-EARLY", "UPD-LATE"])


class TestResponseTracking(unittest.TestCase):
	"""Only a party's message is a question CGM owes an answer to."""

	def setUp(self):
		for target, kwargs in (
			(f"{_MODULE}._project_display_ref", {"return_value": "LJL-2606-0468"}),
			("frappe.db.get_value", {"return_value": "Acme Ltd"}),
			("frappe.utils.get_fullname", {"return_value": "A Person"}),
		):
			p = patch(target, **kwargs)
			p.start()
			self.addCleanup(p.stop)

	def test_an_unanswered_party_message_is_awaiting_a_reply(self):
		[message] = _thread_payload(
			[_row(response_status="Open")], audience=AUDIENCE_CUSTOMER
		)
		self.assertTrue(message["awaiting_response"])
		self.assertEqual(message["responded_by_name"], "")

	def test_an_answered_message_names_the_responder(self):
		rows = [
			_row(
				response_status="Answered",
				responded_by="ops@example.com",
				responded_on="2026-09-02 10:00:00",
			)
		]
		[message] = _thread_payload(rows, audience=AUDIENCE_CUSTOMER)
		self.assertFalse(message["awaiting_response"])
		self.assertEqual(message["responded_by_name"], "A Person")
		self.assertEqual(message["responded_on"], "2026-09-02 10:00:00")

	def test_cgm_messages_carry_no_response_state(self):
		rows = [_row(update_source="Internal", response_status=None)]
		[message] = _thread_payload(rows, audience=AUDIENCE_CUSTOMER)
		self.assertFalse(message["awaiting_response"])


class TestPortalAccessGuards(unittest.TestCase):
	"""An internal note must never open in a portal, own shipment or not."""

	def test_customer_cannot_open_an_unpublished_update(self):
		doc = frappe._dict(_row(update_source="Internal", visible_to_customer=0))
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.portal.customer_for_user",
			return_value="CUST-0001",
		):
			self.assertFalse(_customer_can_access_update(doc))

	def test_customer_can_open_a_published_update_on_their_shipment(self):
		doc = frappe._dict(_row(update_source="Internal", visible_to_customer=1))
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.portal.customer_for_user",
			return_value="CUST-0001",
		):
			self.assertTrue(_customer_can_access_update(doc))

	def test_transporter_cannot_open_an_unpublished_update(self):
		doc = frappe._dict(
			_row(update_source="Internal", transporter="SUP-0001", visible_to_transporter=0)
		)
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal"
			".get_transporter_for_user",
			return_value="SUP-0001",
		):
			self.assertFalse(_transporter_can_access_update(doc))

	def test_transporter_can_open_a_published_update_on_their_own_job(self):
		doc = frappe._dict(
			_row(update_source="Internal", transporter="SUP-0001", visible_to_transporter=1)
		)
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal"
			".get_transporter_for_user",
			return_value="SUP-0001",
		):
			self.assertTrue(_transporter_can_access_update(doc))


class TestPublishGuards(unittest.TestCase):
	def test_publishing_needs_an_audience(self):
		with self.assertRaises(frappe.ValidationError):
			post_published_update(
				subject="Vessel berthed",
				message="Discharge tonight.",
				project="PROJ-0001",
				to_customer=False,
				to_transporter=False,
			)

	def test_a_party_source_cannot_be_published_as_cgm(self):
		with self.assertRaises(frappe.ValidationError):
			post_published_update(
				subject="Vessel berthed",
				message="Discharge tonight.",
				project="PROJ-0001",
				to_customer=True,
				update_source="Customer",
			)

	def test_message_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			post_published_update(
				subject="Vessel berthed",
				message="   ",
				project="PROJ-0001",
				to_customer=True,
			)


class TestFeedbackRating(unittest.TestCase):
	"""Ratings are half-star, matching Frappe's Rating control."""

	def _every_half_star(self):
		value = RATING_STEP
		while value <= RATING_MAX:
			yield value
			value += RATING_STEP

	def test_stars_round_trip_through_the_stored_fraction(self):
		for stars in self._every_half_star():
			self.assertEqual(stars_from_rating(rating_from_stars(stars)), stars)

	def test_stored_fraction_converts_back_to_stars(self):
		self.assertEqual(stars_from_rating(0.8), 4)
		self.assertEqual(stars_from_rating(0.9), 4.5)
		self.assertEqual(stars_from_rating(1), 5)

	def test_a_value_already_in_stars_is_left_alone(self):
		self.assertEqual(stars_from_rating(3), 3)
		self.assertEqual(stars_from_rating(3.5), 3.5)

	def test_ratings_snap_to_the_nearest_half(self):
		self.assertEqual(rating_from_stars(4.3), rating_from_stars(4.5))
		self.assertEqual(rating_from_stars(4.1), rating_from_stars(4))

	def test_out_of_range_ratings_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			rating_from_stars(6)
		with self.assertRaises(frappe.ValidationError):
			rating_from_stars(-1)
		with self.assertRaises(frappe.ValidationError):
			rating_from_stars(0)


class TestFeedbackSummary(unittest.TestCase):
	def test_empty_summary(self):
		self.assertEqual(
			feedback_summary([]),
			{"count": 0, "average_stars": 0, "average_display": ""},
		)

	def test_average_across_responses(self):
		summary = feedback_summary([{"stars": 4}, {"stars": 5}, {"stars": 3}])
		self.assertEqual(summary["count"], 3)
		self.assertEqual(summary["average_stars"], 4.0)
		self.assertEqual(summary["average_display"], "4.0/5")
