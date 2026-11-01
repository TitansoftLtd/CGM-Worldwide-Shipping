"""Every container status the app can produce must have a colour.

The list, the form, the tracking report and the Ops Board all read
`frappe.boot.cgm_container_statuses`, built from CONTAINER_STATUS_TABLE. A status the
derivers start returning that has no row there is drawn grey everywhere, silently, which
is what makes a container with a problem impossible to spot while skimming the list.
"""

import unittest

from cgm_shipping.cgm_worldwide_shipping.customizations import constants as c


class TestContainerStatusColours(unittest.TestCase):
	def setUp(self):
		self.boot = c.container_status_boot()

	def test_boot_carries_a_colour_for_every_table_row(self):
		for status, _phase, colour, _pill in c.CONTAINER_STATUS_TABLE:
			with self.subTest(status=status):
				self.assertEqual(self.boot["statuses"][status]["colour"], colour)

	def test_every_derived_status_constant_is_in_the_table(self):
		"""A constant the derivers return but the table omits would be grey."""
		derived = [
			c.CONTAINER_STATUS_PENDING_ARRIVAL, c.CONTAINER_STATUS_VESSEL_BERTHED,
			c.CONTAINER_STATUS_DISCHARGED_AT_PORT, c.CONTAINER_STATUS_RELEASED_IN_TRANSIT,
			c.CONTAINER_STATUS_AT_WAREHOUSE, c.CONTAINER_STATUS_CARGO_OFFLOADED,
			c.CONTAINER_STATUS_EMPTY_RETURNED, c.CONTAINER_STATUS_INTERCHANGE,
			c.CONTAINER_STATUS_RETURN_OVERDUE,
		]
		missing = [s for s in derived if s not in self.boot["statuses"]]
		self.assertEqual(missing, [])

	def test_the_stages_the_client_reads_keep_their_distinct_colours(self):
		"""At port, on the road and closed must not look alike."""
		self.assertEqual(self.boot["statuses"][c.CONTAINER_STATUS_DISCHARGED_AT_PORT]["colour"], "yellow")
		self.assertEqual(self.boot["statuses"][c.CONTAINER_STATUS_RELEASED_IN_TRANSIT]["colour"], "orange")
		self.assertEqual(self.boot["statuses"][c.CONTAINER_STATUS_INTERCHANGE]["colour"], "green")

	def test_return_overdue_stays_red(self):
		"""It is a live demurrage alarm and must not blend in."""
		self.assertEqual(self.boot["statuses"][c.CONTAINER_STATUS_RETURN_OVERDUE]["colour"], "red")

	def test_the_order_list_covers_every_status(self):
		self.assertEqual(set(self.boot["order"]), set(self.boot["statuses"]))
