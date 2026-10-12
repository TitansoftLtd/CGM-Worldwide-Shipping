"""Role checks read the roles configured in CGM Shipping Settings, not a list in code.

Hardcoded role lists had drifted from the configured ones: they named roles that
do not exist on the site ("Operations User", "CGM Documentation") and missed the
ones that do. Adding a role in Settings must be enough to grant access.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading import bill_of_lading

PERMISSIONS = "cgm_shipping.cgm_worldwide_shipping.customizations.permissions"


class TestDepositRefundRoles(unittest.TestCase):
	def _can_manage(self, user_roles, configured):
		with (
			patch(f"{PERMISSIONS}.configured_finance_roles", return_value=frozenset(configured)),
			patch.object(frappe, "get_roles", return_value=list(user_roles)),
		):
			return bill_of_lading._user_can_manage_deposit_refund()

	def test_configured_finance_role_grants(self):
		self.assertTrue(self._can_manage(["Treasury Clerk"], {"Treasury Clerk"}))

	def test_unconfigured_role_does_not(self):
		"""Finance Manager used to be hardcoded; it now counts only if configured."""
		self.assertFalse(self._can_manage(["Finance Manager"], {"Accounts User"}))

	def test_system_manager_always_can(self):
		self.assertTrue(self._can_manage(["System Manager"], set()))
