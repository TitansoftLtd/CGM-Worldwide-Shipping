"""An HR approver's own leave does not come back to them for approval.

The leave workflow ends every route at Pending HR Approval, then Pending Director
Approval. That works until the applicant is one of the HR approvers: their own leave
arrives at a step only they can act on, so either they approve their own leave or it
sits there. Blocking the self-approval on its own would just deadlock it.

So an HR approver's leave is final once their line manager approves. The applicant is
recognised by role rather than by name, and the role is read from the workflow itself,
so changing which role approves at the HR step changes who this applies to.

Two parts, because a workflow decides routing and only a document knows who applied:
`set_applicant_is_hr` marks the application on validate, and `ensure_leave_hr_route`
teaches the workflow to read that mark.
"""

from __future__ import annotations

import frappe

LEAVE_APPLICATION = "Leave Application"
FLAG_FIELD = "custom_applicant_is_hr"

LINE_MANAGER_STATE = "Pending Line Manager Approval"
HR_STATE = "Pending HR Approval"
APPROVED_STATE = "Approved"
APPROVE_ACTION = "Approve"

#: The role CGM gives the HR employee. Settings decides who counts as HR; this is what
#: that setting is seeded with, so the answer is one named role rather than "HR Manager",
#: which other people hold for unrelated reasons.
CGM_HR_ROLE = "CGM HR"

SETTINGS = "CGM Shipping Settings"
HR_ROLES_FIELD = "custom_hr_roles"

#: Last resort: no setting, and a workflow that names no role at the HR step.
DEFAULT_HR_ROLE = "HR Manager"

#: Appended to the routes out of the line manager's step so they do not compete with
#: the shortcut added for an HR applicant.
NOT_HR = f"not doc.{FLAG_FIELD}"
IS_HR = f"doc.{FLAG_FIELD}"


# ---------------------------------------------------------------------------------
# Marking the application
# ---------------------------------------------------------------------------------


def set_applicant_is_hr(doc, method=None) -> None:
	"""Record whether this application was raised by one of the HR approvers."""
	if not doc.meta.has_field(FLAG_FIELD):
		return

	doc.set(FLAG_FIELD, 1 if applicant_is_hr(doc) else 0)


def applicant_is_hr(doc) -> bool:
	user = doc.get("custom_employee_user") or _employee_user(doc.get("employee"))
	if not user:
		return False

	roles = hr_approval_roles()
	if not roles:
		return False

	return bool(set(frappe.get_roles(user)) & roles)


def _employee_user(employee: str | None) -> str | None:
	"""The applicant's login, for an application saved before the fetch happened."""
	if not employee:
		return None
	return frappe.db.get_value("Employee", employee, "user_id")


def hr_approval_roles() -> set[str]:
	"""Who counts as HR, in order of how deliberate the answer is.

	Settings first, because that is where someone has said so on purpose. Then the roles
	the workflow allows at its HR step, which is a fair inference on a site that has not
	been configured. `HR Manager` only as a last resort: on this site other people hold
	it for unrelated reasons, which is the whole reason the setting exists.
	"""
	configured = configured_hr_roles()
	if configured:
		return configured

	workflow = _active_workflow_name()
	if not workflow:
		return {DEFAULT_HR_ROLE}

	roles = {
		row.allowed
		for row in frappe.get_all(
			"Workflow Transition",
			filters={"parent": workflow, "state": HR_STATE},
			fields=["allowed"],
		)
		if row.allowed
	}
	return roles or {DEFAULT_HR_ROLE}


def configured_hr_roles() -> set[str]:
	"""The HR roles named in CGM Shipping Settings, if any."""
	if not frappe.db.exists("DocType", SETTINGS):
		return set()

	try:
		settings = frappe.get_cached_doc(SETTINGS)
	except Exception:
		# A settings row that will not load must not stop a leave application saving.
		return set()

	if not settings.meta.has_field(HR_ROLES_FIELD):
		return set()

	return {row.role for row in (settings.get(HR_ROLES_FIELD) or []) if row.role}


def _active_workflow_name() -> str | None:
	return frappe.db.get_value(
		"Workflow", {"document_type": LEAVE_APPLICATION, "is_active": 1}, "name"
	)


