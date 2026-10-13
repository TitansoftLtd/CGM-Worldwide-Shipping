"""Funding Request actions: Disburse listed first, and Cancel renamed.

Why: the Actions menu on an approved Funding Request read *Cancel, Disburse*.
Disburse is what Finance opens the request to do, and cancelling is the
exception, so the exception sat on top. And a bare "Cancel" in a menu reads as
"close this menu", not "cancel this request and hand its Material Requests back".

What: on the active Funding Request workflow,

* adds the payment actions where they are missing (the same create-if-missing
  step migrate runs, done here first so there is something to order). There is
  one per pending step - Disburse, Create Purchase Order, Submit Journal Entry,
  Submit Purchase Order, Record Purchase Payment - each shown only while the
  request is waiting on that step,
* fills `pending_step` on submitted Funding Requests, which is what decides the
  action a request shows,
* adds a "Disbursement in Progress" state to the Material Request workflow and
  refreshes the state of Material Requests on submitted Funding Requests, so a
  request whose entry or order is raised but unpaid says so,
* renames the action that leads to a cancelled state from "Cancel" to
  "Cancel Request",
* moves each Disburse action above the other actions of its state,
* removes the Complete action and the Completed state, so Disbursed is the last
  state. Completed only recorded that someone pressed Complete after the money
  had gone out, and nothing read it. Requests already Completed are moved to
  Disbursed first,
* adds "Cancel Request" to Disbursed, which had no way back.

Nothing else on the workflow is touched: no state, role or other action. A
cancelling action already renamed in Desk to something else is left with the
name it was given. On Funding Requests `pending_step` is written and Completed
becomes Disbursed; no amount or timestamp changes.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it.
"""

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import (
		ensure_funding_completed_cancel_transition,
		ensure_funding_disburse_transition,
		ensure_material_request_progress_state,
		retire_funding_completed_state,
		tidy_funding_request_actions,
	)

	if not frappe.db.exists("DocType", "Funding Request"):
		return
	added = ensure_funding_disburse_transition()
	result = tidy_funding_request_actions()
	# Disbursed becomes the last state. Done before the cancel action is added, so
	# it lands on Disbursed and not on a state about to be removed.
	retired = retire_funding_completed_state()
	# After the rename, so the new action is created under its final name.
	ensure_funding_completed_cancel_transition()

	# The actions are shown by `pending_step`, which no existing request has yet.
	filled = 0
	if frappe.get_meta("Funding Request").has_field("pending_step"):
		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import store_pending_step

		for name in frappe.get_all("Funding Request", filters={"docstatus": 1}, pluck="name"):
			if store_pending_step(frappe.get_doc("Funding Request", name)):
				filled += 1

	# Material Requests mirror their Funding Request, and now have an in-progress
	# state to mirror. Bring the ones on live requests up to date.
	ensure_material_request_progress_state()
	for name in frappe.get_all("Funding Request", filters={"docstatus": 1}, pluck="name"):
		frappe.get_doc("Funding Request", name).sync_material_request_links()
	frappe.db.commit()
	print(
		f"Funding Request workflow: Disburse added: {bool(added)}; "
		f"cancel actions renamed: {result['renamed']}; reordered: {result['reordered']}; "
		f"requests with a pending step: {filled}; "
		f"Completed retired: {retired['removed'] or 'already gone'}, requests moved to Disbursed: {retired['moved']}"
	)
