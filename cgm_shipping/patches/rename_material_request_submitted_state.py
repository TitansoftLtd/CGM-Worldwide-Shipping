"""Rename the Material Request funding state "Submitted" to "Awaiting Funding".

Why: "Submitted" described the mechanics, not the situation. Every submitted
document in Frappe is submitted, so the word told a requester nothing about what
happens next or who is holding it. The state actually means the request is waiting
for somebody to put it on a Funding Request, so it now says that.

What: renames the state on the `CGM Material Request Funding` workflow - its
states and both sides of every transition - adds the `Workflow State` master if it
is missing, and moves every Material Request currently sitting in the old state.

Measured before writing this: `Submitted` is used by that one workflow and no
other, so no other document type is touched. If another workflow has started using
it by the time this runs, the rename is skipped rather than reaching across into
somebody else's process.

This changes a label and the value stored in `workflow_state`. No amount, no
document status and nothing posted changes, and the transitions keep the same
shape, so a request in this state moves on exactly as it did before.

The code accepts either name (`pick_workflow_state` takes the new one first and
falls back to the old), so the app keeps working on a site where this has not run.

Idempotent. Retire per docs/guides/patches.md once staging and production Patch Log
show it.
"""

import frappe

WORKFLOW = "CGM Material Request Funding"
OLD_STATE = "Submitted"
NEW_STATE = "Awaiting Funding"


def _other_workflows_using_old_state() -> list[str]:
	rows = frappe.get_all(
		"Workflow Document State", filters={"state": OLD_STATE}, fields=["parent"]
	)
	return sorted({r.parent for r in rows} - {WORKFLOW})


def execute():
	if not frappe.db.exists("Workflow", WORKFLOW):
		print(f"{WORKFLOW} is not on this site; nothing to rename.")
		return

	states = frappe.get_all(
		"Workflow Document State", filters={"parent": WORKFLOW}, pluck="state"
	)
	if NEW_STATE in states and OLD_STATE not in states:
		print(f"{WORKFLOW} already uses {NEW_STATE!r}; nothing to do.")
		return

	shared = _other_workflows_using_old_state()
	if shared:
		# Renaming would reach into a process this patch knows nothing about.
		print(f"{OLD_STATE!r} is also used by {', '.join(shared)}; skipping the rename.")
		return

	if not frappe.db.exists("Workflow State", NEW_STATE):
		style = frappe.db.get_value("Workflow State", OLD_STATE, "style") or ""
		frappe.get_doc(
			{"doctype": "Workflow State", "workflow_state_name": NEW_STATE, "style": style}
		).insert(ignore_permissions=True)
		print(f"Created Workflow State {NEW_STATE!r}.")

	workflow = frappe.get_doc("Workflow", WORKFLOW)
	touched = 0
	for row in workflow.states:
		if row.state == OLD_STATE:
			row.state = NEW_STATE
			touched += 1
	for row in workflow.transitions:
		if row.state == OLD_STATE:
			row.state = NEW_STATE
			touched += 1
		if row.next_state == OLD_STATE:
			row.next_state = NEW_STATE
			touched += 1
	if touched:
		workflow.flags.ignore_permissions = True
		workflow.save()
		print(f"Renamed {touched} workflow state/transition reference(s).")

	moved = frappe.db.sql(
		"select count(*) from `tabMaterial Request` where workflow_state = %(old)s",
		{"old": OLD_STATE},
	)[0][0]
	if moved:
		frappe.db.sql(
			"update `tabMaterial Request` set workflow_state = %(new)s where workflow_state = %(old)s",
			{"new": NEW_STATE, "old": OLD_STATE},
		)
		print(f"Moved {moved} Material Request(s) to {NEW_STATE!r}.")
	else:
		print(f"No Material Request was sitting in {OLD_STATE!r}.")

	frappe.db.commit()
	frappe.clear_cache(doctype="Material Request")
