"""The air plans the client signed off, pinned.

Each case is a decision, not a preference. A change that trips one needs the
client, not a fix.
"""

from __future__ import annotations

import json
import pathlib
import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
	AIR_EXPORT_GATES,
	AIR_IMPORT_GATES,
	air_export_tasks,
	air_import_tasks,
)


def _subjects(rows) -> list[str]:
	return [r["subject"] for r in rows]


def _by_subject(rows, subject) -> dict:
	return next(r for r in rows if r["subject"] == subject)


def _project_fields() -> set[str]:
	path = (
		pathlib.Path(__file__).resolve().parents[1]
		/ "cgm_worldwide_shipping/custom/project.json"
	)
	return {f["fieldname"] for f in json.loads(path.read_text())["custom_fields"]}


class TestAirExportPlan(unittest.TestCase):
	def test_the_steps_that_just_happen_are_not_tasks(self):
		"""Nobody ticks the package onto the plane; it goes."""
		for gone in (
			"Take package to airport and export processes",
			"Hand over shipment to airline",
			"Monitor flight departure",
		):
			self.assertNotIn(gone, _subjects(air_export_tasks()))

	def test_the_departure_is_a_date_on_the_shipment(self):
		"""The client wanted the departure kept, as a field and not a step."""
		self.assertIn("custom_actual_time_of_departure_atd", _project_fields())

	def test_admin_raises_the_airwaybill_number(self):
		row = _by_subject(air_export_tasks(), "Generate airwaybill number")
		self.assertEqual(row["department_role"], "Documentation")

	def test_the_manifest_step_stays(self):
		self.assertIn("Obtain manifest and apply for COE", _subjects(air_export_tasks()))

	def test_admin_closes_the_job_at_arrival_and_at_delivery(self):
		"""The client answered "both" to arrival or delivery, so both are steps."""
		rows = air_export_tasks()
		self.assertEqual(
			[r["subject"] for r in rows[-2:]],
			["Confirm arrival at destination airport", "Confirm delivery to consignee"],
		)
		for row in rows[-2:]:
			self.assertEqual(row["department_role"], "Documentation")


class TestAirImportPlan(unittest.TestCase):
	def test_the_documentation_officer_confirms_the_client_documents(self):
		"""The client named the documentation officer as the one who checks."""
		row = _by_subject(air_import_tasks(), "Receive proforma invoice packing list COA")
		self.assertEqual(row["task_role"], "Document Checkpoint")
		self.assertEqual(row["department_role"], "Documentation")

	def test_the_last_step_is_the_charges_invoice_and_the_delivery_note(self):
		"""The client: after the delivery note the import is done, offline from there."""
		rows = air_import_tasks()
		last = rows[-1]
		self.assertEqual(last["subject"], "Upload invoice for import charges and delivery note")
		self.assertEqual(last["department_role"], "Documentation")
		self.assertEqual(last["required_document_types"], "Delivery Note")
		self.assertEqual(last["depends_on_sequences"], str(rows[-2]["sequence_no"]))

	def test_finance_pays_the_entry(self):
		row = _by_subject(air_import_tasks(), "Finance pays entry")
		self.assertEqual(row["task_role"], "Finance Payment")
		self.assertEqual(row["payment_kind"], "ENTRY_SLIP")

	def test_post_clearance_permits_have_a_finance_step(self):
		"""Pre-clearance had one and post-clearance did not, so nobody paid."""
		rows = air_import_tasks()
		application = _by_subject(rows, "Apply for post-clearance permits")
		finance = _by_subject(rows, "Finance pays post-clearance permit invoices")
		self.assertEqual(finance["task_role"], "Permit Finance")
		self.assertEqual(finance["permit_stage"], "Post-clearance")
		self.assertEqual(finance["payment_kind"], "Permit")
		self.assertEqual(finance["sequence_no"], application["sequence_no"] + 1)
		self.assertEqual(finance["depends_on_sequences"], str(application["sequence_no"]))


