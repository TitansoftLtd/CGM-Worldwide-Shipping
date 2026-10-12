"""Reopen tasks that were completed while their own gates were still pending."""

import frappe

REOPEN_VALUES = {
	"status": "Open",
	"progress": 0,
	"completed_by": None,
	"completed_on": None,
}


def _pending_reason(task) -> str | None:
	"""Why this Completed task is not actually complete, or None if it is fine."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		can_complete_application_finance_task,
		can_complete_application_task,
		profile_for_task,
		task_matches_application,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_permit_application,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		permit_rows_pending_verification,
	)

	if task_is_permit_application(task):
		invoices, receipts, _fin = permit_rows_pending_verification(task)
		if invoices or receipts:
			parts = []
			if invoices:
				parts.append(f"invoice not verified: {', '.join(invoices)}")
			if receipts:
				parts.append(f"receipt not verified: {', '.join(receipts)}")
			return "; ".join(parts)
		return None

	profile = profile_for_task(task)
	if not profile:
		return None

	if task_matches_application(task, profile):
		if not can_complete_application_task(task, profile):
			return "application gates not satisfied"
		return None

	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		task_matches_application_finance,
	)

	if task_matches_application_finance(task, profile):
		if not can_complete_application_finance_task(task, profile):
			return "finance gates not satisfied"
	return None


def execute():
	names = frappe.get_all(
		"Task",
		filters={"status": "Completed", "project": ["is", "set"]},
		pluck="name",
		order_by="creation",
	)
	reopened, skipped, failed = [], 0, 0

	for name in names:
		try:
			task = frappe.get_doc("Task", name)
		except Exception:
			failed += 1
			continue

		try:
			reason = _pending_reason(task)
		except Exception:
			frappe.log_error(
				title="reopen_tasks_completed_with_pending_verification",
				message=f"{name}: {frappe.get_traceback()}",
			)
			failed += 1
			continue

		if not reason:
			skipped += 1
			continue

		frappe.flags.cgm_reopening_task = True
		try:
			frappe.db.set_value("Task", name, REOPEN_VALUES, update_modified=True)
			frappe.clear_document_cache("Task", name)
		finally:
			frappe.flags.cgm_reopening_task = False

		reopened.append((name, task.subject, task.project, reason))

	# set_value bypasses document hooks, so on_task_update never fires and the
	# Project keeps claiming a stage its tasks no longer support. Rewind it here
	# through the same function the task save hook uses - it advances or rewinds,
	# so a Project whose reopened task pulls it back a stage is corrected, and one
	# that is unaffected is left alone. Same approach as fix_sea_import_status_gates.
	rewound = []
	for project in sorted({row[2] for row in reopened if row[2]}):
		try:
			from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
				sync_project_shipment_status_from_tasks,
			)

			before = frappe.db.get_value("Project", project, "custom_shipment_status")
			after = sync_project_shipment_status_from_tasks(project)
			if after and after != before:
				rewound.append((project, before, after))
		except Exception:
			frappe.log_error(
				title="reopen_tasks_completed_with_pending_verification",
				message=f"{project}: {frappe.get_traceback()}",
			)

	frappe.db.commit()

	print(
		f"Tasks checked: {len(names)}; reopened: {len(reopened)}; "
		f"left completed: {skipped}; could not check: {failed}"
	)
	for name, subject, project, reason in reopened:
		print(f"  reopened {name} ({project}) {subject} - {reason}")
	if rewound:
		print(f"\nProject shipment status rewound on {len(rewound)}:")
		for project, before, after in rewound:
			print(f"  {project}: {before} -> {after}")
