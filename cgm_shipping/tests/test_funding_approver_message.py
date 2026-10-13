"""The self-approval block names the role that is waiting.

The message used to end with "Ask another approver to review it", which left the
reader to work out who that was. On a site with Finance User, Finance Manager,
Accounts User and Funding Approver all in play, that is not obvious, and the
person being blocked is usually the one least able to find out.

It names the role and not the people. A refusal message is the wrong place to
publish who holds a finance role, and any such list goes stale as soon as somebody
joins or leaves. The only thing read about the holders is whether anybody else
exists at all, so a request nobody can approve says so.

The role is read from the live workflow rather than hardcoded, because the states
and the roles on them are site configuration.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import funding_workflow as FW


def _workflow(transitions):
    return frappe._dict(transitions=[frappe._dict(t) for t in transitions])


class TestApproverRole(unittest.TestCase):
    def test_the_role_comes_from_the_approve_transition(self):
        wf = _workflow([
            {"action": "Submit", "next_state": "Pending", "allowed": "Finance User"},
            {"action": "Approve", "next_state": "Approved", "allowed": "Funding Approver"},
        ])
        self.assertEqual(FW.funding_approver_role(wf), "Funding Approver")

    def test_a_site_that_renamed_the_role_gets_its_own_name(self):
        wf = _workflow([
            {"action": "Approve", "next_state": "Approved", "allowed": "Head of Finance"},
        ])
        self.assertEqual(FW.funding_approver_role(wf), "Head of Finance")

    def test_no_approve_transition_yields_nothing(self):
        wf = _workflow([{"action": "Submit", "next_state": "Pending", "allowed": "Finance User"}])
        self.assertEqual(FW.funding_approver_role(wf), "")

    def test_a_site_with_no_funding_workflow_does_not_raise(self):
        """`workflow=None` means "load the live one", as elsewhere in this module,
        so a site genuinely without the workflow is simulated at the loader."""
        with patch.object(FW, "load_funding_request_workflow", return_value=None):
            self.assertEqual(FW.funding_approver_role(), "")

    def test_it_matches_the_live_workflow(self):
        if not frappe.db.exists("Workflow", "CGM Funding Request Approval"):
            self.skipTest("funding workflow not on this site")
        self.assertEqual(FW.funding_approver_role(), "Funding Approver")


class TestAnotherApproverExists(unittest.TestCase):
    """A yes/no, never a list of names."""

    ROLE = "Funding Approver"

    def test_the_blocked_person_does_not_count_as_another_approver(self):
        """Otherwise the only holder approving their own request reads as fine."""
        with patch.object(frappe, "get_all", return_value=["solo@example.com"]), patch.object(
            frappe.db, "get_value", return_value=1
        ):
            self.assertFalse(
                FW.another_approver_exists(self.ROLE, exclude="solo@example.com")
            )
            self.assertTrue(FW.another_approver_exists(self.ROLE, exclude="someone@else.com"))

    def test_administrator_is_never_counted(self):
        """Nobody chases Administrator to approve a payment."""
        with patch.object(frappe, "get_all", return_value=["Administrator"]), patch.object(
            frappe.db, "get_value", return_value=1
        ):
            self.assertFalse(FW.another_approver_exists(self.ROLE))

    def test_disabled_users_are_not_counted(self):
        with patch.object(frappe, "get_all", return_value=["gone@example.com"]), patch.object(
            frappe.db, "get_value", return_value=0
        ):
            self.assertFalse(FW.another_approver_exists(self.ROLE))

    def test_an_unknown_role_has_nobody(self):
        self.assertFalse(FW.another_approver_exists("No Such Role Here"))

    def test_a_blank_role_has_nobody(self):
        self.assertFalse(FW.another_approver_exists(""))

    def test_it_returns_a_boolean_not_a_list_of_people(self):
        """The point of the change: the message must not be able to name anyone."""
        with patch.object(frappe, "get_all", return_value=["a@x.com", "b@x.com"]), patch.object(
            frappe.db, "get_value", return_value=1
        ):
            result = FW.another_approver_exists(self.ROLE)
        self.assertIsInstance(result, bool)

    def test_the_live_role_has_someone_other_than_the_raiser(self):
        if not frappe.db.exists("Role", self.ROLE):
            self.skipTest("role not on this site")
        self.assertTrue(FW.another_approver_exists(self.ROLE, exclude="nobody@example.com"))


class TestTheMessageNamesNoOne(unittest.TestCase):
    """Guards the decision, so a future change cannot quietly reintroduce names."""

    def test_the_block_mentions_the_role_and_no_user(self):
        from cgm_shipping.cgm_worldwide_shipping.doctype.funding_request.funding_request import (
            FundingRequest,
        )

        if not frappe.db.exists("Workflow", "CGM Funding Request Approval"):
            self.skipTest("funding workflow not on this site")

        raiser = "approver-message-test@example.com"

        class _Stub:
            workflow_state = "Approved"
            submitted_by = raiser
            approved_by = raiser

            def is_new(self):
                return False

            def get_doc_before_save(self):
                return None

        frappe.message_log = []
        with self.assertRaises(frappe.ValidationError):
            FundingRequest._block_self_approval(_Stub())
        message = (frappe.message_log or [{}])[-1].get("message", "")

        self.assertIn("Funding Approver", message)
        # No other holder of the role may appear in it.
        holders = frappe.get_all(
            "Has Role", filters={"role": "Funding Approver", "parenttype": "User"}, pluck="parent"
        )
        for user in holders:
            full_name = frappe.db.get_value("User", user, "full_name")
            if full_name and full_name != "Administrator":
                self.assertNotIn(full_name, message, f"{full_name} leaked into the message")
            self.assertNotIn(user, message.replace(raiser, ""), f"{user} leaked into the message")
