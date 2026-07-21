# Copyright (c) 2026, Titansoft Limited and Contributors
# See license.txt

from frappe.tests import IntegrationTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	AWB_TO_OPPORTUNITY_FIELDS,
	apply_awb_fields_to_doc,
	awb_propagation_payload,
)


class TestAirWaybillSync(IntegrationTestCase):
	def test_awb_to_opportunity_field_map_covers_awb_doctype_fields(self):
		awb_fields = {
			"client_reference_no",
			"description",
			"airline",
			"eta",
			"etd",
			"weight_uom",
			"net_weight",
			"gross_weight",
			"port_of_loading",
			"port_of_discharge",
		}
		mapped = {src for src, _dest in AWB_TO_OPPORTUNITY_FIELDS}
		self.assertEqual(mapped, awb_fields)

	def test_awb_propagation_payload_includes_opportunity_fieldnames(self):
		class FakeAWB:
			name = "AWB-001"
			shipment_type = None

			def get(self, fieldname):
				values = {
					"client_reference_no": "REF-1",
					"description": "Electronics",
					"airline": "KQ",
					"eta": "2026-08-01",
					"etd": "2026-07-30",
					"weight_uom": "Kg",
					"net_weight": 100,
					"gross_weight": 120,
					"port_of_loading": "NBO",
					"port_of_discharge": "DXB",
				}
				return values.get(fieldname)

		payload = awb_propagation_payload(FakeAWB())
		self.assertEqual(payload["awb_name"], "AWB-001")
		self.assertEqual(payload["custom_client_refrence_no"], "REF-1")
		self.assertEqual(payload["custom_airline"], "KQ")
		self.assertEqual(payload["custom_port_of_loading"], "NBO")

	def test_build_awb_seed_from_opportunity(self):
		class FakeMeta:
			def has_field(self, fieldname):
				return fieldname.startswith("custom_")

		class FakeOpp:
			name = "CRM-OPP-2026-00001"
			opportunity_from = "Customer"
			meta = FakeMeta()
			_values = {
				"party_name": "Ducorp Trading Kenya Limited",
				"custom_shipment_type": "Air Import",
				"custom_client_refrence_no": "987654re9u",
				"custom_description_of_goods": "Electronics",
				"custom_airline": "KQ",
				"custom_eta": "2026-08-01",
				"custom_etd": "2026-07-30",
			}

			def get(self, fieldname):
				return self._values.get(fieldname)

		from cgm_shipping.cgm_worldwide_shipping.doctype.air_waybill.air_waybill import (
			build_awb_seed_from_opportunity,
		)

		with self.patch(
			"cgm_shipping.cgm_worldwide_shipping.doctype.air_waybill.air_waybill.is_valid_opportunity_link",
			return_value=True,
		):
			seed = build_awb_seed_from_opportunity(FakeOpp())

		self.assertEqual(seed["customer"], "Ducorp Trading Kenya Limited")
		self.assertEqual(seed["client_reference_no"], "987654re9u")
		self.assertEqual(seed["airline"], "KQ")
		self.assertEqual(seed["linked_opportunity"], "CRM-OPP-2026-00001")

	def test_apply_awb_fields_skips_link_when_awb_not_saved(self):
		class FakeMeta:
			def has_field(self, fieldname):
				return fieldname.startswith("custom_")

		class FakeOpp:
			meta = FakeMeta()
			_values = {}

			def get(self, fieldname):
				return self._values.get(fieldname)

			def set(self, fieldname, value):
				self._values[fieldname] = value

		class FakeAWB:
			name = "987654qwdqw"
			shipment_type = None

			def get(self, fieldname):
				return {"client_reference_no": "REF-1"}.get(fieldname)

		from cgm_shipping.cgm_worldwide_shipping.doctype.air_waybill.air_waybill import (
			apply_awb_fields_to_opportunity,
		)

		opp = FakeOpp()
		with self.patch("frappe.db.exists", return_value=False):
			apply_awb_fields_to_opportunity(opp, FakeAWB())

		self.assertIsNone(opp.get("custom_air_waybill"))
		self.assertEqual(opp.get("custom_client_refrence_no"), "REF-1")

	def test_apply_awb_fields_to_opportunity_doc(self):
		class FakeMeta:
			def has_field(self, fieldname):
				return fieldname.startswith("custom_")

			def get_field(self, fieldname):
				class DF:
					fieldtype = "Data"

				if fieldname in {"custom_gross_weight", "custom_net_weight"}:
					DF.fieldtype = "Float"
				return DF

		class FakeOpp:
			meta = FakeMeta()
			_values = {}

			def get(self, fieldname):
				return self._values.get(fieldname)

			def set(self, fieldname, value):
				self._values[fieldname] = value

		class FakeAWB:
			shipment_type = None

			def get(self, fieldname):
				return {
					"client_reference_no": "REF-99",
					"description": "Machinery",
					"airline": "ET",
					"eta": "2026-09-01",
					"etd": "2026-08-28",
					"net_weight": 50,
					"gross_weight": 55,
				}.get(fieldname)

		opp = FakeOpp()
		self.assertTrue(apply_awb_fields_to_doc(opp, FakeAWB()))
		self.assertEqual(opp.get("custom_client_refrence_no"), "REF-99")
		self.assertEqual(opp.get("custom_airline"), "ET")
		self.assertEqual(opp.get("custom_mode_of_transport"), "Air")
