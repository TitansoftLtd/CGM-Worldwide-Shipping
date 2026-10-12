"""Container status progression and its colour.

Rule: unchanged before offloading, orange once the offloading date is recorded,
green only when the interchange is confirmed. Return Overdue stays red.

The colour follows the derived status, so these pin the derivation too - a
transit container used to stop at "Offloaded at Destination" for good, which
meant it could never turn green.
"""

import unittest

from frappe.utils import getdate

from cgm_shipping.cgm_worldwide_shipping.customizations.container_ops_board import _STATUS_PILL
from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	_derive_tracker_status,
)

TODAY = getdate("2026-09-10")


def _status(**fields):
	return _derive_tracker_status(fields, ref_date=TODAY)


class TestContainerStatusProgression(unittest.TestCase):
	def test_port_import_offloaded(self):
		self.assertEqual(
			_status(container_mode="Mombasa Port", offloading_date="2026-09-01"),
			"Cargo Offloaded",
		)

	def test_port_import_interchange(self):
		self.assertEqual(
			_status(
				container_mode="Mombasa Port",
				offloading_date="2026-09-01",
				actual_empty_return="2026-09-03",
				interchange_date="2026-09-05",
			),
			"Interchange Received",
		)

	def test_transit_offloaded(self):
		self.assertEqual(
			_status(container_mode="Transit Import", offloading_date="2026-09-01"),
			"Offloaded at Destination",
		)

	def test_transit_empty_return_outranks_offloading(self):
		self.assertEqual(
			_status(
				container_mode="Transit Import",
				offloading_date="2026-09-01",
				actual_empty_return="2026-09-04",
			),
			"Empty Returned",
		)

	def test_transit_reaches_interchange(self):
		"""Previously stuck on Offloaded at Destination forever."""
		self.assertEqual(
			_status(
				container_mode="Transit Import",
				offloading_date="2026-09-01",
				actual_empty_return="2026-09-04",
				interchange_date="2026-09-06",
			),
			"Interchange Received",
		)

	def test_transit_before_offloading_unchanged(self):
		self.assertEqual(
			_status(container_mode="Transit Import", gate_out_date_port="2026-08-28"),
			"Released from Port",
		)


class TestOpsBoardPills(unittest.TestCase):
	"""Ops board tones: 'active' is orange, 'success' is green."""

	def test_offloaded_statuses_are_orange(self):
		for status in ("Cargo Offloaded", "Offloaded at Destination", "Empty Returned"):
			with self.subTest(status=status):
				self.assertEqual(_STATUS_PILL[status], "active")

	def test_interchange_is_green(self):
		self.assertEqual(_STATUS_PILL["Interchange Received"], "success")

	def test_overdue_stays_red(self):
		self.assertEqual(_STATUS_PILL["Return Overdue"], "danger")

	def test_before_offloading_unchanged(self):
		self.assertEqual(_STATUS_PILL["Released / In Transit"], "primary")
		self.assertEqual(_STATUS_PILL["At Warehouse"], "primary")
		self.assertEqual(_STATUS_PILL["Discharged / At Port"], "warning")