class TestAirGatesPointAtRealSteps(unittest.TestCase):
	def test_no_gate_runs_past_the_last_step(self):
		for gates, rows, name in (
			(AIR_IMPORT_GATES, air_import_tasks(), "Air Import"),
			(AIR_EXPORT_GATES, air_export_tasks(), "Air Export"),
		):
			last = max(r["sequence_no"] for r in rows)
			for gate in gates:
				self.assertLessEqual(
					gate["min_completed_task_seq"],
					last,
					f"{name}: {gate['shipment_workflow_state']} waits for a step that is gone",
				)

	def test_completed_waits_for_the_last_step(self):
		"""A shipment that still has a step to work is not finished."""
		for gates, rows, name in (
			(AIR_IMPORT_GATES, air_import_tasks(), "Air Import"),
			(AIR_EXPORT_GATES, air_export_tasks(), "Air Export"),
		):
			gate = next(g for g in gates if g["shipment_workflow_state"] == "Completed")
			self.assertEqual(
				gate["min_completed_task_seq"],
				max(r["sequence_no"] for r in rows),
				f"{name}: Completed does not wait for the last step",
			)

	def test_a_permit_status_waits_for_finance_not_the_application(self):
		"""Pre-clearance sits on the Finance step, so post-clearance must too."""
		rows = air_import_tasks()
		gate = next(g for g in AIR_IMPORT_GATES if g["shipment_workflow_state"] == "Post-clearance")
		finance = _by_subject(rows, "Finance pays post-clearance permit invoices")
		self.assertEqual(gate["min_completed_task_seq"], finance["sequence_no"])


class TestEveryAirStepIsReachable(unittest.TestCase):
	def test_dependencies_point_backwards_at_real_steps(self):
		for rows, name in ((air_import_tasks(), "Air Import"), (air_export_tasks(), "Air Export")):
			seqs = {r["sequence_no"] for r in rows}
			for row in rows:
				dep = (row["depends_on_sequences"] or "").strip()
				for part in filter(None, dep.split(",")):
					n = int(part)
					self.assertIn(n, seqs, f"{name} step {row['sequence_no']} waits for {n}, which is gone")
					self.assertLess(n, row["sequence_no"], f"{name} step {row['sequence_no']} waits for a later step")

	def test_subjects_are_unique(self):
		"""Tasks are matched back to the template by subject, so repeats mis-stamp."""
		for rows, name in ((air_import_tasks(), "Air Import"), (air_export_tasks(), "Air Export")):
			subjects = _subjects(rows)
			self.assertEqual(len(set(subjects)), len(subjects), f"{name} repeats a subject")



class TestThePatchNamesRealSteps(unittest.TestCase):
	"""The patch matches rows by subject, so a renamed step must fail here."""

	def setUp(self):
		from cgm_shipping.patches import align_air_templates_with_client_plan as patch

		self.patch = patch
		self.seeded = _subjects(air_import_tasks()) + _subjects(air_export_tasks())

	def test_every_step_it_adds_or_follows_is_in_the_seed(self):
		p = self.patch
		for subject in (
			p.INTAKE_STEP,
			p.ENTRY_PAYMENT_NOW,
			p.POST_CLEARANCE_APPLICATION,
			p.POST_CLEARANCE_FINANCE,
			p.FINAL_STEP,
		):
			self.assertIn(subject, _subjects(air_import_tasks()))
		for subject in (p.AIRWAYBILL_STEP, p.MANIFEST_STEP, *p.CLOSING_STEPS):
			self.assertIn(subject, _subjects(air_export_tasks()))

	def test_what_it_retires_is_gone_from_the_seed(self):
		for subject in (self.patch.ENTRY_PAYMENT_WAS, *self.patch.AIR_EXPORT_DROPPED):
			self.assertNotIn(subject, self.seeded)


