"""Who hears about somebody going on leave, and who does not.

Quality assurance used to be told about every leave application because she
happened to hold Senior Operations Manager and Director. Those are approval rights,
not a mailing list. When the role profiles were reorganised on 30 October she lost
both and the emails stopped, and putting them back would have handed her the power
to approve leave in order to fix an email.

So the recipients are a list in Settings, and there are two notices: one when the
application is raised, one when the line manager approves. Nobody is told about
their own leave; that still arrives as the ordinary employee notification.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import (
    leave_watch_notification as lwn,
)


class _Settings:
    def __init__(self, users, has_field=True):
        self.rows = [frappe._dict(user=u) for u in users]
        self.meta = frappe._dict(has_field=lambda f: has_field)

    def get(self, _field, _default=None):
        return self.rows


class _Leave:
    def __init__(self, applicant=None, stamped=""):
        self._d = {
            "custom_employee_user": applicant,
            lwn.EMAILS_FIELD: stamped,
        }
        self.meta = frappe._dict(has_field=lambda f: True)

    def get(self, field, default=None):
        return self._d.get(field, default)

    def set(self, field, value):
        self._d[field] = value


def _with(users, enabled=None, emails=None):
    """Stub Settings and the User lookups the module makes."""
    enabled = users if enabled is None else enabled
    emails = emails or {}

    def get_all(doctype, **kw):
        return [frappe._dict(name=u) for u in enabled]

    def get_value(doctype, name, field):
        return emails.get(name)

    return (
        patch.object(frappe, "get_cached_doc", return_value=_Settings(users)),
        patch.object(frappe, "get_all", side_effect=get_all),
        patch.object(frappe.db, "get_value", side_effect=get_value),
    )


class TestWhoIsTold(unittest.TestCase):
    def test_the_people_named_in_settings(self):
        c1, c2, c3 = _with(["mary@x.com", "ops@x.com"])
        with c1, c2, c3:
            self.assertEqual(lwn.leave_watchers(), ["mary@x.com", "ops@x.com"])

    def test_an_empty_list_tells_nobody(self):
        c1, c2, c3 = _with([])
        with c1, c2, c3:
            self.assertEqual(lwn.leave_watchers(), [])

    def test_a_disabled_login_is_skipped(self):
        """Still listed in Settings, but they have left."""
        c1, c2, c3 = _with(["mary@x.com", "gone@x.com"], enabled=["mary@x.com"])
        with c1, c2, c3:
            self.assertEqual(lwn.leave_watchers(), ["mary@x.com"])

    def test_a_duplicate_row_is_told_once(self):
        c1, c2, c3 = _with(["mary@x.com", "mary@x.com"], enabled=["mary@x.com"])
        with c1, c2, c3:
            self.assertEqual(lwn.leave_watchers(), ["mary@x.com"])

    def test_settings_without_the_field_tells_nobody(self):
        with patch.object(frappe, "get_cached_doc", return_value=_Settings([], has_field=False)):
            self.assertEqual(lwn.leave_watchers(), [])

    def test_settings_that_will_not_load_does_not_break_a_save(self):
        with patch.object(frappe, "get_cached_doc", side_effect=Exception("boom")):
            self.assertEqual(lwn.leave_watchers(), [])


class TestNobodyIsToldAboutTheirOwnLeave(unittest.TestCase):
    """They already get the ordinary employee notification."""

    def test_the_applicant_is_left_out(self):
        c1, c2, c3 = _with(["mary@x.com", "ops@x.com"])
        with c1, c2, c3:
            doc = _Leave(applicant="mary@x.com")
            lwn.set_leave_watcher_emails(doc)
        self.assertEqual(doc.get(lwn.EMAILS_FIELD), "ops@x.com")

    def test_the_only_watcher_applying_leaves_nobody_to_tell(self):
        c1, c2, c3 = _with(["mary@x.com"])
        with c1, c2, c3:
            doc = _Leave(applicant="mary@x.com")
            lwn.set_leave_watcher_emails(doc)
        self.assertEqual(doc.get(lwn.EMAILS_FIELD), "")

    def test_the_comparison_ignores_case(self):
        c1, c2, c3 = _with(["Mary@X.com"], enabled=["Mary@X.com"])
        with c1, c2, c3:
            doc = _Leave(applicant="mary@x.com")
            lwn.set_leave_watcher_emails(doc)
        self.assertEqual(doc.get(lwn.EMAILS_FIELD), "")

    def test_somebody_elses_leave_reaches_every_watcher(self):
        c1, c2, c3 = _with(["mary@x.com", "ops@x.com"])
        with c1, c2, c3:
            doc = _Leave(applicant="driver@x.com")
            lwn.set_leave_watcher_emails(doc)
        self.assertEqual(doc.get(lwn.EMAILS_FIELD), "mary@x.com, ops@x.com")

    def test_an_application_with_no_login_still_tells_the_watchers(self):
        c1, c2, c3 = _with(["mary@x.com"])
        with c1, c2, c3:
            doc = _Leave(applicant=None)
            lwn.set_leave_watcher_emails(doc)
        self.assertEqual(doc.get(lwn.EMAILS_FIELD), "mary@x.com")


class TestTheTwoMoments(unittest.TestCase):
    def test_one_fires_when_the_application_is_raised(self):
        spec = lwn.WATCH_NOTIFICATIONS["CGM Leave - Watch (Applied)"]
        self.assertEqual(spec["event"], "New")
        self.assertIn(lwn.LINE_MANAGER_STATE, spec["condition"])

    def test_the_other_fires_when_the_line_manager_approves(self):
        spec = lwn.WATCH_NOTIFICATIONS["CGM Leave - Watch (Line Manager Approved)"]
        self.assertEqual(spec["event"], "Value Change")
        self.assertEqual(spec["value_changed"], "workflow_state")
        for state in lwn.AFTER_LINE_MANAGER:
            with self.subTest(state=state):
                self.assertIn(state, spec["condition"])

    def test_the_final_director_approval_is_not_one_of_them(self):
        """That one is the approver's prompt to act, and the watcher acts on none."""
        for spec in lwn.WATCH_NOTIFICATIONS.values():
            self.assertNotIn("Pending Director Approval", spec["condition"])

    def test_both_are_addressed_from_the_stamped_field(self):
        """Not by role: a role is whoever the profiles say, which is too many."""
        import inspect

        src = inspect.getsource(lwn.ensure_leave_watch_notifications)
        self.assertIn("receiver_by_document_field", src)
        self.assertNotIn("receiver_by_role", src)


class TestTheTemplate(unittest.TestCase):
    def test_it_renders_against_a_real_application(self):
        names = frappe.get_all("Leave Application", pluck="name", limit=1)
        if not names:
            self.skipTest("no leave applications on this site")
        doc = frappe.get_doc("Leave Application", names[0])
        for name, spec in lwn.WATCH_NOTIFICATIONS.items():
            with self.subTest(notification=name):
                html = frappe.render_template(spec["message"], {"doc": doc, "frappe": frappe})
                self.assertIn(doc.employee_name, html)
                self.assertIn("Open the application", html)

    def test_the_subject_names_the_employee(self):
        for spec in lwn.WATCH_NOTIFICATIONS.values():
            self.assertIn("doc.employee_name", spec["subject"])
