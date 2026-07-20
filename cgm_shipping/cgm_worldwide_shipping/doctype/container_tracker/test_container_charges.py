# Copyright (c) 2026, Titansoft Limited and Contributors

from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from cgm_shipping.cgm_worldwide_shipping.customizations.container_charges import (
	CHARGE_TYPE_DEMURRAGE,
	CHARGE_TYPE_KPA_PORT,
	compute_container_charge_amounts,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	compute_container_metrics,
)


class TestContainerCharges(IntegrationTestCase):
	def test_manual_rates_drive_accrued_amounts(self):
		data = {
			"demurrage_daily_rate": 40,
			"kpa_port_daily_rate": 75,
			"shipping_line": "COSCO",
		}
		metrics = {"demurrage_days": 4, "kpa_days": 2}
		amounts = compute_container_charge_amounts(data, metrics)
		self.assertEqual(flt(amounts["demurrage_amount"]), 160)
		self.assertEqual(flt(amounts["kpa_amount"]), 150)
		self.assertEqual(flt(amounts["demurrage_daily_rate"]), 40)
		self.assertEqual(flt(amounts["kpa_port_daily_rate"]), 75)

	def test_adjustments_are_included(self):
		data = {
			"demurrage_daily_rate": 10,
			"demurrage_amount_adjustment": 25,
			"kpa_port_daily_rate": 5,
			"kpa_amount_adjustment": -3,
		}
		metrics = {"demurrage_days": 3, "kpa_days": 4}
		amounts = compute_container_charge_amounts(data, metrics)
		self.assertEqual(flt(amounts["demurrage_amount"]), 55)
		self.assertEqual(flt(amounts["kpa_amount"]), 17)

	def test_metrics_include_charge_amounts(self):
		data = {
			"free_days_start_date": "2026-06-01",
			"free_days_end_date": "2026-06-05",
			"kpa_free_days_end_date": "2026-06-04",
			"gate_out_date_port": "2026-06-10",
			"demurrage_daily_rate": 20,
			"kpa_port_daily_rate": 30,
		}
		metrics = compute_container_metrics(data)
		self.assertGreater(metrics["demurrage_days"], 0)
		self.assertGreater(metrics["kpa_days"], 0)
		self.assertGreater(flt(metrics["demurrage_amount"]), 0)
		self.assertGreater(flt(metrics["kpa_amount"]), 0)

	def test_charge_type_labels(self):
		self.assertEqual(CHARGE_TYPE_DEMURRAGE, "Demurrage/Detention")
		self.assertEqual(CHARGE_TYPE_KPA_PORT, "KPA Port")
