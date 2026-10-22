"""Verifying a permit receipt is Finance's job, and only a new tick is guarded.

Finance could not tick **Receipt Verified** on a permit row at all, and once any
row had been verified they could not save the task again for any reason. Two
separate faults in the same guard:

* It asked for the **Upload Receipt** responsibility. On permits that belongs to
  Declaration - the declarant downloads the receipt from the issuing body's
  portal - so the guard demanded the uploader's own permission before anyone
  could check the uploader's work. Verification belongs with Finance, exactly as
  the invoice check beside it already had it.
* It tested whether the flag *was set* rather than whether it had just *changed*,
  so an existing tick blocked every later save of the task by anyone outside that
  role group, however unrelated the edit.
"""

import unittest

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import workflow as W
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_PERMITS_FIELD
from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
    ACTION_UPLOAD_RECEIPT,
    ACTION_VERIFY_INVOICE,
    FLOW_PERMIT,
    role_groups_for,
    user_has_responsibility,
)


def _rows(*specs):
    return [frappe._dict(spec, name=f"row{i}") for i, spec in enumerate(specs)]


class _Task(frappe._dict):
    """A permit task with a previous version, as the guard sees it on save."""

    def __init__(self, rows, previous=None):
        super().__init__()
        self.name = "TASK-PERMIT-TEST"
        self[TASK_PERMITS_FIELD] = rows
        self._previous = previous
        self.meta = frappe._dict(has_field=lambda _f: True)

    def get_doc_before_save(self):
        if self._previous is None:
            return None
        doc = frappe._dict()
        doc[TASK_PERMITS_FIELD] = self._previous
        return doc


class _AsFinanceTask:
    """Treat the stub as a finance permit task for the duration of a test."""

    def __enter__(self):
        self._app = W.is_permit_application_task_doc
        self._fin = W.is_permit_finance_task_doc
        W.is_permit_application_task_doc = lambda _t: False
        W.is_permit_finance_task_doc = lambda _t: True

    def __exit__(self, *exc):
        W.is_permit_application_task_doc = self._app
        W.is_permit_finance_task_doc = self._fin


class TestWhoOwnsTheAction(unittest.TestCase):
    """The responsibilities the guard should and should not be asking about."""

    def test_uploading_a_permit_receipt_belongs_to_declaration(self):
        """Which is why demanding it for a verification locked Finance out."""
        self.assertEqual(sorted(role_groups_for(FLOW_PERMIT, ACTION_UPLOAD_RECEIPT)), ["Declaration"])

    def test_verifying_belongs_to_finance(self):
        self.assertEqual(sorted(role_groups_for(FLOW_PERMIT, ACTION_VERIFY_INVOICE)), ["Finance"])


class TestReceiptVerifiedGuard(unittest.TestCase):
    FINANCE_ROLES = {"Finance User", "Finance Manager", "Accounts User", "Accounts Manager"}

    @classmethod
    def setUpClass(cls):
        cls.finance = cls._user_with("Finance User", without={"System Manager", "Declarant"})
        cls.outsider = cls._user_without({"System Manager", "Declarant"} | cls.FINANCE_ROLES)

    @staticmethod
    def _user_with(role, without):
        holders = {
            u
            for u in set(frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent"))
            if frappe.db.get_value("User", u, "enabled") and u != "Administrator"
        }
        for user in sorted(holders):
            if not (set(frappe.get_roles(user)) & without):
                return user
        return None

    @staticmethod
    def _user_without(roles):
        """Any enabled person who holds none of these - the control's target."""
        for user in sorted(frappe.get_all("User", filters={"enabled": 1}, pluck="name")):
            if user in ("Administrator", "Guest"):
                continue
            if not (set(frappe.get_roles(user)) & roles):
                return user
        return None

    def tearDown(self):
        frappe.set_user("Administrator")

    def _check(self, task, as_user):
        frappe.set_user(as_user)
        with _AsFinanceTask():
            W.enforce_receipt_verified_permission(task)

    def test_finance_may_tick_receipt_verified(self):
        """The reported bug: Finance was refused on their own payment task."""
        if not self.finance:
            self.skipTest("no Finance user without Declarant on this site")
        task = _Task(
            _rows({"permit_type": "DVS", "receipt_verified": 1}),
            previous=_rows({"permit_type": "DVS", "receipt_verified": 0}),
        )
        self._check(task, self.finance)

    def test_an_existing_tick_does_not_block_an_unrelated_save(self):
        """Nothing changed on this save, so nothing should be checked."""
        if not self.finance:
            self.skipTest("no Finance user without Declarant on this site")
        task = _Task(
            _rows({"permit_type": "DVS", "receipt_verified": 1}),
            previous=_rows({"permit_type": "DVS", "receipt_verified": 1}),
        )
        self._check(task, self.finance)

    def test_someone_outside_finance_still_cannot_verify(self):
        """The control has to survive the fix, not be removed by it."""
        if not self.outsider:
            self.skipTest("no suitable non-finance user on this site")
        task = _Task(
            _rows({"permit_type": "DVS", "receipt_verified": 1}),
            previous=_rows({"permit_type": "DVS", "receipt_verified": 0}),
        )
        with self.assertRaises(frappe.ValidationError):
            self._check(task, self.outsider)

    def test_invoice_verified_is_guarded_the_same_way(self):
        if not self.outsider:
            self.skipTest("no suitable non-finance user on this site")
        task = _Task(
            _rows({"permit_type": "DVS", "invoice_verified": 1}),
            previous=_rows({"permit_type": "DVS", "invoice_verified": 0}),
        )
        with self.assertRaises(frappe.ValidationError):
            self._check(task, self.outsider)

    def test_a_row_added_already_ticked_is_still_checked(self):
        """No previous row means the tick arrived with this save."""
        if not self.outsider:
            self.skipTest("no suitable non-finance user on this site")
        task = _Task(_rows({"permit_type": "DVS", "receipt_verified": 1}), previous=[])
        with self.assertRaises(frappe.ValidationError):
            self._check(task, self.outsider)

    def test_an_untouched_row_is_never_checked(self):
        if not self.outsider:
            self.skipTest("no suitable non-finance user on this site")
        task = _Task(
            _rows({"permit_type": "DVS", "receipt_verified": 0}),
            previous=_rows({"permit_type": "DVS", "receipt_verified": 0}),
        )
        self._check(task, self.outsider)
