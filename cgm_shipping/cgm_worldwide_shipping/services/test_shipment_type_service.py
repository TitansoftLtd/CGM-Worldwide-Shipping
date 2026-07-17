# Copyright (c) 2026, Titansoft Limited and Contributors
from frappe.tests import IntegrationTestCase

from cgm_shipping.cgm_worldwide_shipping.services.shipment_type_service import (
	derive_transport_documents_from_flags,
	get_allowed_transport_documents,
)


class TestShipmentTypeService(IntegrationTestCase):
	def test_air_export_derives_air_waybill_only(self):
		rows = derive_transport_documents_from_flags(
			{
				"default_mode_of_transport": "Air",
				"is_outbound": 1,
				"uses_export_documents": 1,
				"primary_transport_document": "Air Waybill",
			}
		)
		labels = {row["transport_document"] for row in rows}
		self.assertEqual(labels, {"Air Waybill"})

	def test_air_export_respects_explicit_transport_documents_only(self):
		if not self.db_exists("Shipment Type", "Air Export"):
			self.skipTest("Air Export Shipment Type not installed")

		allowed = get_allowed_transport_documents("Air Export")
		labels = [row["transport_document"] for row in allowed]
		self.assertEqual(labels, ["Air Waybill"])
		self.assertTrue(all(row["is_required_for_start"] for row in allowed))