def ensure_cgm_hr_role() -> None:
	"""Create the CGM HR role and name it in Settings.

	The role is created empty: nobody holds it until it is given to the HR employee on
	their User record. Until then no applicant is recognised as HR and every leave takes
	the route it takes today, which is the safe way round for this to arrive.
	"""
	if not frappe.db.exists("Role", CGM_HR_ROLE):
		frappe.get_doc(
			{"doctype": "Role", "role_name": CGM_HR_ROLE, "desk_access": 1}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("DocType", SETTINGS):
		return

	settings = frappe.get_single(SETTINGS)
	if not settings.meta.has_field(HR_ROLES_FIELD):
		return

	if settings.get(HR_ROLES_FIELD):
		# Already answered, by seeding or by hand. Not ours to overwrite.
		return

	settings.append(HR_ROLES_FIELD, {"role": CGM_HR_ROLE})
	settings.flags.ignore_permissions = True
	settings.save()


# ---------------------------------------------------------------------------------
# Teaching the workflow
# ---------------------------------------------------------------------------------


def ensure_leave_hr_route() -> bool:
	"""Route an HR approver's own leave straight to Approved at the line manager.

	Idempotent, and narrow on purpose: it adds one transition, qualifies the existing
	routes out of the line manager's step so they do not also fire, and stops the HR
	step being self-approved. Every other transition is left exactly as configured,
	because this workflow is tuned on the site and not shipped by the app.
	"""
	ensure_cgm_hr_role()

	name = _active_workflow_name()
	if not name:
		return False

	# The conditions written below read this field. Writing them while the field is
	# missing would make every Approve on every leave application throw, so this is a
	# refusal to proceed rather than a tidy-up. after_migrate runs after
	# sync_customizations, so in a normal deploy the field is already there.
	if not frappe.get_meta(LEAVE_APPLICATION).has_field(FLAG_FIELD):
		frappe.log_error(
			title="CGM: leave HR route not installed",
			message=(
				f"{FLAG_FIELD} is not on {LEAVE_APPLICATION} yet, so the workflow was left "
				"untouched. Re-run bench migrate once custom/leave_application.json has synced."
			),
		)
		return False

	workflow = frappe.get_doc("Workflow", name)
	states = {row.state for row in workflow.states}
	if not {LINE_MANAGER_STATE, APPROVED_STATE} <= states:
		# A renamed or replaced workflow: better to do nothing than to guess at it.
		return False

	changed = _qualify_existing_routes(workflow)
	changed = _add_hr_shortcut(workflow) or changed
	changed = _block_hr_self_approval(workflow) or changed

	if changed:
		workflow.flags.ignore_permissions = True
		workflow.save()
		frappe.clear_cache(doctype=LEAVE_APPLICATION)

	return changed


def _qualify_existing_routes(workflow) -> bool:
	"""Add "and not applicant is HR" to the line manager's other Approve routes."""
	changed = False
	for row in workflow.transitions:
		if row.state != LINE_MANAGER_STATE or row.action != APPROVE_ACTION:
			continue
		if row.next_state == APPROVED_STATE:
			continue
		if FLAG_FIELD in (row.condition or ""):
			continue

		existing = (row.condition or "").strip()
		row.condition = f"({existing}) and {NOT_HR}" if existing else NOT_HR
		changed = True
	return changed


def _add_hr_shortcut(workflow) -> bool:
	"""One Approve route from the line manager's step straight to Approved."""
	for row in workflow.transitions:
		if (
			row.state == LINE_MANAGER_STATE
			and row.action == APPROVE_ACTION
			and row.next_state == APPROVED_STATE
		):
			return False

	allowed = next(
		(
			row.allowed
			for row in workflow.transitions
			if row.state == LINE_MANAGER_STATE and row.action == APPROVE_ACTION and row.allowed
		),
		None,
	)
	if not allowed:
		return False

	workflow.append(
		"transitions",
		{
			"state": LINE_MANAGER_STATE,
			"action": APPROVE_ACTION,
			"next_state": APPROVED_STATE,
			"allowed": allowed,
			"condition": IS_HR,
			# The line manager is not the applicant here, so this is not self-approval.
			"allow_self_approval": 1,
		},
	)
	return True


def _block_hr_self_approval(workflow) -> bool:
	"""Stop the HR step approving an application its own owner raised.

	Belt and braces behind the routing: an application that reached the HR step some
	other way still cannot be approved by the person who raised it.
	"""
	changed = False
	for row in workflow.transitions:
		if row.state == HR_STATE and row.action == APPROVE_ACTION and row.allow_self_approval:
			row.allow_self_approval = 0
			changed = True
	return changed
