"""The container status table is the one source for every status list.

Two things are pinned here. First, every status the derivers can return has a
row - a status without one is silently uncoloured, uncounted and missing from
return tracking, which is exactly what happened to transit containers. Second,
the generated lists still say what the hand-written ones did for port
containers, so the refactor changes nothing for them.
"""

import unittest

from frappe.utils import getdate

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	CONTAINER_CLOSED_STATUSES,
	CONTAINER_EMPTY_PENDING_STATUSES,
	CONTAINER_LOCATION_REFRESH_STATUSES,
	CONTAINER_RETURN_OPEN_STATUSES,
	CONTAINER_STATUS_COLOUR,
	CONTAINER_STATUS_TABLE,
	PHASE_AT_DESTINATION,
	PHASE_RELEASED,
	container_status_boot,
	container_statuses_in,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	CLOSED_CONTAINER_STATUSES,
	_derive_tracker_status,
	traffic_light_for_row,
)

TODAY = getdate("2026-09-10")
D = "2026-09-01"

PORT = "Mombasa Port"
TRANSIT_IN = "Transit Import"
TRANSIT_OUT = "Transit Export"

# The nine statuses the port deriver returns - the hand-written lists covered these.
PORT_STATUSES = frozenset(
	{
		"Pending Arrival",
		"Vessel Berthed",
		"Discharged / At Port",
		"Released / In Transit",
		"At Warehouse",
		"Cargo Offloaded",
		"Return Overdue",
		"Empty Returned",
		"Interchange Received",
	}
)

# One fixture per branch of both derivers.
DERIVER_CASES = [
	(PORT, {}),
	(PORT, {"ata": D}),
	(PORT, {"discharging_date": D}),
	(PORT, {"gate_out_date_port": D}),
	(PORT, {"gate_in_date_warehouse": D}),
	(PORT, {"offloading_date": D}),
	(PORT, {"expected_empty_return": "2026-01-01"}),
	(PORT, {"actual_empty_return": D}),
	(PORT, {"interchange_date": D}),
	(TRANSIT_IN, {}),
	(TRANSIT_IN, {"ata": D}),
	(TRANSIT_IN, {"discharging_date": D}),
	(TRANSIT_IN, {"custom_release_date": D}),
	(TRANSIT_IN, {"gate_out_date_port": D}),
	(TRANSIT_IN, {"release_order_number": "RO1"}),
	(TRANSIT_IN, {"loading_slip_number": "LS1"}),
	(TRANSIT_IN, {"delivery_note_number": "DN1"}),
	(TRANSIT_IN, {"c2_number": "C21"}),
	(TRANSIT_IN, {"ecmd_fitted_date": D}),
	(TRANSIT_IN, {"transit_departure_date": D}),
	(TRANSIT_IN, {"border_clearance_date": D}),
	(TRANSIT_IN, {"gate_in_date_warehouse": D}),
	(TRANSIT_IN, {"offloading_date": D}),
	(TRANSIT_IN, {"actual_empty_return": D}),
	(TRANSIT_IN, {"interchange_date": D}),
	(TRANSIT_OUT, {}),
	(TRANSIT_OUT, {"warehouse_loading_date": D}),
]


class TestStatusTableCoverage(unittest.TestCase):
	def test_every_derivable_status_has_a_row(self):
		for mode, fields in DERIVER_CASES:
			status = _derive_tracker_status({"container_mode": mode, **fields}, ref_date=TODAY)
			with self.subTest(mode=mode, fields=fields, status=status):
				self.assertIn(status, CONTAINER_STATUS_COLOUR)

	def test_table_has_no_duplicate_statuses(self):
		names = [row[0] for row in CONTAINER_STATUS_TABLE]
		self.assertEqual(len(names), len(set(names)))


class TestPortParity(unittest.TestCase):
	"""Generated lists must match the old hand-written ones for port containers."""

	def test_closed_statuses_unchanged(self):
		# Drives charge accrual and the metrics refresh - must not move.
		self.assertEqual(set(CLOSED_CONTAINER_STATUSES), {"Empty Returned", "Interchange Received"})
		self.assertEqual(set(CONTAINER_CLOSED_STATUSES), set(CLOSED_CONTAINER_STATUSES))

	def test_open_return_unchanged_for_port(self):
		self.assertEqual(
			CONTAINER_RETURN_OPEN_STATUSES & PORT_STATUSES,
			{"Released / In Transit", "At Warehouse", "Cargo Offloaded", "Return Overdue", "Empty Returned"},
		)

	def test_empty_pending_unchanged_for_port(self):
		self.assertEqual(
			CONTAINER_EMPTY_PENDING_STATUSES & PORT_STATUSES,
			{"Released / In Transit", "At Warehouse", "Cargo Offloaded", "Return Overdue"},
		)

	def test_kpi_buckets_unchanged_for_port(self):
		self.assertEqual(container_statuses_in(PHASE_RELEASED) & PORT_STATUSES, {"Released / In Transit"})
		self.assertEqual(
			container_statuses_in(PHASE_AT_DESTINATION) & PORT_STATUSES, {"At Warehouse", "Cargo Offloaded"}
		)

	def test_location_refresh_unchanged(self):
		self.assertEqual(
			set(CONTAINER_LOCATION_REFRESH_STATUSES),
			{"Released / In Transit", "At Warehouse", "Cargo Offloaded", "Discharged / At Port", "Vessel Berthed"},
		)


class TestTransitNowTracked(unittest.TestCase):
	def test_gated_out_transit_is_an_open_return(self):
		for status in ("Released from Port", "In Transit", "Offloaded at Destination"):
			with self.subTest(status=status):
				self.assertIn(status, CONTAINER_RETURN_OPEN_STATUSES)

	def test_transit_counted_in_project_kpis(self):
		self.assertIn("Released from Port", container_statuses_in(PHASE_RELEASED))
		self.assertIn("Offloaded at Destination", container_statuses_in(PHASE_AT_DESTINATION))


class TestColourRule(unittest.TestCase):
	def test_offloaded_is_orange_until_interchange(self):
		for status in ("Cargo Offloaded", "Offloaded at Destination", "Empty Returned"):
			with self.subTest(status=status):
				self.assertEqual(CONTAINER_STATUS_COLOUR[status], "orange")
		self.assertEqual(CONTAINER_STATUS_COLOUR["Interchange Received"], "green")
		self.assertEqual(CONTAINER_STATUS_COLOUR["Return Overdue"], "red")


class TestTrafficLight(unittest.TestCase):
	def _light(self, **fields):
		return traffic_light_for_row({"container_mode": PORT, **fields})

	def test_interchange_is_cleared(self):
		light = self._light(offloading_date=D, actual_empty_return=D, interchange_date=D)
		self.assertEqual(light["level"], "green")

	def test_empty_returned_awaits_interchange(self):
		"""Used to show green CLEARED while the status pill beside it was orange."""
		light = self._light(offloading_date=D, actual_empty_return=D)
		self.assertEqual(light["level"], "amber")
		self.assertEqual(light["css"], "cgm-tl-amber")


class TestBootPayload(unittest.TestCase):
	def test_boot_mirrors_table(self):
		boot = container_status_boot()
		self.assertEqual(boot["order"], [row[0] for row in CONTAINER_STATUS_TABLE])
		self.assertTrue(boot["statuses"]["Released from Port"]["return_open"])
		self.assertTrue(boot["statuses"]["Empty Returned"]["closed"])
		self.assertEqual(boot["statuses"]["Empty Returned"]["colour"], "orange")
