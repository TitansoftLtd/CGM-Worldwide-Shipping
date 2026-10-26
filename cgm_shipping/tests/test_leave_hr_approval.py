"""An HR approver's own leave is final once their line manager approves.

Every route in the leave workflow ended at Pending HR Approval. An HR approver's own
leave therefore arrived at a step only they could act on, so it was either self-approved
or stuck. Their leave now completes at the line manager instead.
"""

import unittest
from unittest.mock import patch
from unittest.mock import patch as mock_patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import leave_hr_approval as lhr

LINE_MANAGER = lhr.LINE_MANAGER_STATE
HR = lhr.HR_STATE


def _application(user="hr@example.com", employee="EMP-001"):
	doc = frappe._dict(custom_employee_user=user, employee=employee, custom_applicant_is_hr=None)
	doc.meta = frappe._dict(has_field=lambda fieldname: True)
	doc.set = lambda field, value: doc.__setitem__(field, value)
	return doc


def _workflow():
	"""A stand-in for the site's leave workflow, shaped like the real one."""
	doc = frappe._dict(
		states=[
			frappe._dict(state=LINE_MANAGER),
			frappe._dict(state=HR),
			frappe._dict(state="Approved"),
		],
		transitions=[
			frappe._dict(state=LINE_MANAGER, action="Approve", next_state=HR,
			             allowed="Leave Approver", condition='doc.custom_branch == "Nairobi"',
			             allow_self_approval=1),
			frappe._dict(state=LINE_MANAGER, action="Reject", next_state="Rejected",
			             allowed="Leave Approver", condition=None, allow_self_approval=1),
			frappe._dict(state=HR, action="Approve", next_state="Pending Director Approval",
			             allowed="HR Manager", condition=None, allow_self_approval=1),
		],
	)
	doc.append = lambda field, row: doc[field].append(frappe._dict(row))
	return doc


class TestMarkingTheApplicant(unittest.TestCase):
	def _mark(self, roles, hr_roles={"HR Manager"}):
		doc = _application()
		with (
			patch.object(lhr, "hr_approval_roles", return_value=hr_roles),
			patch.object(frappe, "get_roles", return_value=roles),
		):
			lhr.set_applicant_is_hr(doc)
		return doc.custom_applicant_is_hr

	def test_an_hr_approver_is_marked(self):
		self.assertEqual(self._mark(["Employee", "HR Manager"]), 1)

	def test_an_ordinary_employee_is_not(self):
		self.assertEqual(self._mark(["Employee", "Projects User"]), 0)

	def test_hr_user_alone_is_not_an_approver(self):
		# HR User does not approve at the HR step, so their leave follows the normal route.
		self.assertEqual(self._mark(["Employee", "HR User"]), 0)

	def test_an_application_with_no_login_is_not_marked(self):
		doc = _application(user=None, employee=None)
		with patch.object(lhr, "hr_approval_roles", return_value={"HR Manager"}):
			lhr.set_applicant_is_hr(doc)
		self.assertEqual(doc.custom_applicant_is_hr, 0)


class TestHrApprovalRoles(unittest.TestCase):
	"""Settings first, then the workflow, then HR Manager as a last resort."""

	def test_settings_wins_over_the_workflow(self):
		with (
			patch.object(lhr, "configured_hr_roles", return_value={"CGM HR"}),
			patch.object(lhr, "_active_workflow_name", return_value="Leave Application Workflow"),
			patch.object(frappe, "get_all", return_value=[frappe._dict(allowed="HR Manager")]),
		):
			self.assertEqual(lhr.hr_approval_roles(), {"CGM HR"})

	def test_unset_settings_falls_back_to_the_workflow(self):
		with (
			patch.object(lhr, "configured_hr_roles", return_value=set()),
			patch.object(lhr, "_active_workflow_name", return_value="Leave Application Workflow"),
			patch.object(frappe, "get_all", return_value=[frappe._dict(allowed="People Manager")]),
		):
			self.assertEqual(lhr.hr_approval_roles(), {"People Manager"})

	def test_no_settings_and_no_workflow_falls_back_to_hr_manager(self):
		with (
			patch.object(lhr, "configured_hr_roles", return_value=set()),
			patch.object(lhr, "_active_workflow_name", return_value=None),
		):
			self.assertEqual(lhr.hr_approval_roles(), {lhr.DEFAULT_HR_ROLE})

	def test_a_settings_row_that_will_not_load_does_not_break_a_save(self):
		# A leave application must still save if Settings is unreadable.
		with patch.object(frappe, "get_cached_doc", side_effect=RuntimeError("boom")):
			self.assertEqual(lhr.configured_hr_roles(), set())


