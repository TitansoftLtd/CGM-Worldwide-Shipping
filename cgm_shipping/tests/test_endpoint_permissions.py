"""API methods that write data check the caller's permissions.

Found in a sweep: any signed-in user (portal customers included) could rewrite
every open Container Tracker, or read an Opportunity's intake readiness.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import container_tracker as tracker_api
from cgm_shipping.cgm_worldwide_shipping.customizations import opportunity_intake_wizard as wizard
from cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker import container_tracker as tracker_job


class TestEndpointPermissions(unittest.TestCase):
	def test_daily_metrics_job_is_not_an_api_method(self):
		self.assertNotIn(tracker_job.refresh_open_container_metrics, frappe.whitelisted)

	def test_metrics_refresh_needs_write_access(self):
		with (
			patch.object(frappe, "has_permission", side_effect=frappe.PermissionError),
			patch.object(tracker_job, "refresh_open_container_metrics") as job,
			self.assertRaises(frappe.PermissionError),
		):
			tracker_api.refresh_open_project_container_metrics()
		job.assert_not_called()

	def test_intake_wizard_needs_read_access_to_the_opportunity(self):
		doc = MagicMock()
		doc.check_permission.side_effect = frappe.PermissionError
		with (
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe, "get_doc", return_value=doc),
			patch.object(wizard, "sync_opportunity_intake_stage") as sync,
			self.assertRaises(frappe.PermissionError),
		):
			wizard.get_intake_wizard_context("CRM-OPP-TEST")
		sync.assert_not_called()
