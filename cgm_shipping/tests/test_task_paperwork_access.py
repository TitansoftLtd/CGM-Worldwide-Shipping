"""A shipment's paperwork opens for whoever works the shipment.

Task rows are scoped by department. That is right for the Task list, and wrong for
the documents hanging off them: every permit, IDF and entry on a shipment sits on a
Declaration task, so a field officer - the person who carries those papers to the
port - saw an empty list and was told the documents did not exist. Going looking for
one, Frappe refused the download too, because a private file is guarded by whether
you can read its parent task (42 of 2,304 task files on production are private).

So reading a task's paperwork is no longer a department question. Finance's payment
evidence is, and stays behind the task permission.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import permissions as perm


def _task(role="Permit Application", project="PROJ-1"):
    return frappe._dict(custom_task_role=role, project=project, name="TASK-1")


def _readable(doc, user=None, project_ok=True):
    with patch.object(frappe, "has_permission", return_value=project_ok):
        return perm.task_paperwork_readable(doc, user)


class TestWhoCanOpenTheShipmentPaperwork(unittest.TestCase):
    def test_someone_who_can_open_the_shipment_can_read_its_permit_task(self):
        self.assertTrue(_readable(_task()))

    def test_someone_who_cannot_open_the_shipment_cannot(self):
        """The shipment is still the gate. This widens nothing beyond it."""
        self.assertFalse(_readable(_task(), project_ok=False))

    def test_a_task_with_no_shipment_is_refused(self):
        self.assertFalse(_readable(_task(project=None)))

    def test_a_row_that_is_not_a_document_is_refused(self):
        self.assertFalse(_readable("not a doc"))


class TestFinanceEvidenceStaysWithFinance(unittest.TestCase):
    """A POP or a bank receipt is not part of the pack the job is run from."""

    def test_a_finance_payment_task_is_refused(self):
        self.assertFalse(_readable(_task(role="Finance Payment")))

    def test_a_permit_finance_task_is_refused(self):
        self.assertFalse(_readable(_task(role="Permit Finance")))

    def test_every_other_role_is_allowed(self):
        for role in ("Permit Application", "Application", "Document", "Standard"):
            with self.subTest(role=role):
                self.assertTrue(_readable(_task(role=role)))


class TestItOpensADocumentNotAList(unittest.TestCase):
    def test_only_read_is_granted(self):
        """Editing a task outside your department is still refused."""
        doc = _task()
        with (
            patch.object(perm, "user_bypasses_sea_task_department_filter", return_value=False),
            patch.object(perm, "is_clearance_department_restricted_task", return_value=True),
            patch.object(perm, "user_can_access_sea_task", return_value=False),
            patch.object(perm, "task_paperwork_readable", return_value=True),
        ):
            self.assertTrue(perm.has_permission(doc, ptype="read"))
            self.assertTrue(perm.has_permission(doc, ptype=None))
            for ptype in ("write", "create", "delete", "submit", "cancel"):
                with self.subTest(ptype=ptype):
                    self.assertFalse(perm.has_permission(doc, ptype=ptype))

    def test_the_list_query_is_untouched(self):
        """get_permission_query_conditions still scopes the Task list by department.

        This grant is per document on purpose. Loosening the list as well would put
        every department's tasks in front of everyone, which is what that scoping
        exists to prevent.
        """
        import inspect

        src = inspect.getsource(perm.get_permission_query_conditions)
        self.assertNotIn("task_paperwork_readable", src)

    def test_the_department_rule_still_answers_first(self):
        """Someone already entitled by department is unaffected by any of this."""
        doc = _task()
        with (
            patch.object(perm, "user_bypasses_sea_task_department_filter", return_value=False),
            patch.object(perm, "is_clearance_department_restricted_task", return_value=True),
            patch.object(perm, "user_can_access_sea_task", return_value=True),
            patch.object(perm, "task_paperwork_readable") as paperwork,
        ):
            self.assertTrue(perm.has_permission(doc, ptype="read"))
        paperwork.assert_not_called()


class TestItMatchesThePanel(unittest.TestCase):
    """The list and the download must agree, or files show and then refuse to open."""

    def test_both_hold_back_the_same_roles(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations import (
            project_task_documents as ptd,
        )

        self.assertEqual(
            tuple(perm.FINANCE_TASK_ROLES), tuple(ptd.FINANCE_TASK_ROLES)
        )
