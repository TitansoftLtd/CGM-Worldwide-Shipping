"""The shipment status table is the one source for shipment status lists and colours.

The status chart, the customer milestones, the portal colours and the Desk
colours each used to be written out separately, and the two colour schemes
already disagreed on 12 of 17 statuses. They are now columns of one table.
The expected values below are what each copy produced before, so moving them
into the table changed nothing anyone sees.
"""

import json
import os
import unittest

import cgm_shipping
from cgm_shipping.cgm_worldwide_shipping.customizations import portal
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	SHIPMENT_MILESTONES,
	SHIPMENT_STATUS_TABLE,
	SHIPMENT_STATUSES,
	shipment_status_boot,
	shipment_status_tone,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
	TEMPLATE_DEFINITIONS,
)

PROJECT_CUSTOM_JSON = os.path.join(
	os.path.dirname(cgm_shipping.__file__), "cgm_worldwide_shipping", "custom", "project.json"
)

# What cgm_status_field.js tone_for_shipment returned before the table.
DESK_TONES_BEFORE = {
	"Draft": "muted",
	"Documents Received": "primary",
	"UCR Applied": "primary",
	"UCR Paid": "primary",
	"Pre-clearance": "primary",
	"Client Inspection": "info",
	"In Transit": "info",
	"Final Docs Received": "primary",
	"Entry Lodged": "primary",
	"Line Paid & DO Lodged": "warning",
	"Entry Paid": "warning",
	"Post-clearance": "primary",
	"Field Clearance": "primary",
	"KPA Paid": "warning",
	"In Delivery": "info",
	"Containers Returned": "primary",
	"Completed": "success",
}

# What portal.status_tone returned before the table.
PORTAL_TONES_BEFORE = {status: "active" for status in DESK_TONES_BEFORE} | {
	"Draft": "muted",
	"In Transit": "info",
	"In Delivery": "info",
	"Containers Returned": "primary",
	"Completed": "success",
}

MILESTONES_BEFORE = [
	("Booking & Documents", ("Draft", "Documents Received", "UCR Applied", "UCR Paid")),
	("Pre-Clearance", ("Pre-clearance", "Client Inspection")),
	("In Transit", ("In Transit",)),
	("Arrival & Customs Entry", ("Final Docs Received", "Entry Lodged", "Line Paid & DO Lodged", "Entry Paid")),
	("Clearance", ("Post-clearance", "Field Clearance", "KPA Paid")),
	("Delivery", ("In Delivery", "Containers Returned", "Completed")),
]

GATE_TABLES = {d["template_name"]: d["gates"] for d in TEMPLATE_DEFINITIONS if d.get("gates")}


def _select_options():
	with open(PROJECT_CUSTOM_JSON) as f:
		for field in json.load(f)["custom_fields"]:
			if field["fieldname"] == "custom_shipment_status":
				return field["options"].split("\n")
	raise AssertionError("custom_shipment_status is not in custom/project.json")


class TestTableMatchesTheField(unittest.TestCase):
	def test_select_options_follow_the_table(self):
		self.assertEqual(_select_options(), list(SHIPMENT_STATUSES))

	def test_no_duplicate_statuses(self):
		self.assertEqual(len(SHIPMENT_STATUSES), len(set(SHIPMENT_STATUSES)))

	def test_every_gate_state_is_a_status(self):
		for flow, gates in GATE_TABLES.items():
			for row in gates:
				with self.subTest(flow=flow, state=row["shipment_workflow_state"]):
					self.assertIn(row["shipment_workflow_state"], SHIPMENT_STATUSES)


class TestMilestones(unittest.TestCase):
	def test_every_status_has_a_known_milestone(self):
		for status, milestone, *_ in SHIPMENT_STATUS_TABLE:
			with self.subTest(status=status):
				self.assertIn(milestone, SHIPMENT_MILESTONES)

	def test_milestones_are_contiguous_in_chart_order(self):
		"""The portal stepper assumes each milestone owns one slice of the chart."""
		seen = [row[1] for row in SHIPMENT_STATUS_TABLE]
		collapsed = [m for i, m in enumerate(seen) if i == 0 or seen[i - 1] != m]
		self.assertEqual(collapsed, list(SHIPMENT_MILESTONES))

	def test_portal_milestones_unchanged(self):
		self.assertEqual(portal.MILESTONES, MILESTONES_BEFORE)
		self.assertEqual(portal.SHIPMENT_STAGES, list(DESK_TONES_BEFORE))


class TestTonesUnchanged(unittest.TestCase):
	def test_desk_tones(self):
		self.assertEqual({s: shipment_status_tone(s) for s in SHIPMENT_STATUSES}, DESK_TONES_BEFORE)

	def test_portal_tones(self):
		self.assertEqual({s: portal.status_tone(s) for s in SHIPMENT_STATUSES}, PORTAL_TONES_BEFORE)

	def test_blank_and_unknown(self):
		for portal_side in (False, True):
			self.assertEqual(shipment_status_tone(None, portal=portal_side), "muted")
			self.assertEqual(shipment_status_tone("Manifest Requested", portal=portal_side), "active")

	def test_boot_mirrors_table(self):
		boot = shipment_status_boot()
		self.assertEqual(boot["order"], list(SHIPMENT_STATUSES))
		self.assertEqual({s: v["tone"] for s, v in boot["statuses"].items()}, DESK_TONES_BEFORE)
		self.assertEqual(boot["statuses"]["Entry Paid"]["milestone"], "Arrival & Customs Entry")