class TestTheIntakeStepHoldsTheShipment(unittest.TestCase):
	"""Nothing moves until the client documents are in."""

	def test_the_intake_step_waits_for_the_client_documents(self):
		row = _by_subject(air_import_tasks(), "Receive proforma invoice packing list COA")
		self.assertEqual(row["required_document_types"], "CI, PKL")
		self.assertEqual(row["requires_document_upload"], 1)

	def test_it_does_not_wait_for_the_coa_it_is_named_after(self):
		"""COA is optional on the master; half the shipments never get one."""
		row = _by_subject(air_import_tasks(), "Receive proforma invoice packing list COA")
		self.assertNotIn("COA", row["required_document_types"])

	def test_the_next_step_waits_for_it(self):
		"""Only a block if step 2 depends on it."""
		rows = air_import_tasks()
		self.assertEqual(rows[1]["depends_on_sequences"], "1")


class TestStampedDocumentsBlockCompletion(unittest.TestCase):
	"""What the stamp does, not that it is spelled right."""

	def _validate(self, required, attached):
		from cgm_shipping.cgm_worldwide_shipping.customizations import task as task_mod

		task = frappe._dict(name="TASK-1", custom_task_documents=[])
		with patch.object(task_mod, "get_effective_required_document_types", return_value=required), patch.object(
			task_mod, "attached_document_codes", return_value=set(attached)
		), patch.object(task_mod, "resolve_required_document_type_name", side_effect=lambda t: t), patch.object(
			task_mod, "_required_document_type_names", return_value=required
		):
			task_mod.validate_required_documents(task, 1)

	def test_a_missing_document_stops_the_step(self):
		with self.assertRaises(Exception) as caught:
			self._validate(["CI", "PKL", "COA"], ["CI"])
		self.assertIn("COA", str(caught.exception))
		self.assertIn("PKL", str(caught.exception))

	def test_all_three_present_lets_it_through(self):
		self._validate(["CI", "PKL", "COA"], ["CI", "PKL", "COA"])

	def test_a_step_with_no_stamp_is_not_gated(self):
		self._validate([], [])


class TestAStepThatDoesNotApplyCanBeCancelled(unittest.TestCase):
	"""Cancelled is how the declarant marks a step that does not apply.

	It releases whatever waited on the step and drops out of the status gates.
	"""

	def test_a_cancelled_step_releases_the_one_waiting_on_it(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import CGMTask

		task = frappe._dict(
			doctype="Task",
			name="TASK-NEXT",
			status="Completed",
			depends_on=[frappe._dict(task="TASK-PERMIT")],
			get_db_value=lambda _f: "Open",
		)
		with patch(
			"frappe.db.get_value", return_value="Cancelled"
		), patch("frappe.desk.form.assign_to.close_all_assignments") as closed:
			CGMTask.validate_status(task)
		closed.assert_called_once()

	def test_an_open_step_still_blocks_the_one_waiting_on_it(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import task as task_mod

		task = frappe._dict(
			doctype="Task",
			name="TASK-NEXT",
			status="Completed",
			depends_on=[frappe._dict(task="TASK-PERMIT")],
			get_db_value=lambda _f: "Open",
		)
		with patch("frappe.db.get_value", return_value="Open"), patch.object(
			task_mod, "_is_sea_task", return_value=False
		), patch.object(task_mod, "blocked_dialog", side_effect=RuntimeError("blocked")) as dialog:
			with self.assertRaises(RuntimeError):
				task_mod.CGMTask.validate_status(task)
		dialog.assert_called_once()

	def test_the_status_gate_ignores_a_cancelled_step(self):
		"""Cancelled sits beside Completed in the gate query, so the chart moves on."""
		import inspect

		from cgm_shipping.cgm_worldwide_shipping.customizations import sea_clearance

		source = inspect.getsource(sea_clearance.get_incomplete_sea_tasks)
		self.assertIn("status NOT IN ('Completed', 'Cancelled')", source)

if __name__ == "__main__":
	unittest.main()