class TestTeachingTheWorkflow(unittest.TestCase):
	def test_other_approve_routes_are_qualified_once(self):
		wf = _workflow()
		self.assertTrue(lhr._qualify_existing_routes(wf))
		route = wf.transitions[0]
		self.assertEqual(route.condition, '(doc.custom_branch == "Nairobi") and not doc.custom_applicant_is_hr')
		# Running again must not stack the clause a second time.
		self.assertFalse(lhr._qualify_existing_routes(wf))
		self.assertEqual(route.condition.count("custom_applicant_is_hr"), 1)

	def test_reject_routes_are_left_alone(self):
		wf = _workflow()
		lhr._qualify_existing_routes(wf)
		self.assertIsNone(wf.transitions[1].condition)

	def test_the_shortcut_is_added_once(self):
		wf = _workflow()
		self.assertTrue(lhr._add_hr_shortcut(wf))
		added = [t for t in wf.transitions if t.next_state == "Approved"]
		self.assertEqual(len(added), 1)
		self.assertEqual(added[0].state, LINE_MANAGER)
		self.assertEqual(added[0].action, "Approve")
		self.assertEqual(added[0].condition, "doc.custom_applicant_is_hr")
		self.assertEqual(added[0].allowed, "Leave Approver")
		self.assertFalse(lhr._add_hr_shortcut(wf))

	def test_the_hr_step_can_no_longer_self_approve(self):
		wf = _workflow()
		self.assertTrue(lhr._block_hr_self_approval(wf))
		hr_route = [t for t in wf.transitions if t.state == HR and t.action == "Approve"][0]
		self.assertEqual(hr_route.allow_self_approval, 0)
		self.assertFalse(lhr._block_hr_self_approval(wf))

	def test_an_unrecognised_workflow_is_not_touched(self):
		wf = _workflow()
		wf.states = [frappe._dict(state="Something Else")]
		with (
			patch.object(lhr, "ensure_cgm_hr_role"),
			patch.object(lhr, "_active_workflow_name", return_value="Leave Application Workflow"),
			patch.object(frappe, "get_doc", return_value=wf),
		):
			self.assertFalse(lhr.ensure_leave_hr_route())


class TestItRefusesToWriteAConditionItCannotEvaluate(unittest.TestCase):
	"""The conditions name a custom field. Writing them before the field exists would
	make every Approve on every leave application throw, so the installer refuses."""

	def test_missing_flag_field_leaves_the_workflow_alone(self):
		wf = _workflow()
		before = [(t.state, t.next_state, t.condition) for t in wf.transitions]
		with (
			patch.object(lhr, "ensure_cgm_hr_role"),
			patch.object(lhr, "_active_workflow_name", return_value="Leave Application Workflow"),
			patch.object(frappe, "get_meta", return_value=frappe._dict(has_field=lambda f: False)),
			patch.object(frappe, "get_doc", return_value=wf),
			patch.object(frappe, "log_error"),
		):
			self.assertFalse(lhr.ensure_leave_hr_route())
		self.assertEqual([(t.state, t.next_state, t.condition) for t in wf.transitions], before)


class TestMarkingApplicationsAlreadyInFlight(unittest.TestCase):
	"""The flag is computed on save, so applications raised before the deploy carry 0.

	Granting a role by script is refused on this site, so the roles are stubbed rather
	than really assigned; what is under test is the correction, not Frappe's role table.
	"""

	def _run(self, applications, roles_by_user):
		from cgm_shipping.patches import mark_in_flight_hr_leave_applications as patch

		written = {}
		with (
			mock_patch.object(patch.frappe, "get_meta", return_value=frappe._dict(has_field=lambda f: True)),
			mock_patch.object(patch.frappe, "get_all", return_value=applications),
			mock_patch.object(patch.frappe, "get_roles", side_effect=lambda u: roles_by_user.get(u, [])),
			mock_patch.object(patch.frappe.db, "set_value",
			                           side_effect=lambda dt, n, f, v, **kw: written.__setitem__(n, v)),
			mock_patch.object(patch.frappe.db, "commit"),
			mock_patch.object(patch.frappe, "log_error"),
			mock_patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.leave_hr_approval.hr_approval_roles",
				return_value={"HR Manager"},
			),
		):
			patch.execute()
		return written

	def test_an_hr_approvers_in_flight_leave_is_corrected(self):
		apps = [frappe._dict(name="HR-LAP-1", employee="E1", custom_employee_user="hr@x", custom_applicant_is_hr=0)]
		self.assertEqual(self._run(apps, {"hr@x": ["Employee", "HR Manager"]}), {"HR-LAP-1": 1})

	def test_an_ordinary_applicant_is_not_touched(self):
		apps = [frappe._dict(name="HR-LAP-2", employee="E2", custom_employee_user="ops@x", custom_applicant_is_hr=0)]
		self.assertEqual(self._run(apps, {"ops@x": ["Employee"]}), {})

	def test_a_flag_that_is_already_right_is_not_rewritten(self):
		apps = [frappe._dict(name="HR-LAP-3", employee="E3", custom_employee_user="hr@x", custom_applicant_is_hr=1)]
		self.assertEqual(self._run(apps, {"hr@x": ["HR Manager"]}), {})

	def test_a_stale_flag_is_corrected_downward_too(self):
		# Someone who has since lost the HR role should go back to the normal route.
		apps = [frappe._dict(name="HR-LAP-4", employee="E4", custom_employee_user="ex@x", custom_applicant_is_hr=1)]
		self.assertEqual(self._run(apps, {"ex@x": ["Employee"]}), {"HR-LAP-4": 0})
