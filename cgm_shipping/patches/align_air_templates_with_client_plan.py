"""Bring the two air plans in line with what the client agreed.

Templates are seeded only on a fresh site and never overwritten, so a seed change
alone never reaches a running one.

Air Export loses three steps nobody ticks and gains the two closing ones; the
airwaybill number moves to admin. Air Import names its entry payment step after
the payment, makes step 1 the documentation officer's checkpoint, and gains two
steps: Finance for post-clearance permits, and the closing upload of the import
charges invoice and delivery note. Its Client Inspection gate is dropped: the
status was retired, so the row blocked every save, in Desk too.
fix_sea_import_status_gates missed this one.
"""

import frappe

ITEM = "CGM Task Template Item"
GATE = "CGM Task Template Gate"
TEMPLATE = "CGM Task Template"

AIR_IMPORT = "Air Import Workflow"
AIR_EXPORT = "Air Export Workflow"

ENTRY_PAYMENT_WAS = "Confirm entry taxes paid"
ENTRY_PAYMENT_NOW = "Finance pays entry"
POST_CLEARANCE_APPLICATION = "Apply for post-clearance permits"
POST_CLEARANCE_FINANCE = "Finance pays post-clearance permit invoices"
# Admin uploads both; the delivery note is where import clearance ends.
FINAL_STEP = "Upload invoice for import charges and delivery note"

# These happen on their own; nobody completes them.
AIR_EXPORT_DROPPED = (
	"Take package to airport and export processes",
	"Hand over shipment to airline",
	"Monitor flight departure",
)
AIRWAYBILL_STEP = "Generate airwaybill number"
MANIFEST_STEP = "Obtain manifest and apply for COE"
# Arrival and delivery are two moments.
CLOSING_STEPS = ("Confirm arrival at destination airport", "Confirm delivery to consignee")

INTAKE_STEP = "Receive proforma invoice packing list COA"


def _ensure_document_types() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		ensure_document_types,
	)

	ensure_document_types()


def _seed_row(subject: str) -> dict:
	"""The step as the seed defines it, so the plan is written down once."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		air_import_tasks,
	)

	return next(r for r in air_import_tasks() if r["subject"] == subject)


def _new_step(subject: str, at: int) -> dict:
	"""The new step, numbered for where it lands."""
	return {**_seed_row(subject), "sequence_no": at + 1, "depends_on_sequences": str(at)}


def _intake_documents() -> str:
	return _seed_row(INTAKE_STEP)["required_document_types"]


def _intake_role() -> str:
	return _seed_row(INTAKE_STEP)["task_role"]


def execute():
	if not frappe.db.exists("DocType", TEMPLATE):
		return
	# A template save rejects a stamp naming a Document Type the site lacks.
	_ensure_document_types()
	for name in (AIR_IMPORT, AIR_EXPORT):
		_drop_unreachable_gates(name)
	_align_air_import()
	_align_air_export()
	_carry_live_air_import_projects()


def _valid_states() -> set:
	field = frappe.get_meta(GATE).get_field("shipment_workflow_state")
	return {line.strip() for line in (field.options or "").split("\n") if line.strip()}


def _drop_unreachable_gates(template: str) -> None:
	"""A gate naming a retired status can never fire, and blocks every save."""
	if not frappe.db.exists(TEMPLATE, template):
		return
	valid = _valid_states()
	if not valid:
		return
	for gate in _gates(template):
		if gate.shipment_workflow_state not in valid:
			frappe.db.delete(GATE, {"name": gate.name})
			print(f"{template}: dropped gate for retired status {gate.shipment_workflow_state!r}")


def _items(template: str) -> list:
	return frappe.get_all(
		ITEM,
		filters={"parent": template, "parenttype": TEMPLATE, "parentfield": "tasks"},
		fields=[
			"name",
			"sequence_no",
			"subject",
			"department_role",
			"task_role",
			"depends_on_sequences",
			"required_document_types",
		],
		order_by="sequence_no asc",
	)


def _gates(template: str) -> list:
	return frappe.get_all(
		GATE,
		filters={"parent": template, "parenttype": TEMPLATE, "parentfield": "gates"},
		fields=["name", "shipment_workflow_state", "min_completed_task_seq", "task_subject"],
		order_by="idx asc",
	)


def _find(rows, subject):
	return next((r for r in rows if (r.subject or "").strip() == subject), None)


def _set(doctype, name, values):
	frappe.db.set_value(doctype, name, values, update_modified=False)


def _point_gate(gate_name: str, seq: int, subjects: dict) -> None:
	"""Both halves move together, or the gate names one step and waits on another."""
	_set(GATE, gate_name, {"min_completed_task_seq": seq, "task_subject": subjects.get(seq, "")})


def _subjects_by_seq(template: str) -> dict:
	return {int(r.sequence_no or 0): (r.subject or "").strip() for r in _items(template)}


# --------------------------------------------------------------------------- import


def _align_air_import():
	if not frappe.db.exists(TEMPLATE, AIR_IMPORT):
		return
	_require_intake_documents()
	_rename_entry_payment()
	_make_intake_a_checkpoint()
	_insert_post_clearance_finance()
	_append_final_step()


def _require_intake_documents():
	intake = _find(_items(AIR_IMPORT), INTAKE_STEP)
	if intake and not (intake.required_document_types or "").strip():
		_set(ITEM, intake.name, {"required_document_types": _intake_documents()})
		print(f"{AIR_IMPORT}: {INTAKE_STEP!r} now needs {_intake_documents()}")


def _make_intake_a_checkpoint():
	"""The documentation officer confirms the client set the shipment starts with."""
	intake = _find(_items(AIR_IMPORT), INTAKE_STEP)
	if intake and (intake.task_role or "") != _intake_role():
		_set(ITEM, intake.name, {"task_role": _intake_role()})
		print(f"{AIR_IMPORT}: {INTAKE_STEP!r} is now a {_intake_role()}")


def _rename_entry_payment():
	old = _find(_items(AIR_IMPORT), ENTRY_PAYMENT_WAS)
	if not old:
		return
	_set(ITEM, old.name, {"subject": ENTRY_PAYMENT_NOW})
	for gate in _gates(AIR_IMPORT):
		if (gate.task_subject or "").strip() == ENTRY_PAYMENT_WAS:
			_set(GATE, gate.name, {"task_subject": ENTRY_PAYMENT_NOW})
	print(f"{AIR_IMPORT}: step {old.sequence_no} renamed to {ENTRY_PAYMENT_NOW!r}")


def _insert_post_clearance_finance():
	rows = _items(AIR_IMPORT)
	if _find(rows, POST_CLEARANCE_FINANCE):
		return
	application = _find(rows, POST_CLEARANCE_APPLICATION)
	if not application:
		print(f"{AIR_IMPORT}: no {POST_CLEARANCE_APPLICATION!r} step; left alone")
		return

	at = int(application.sequence_no or 0)
	# Open a slot: later rows and their dependencies move up one.
	for row in sorted(rows, key=lambda r: int(r.sequence_no or 0), reverse=True):
		seq = int(row.sequence_no or 0)
		if seq <= at:
			continue
		values = {"sequence_no": seq + 1}
		dep = (row.depends_on_sequences or "").strip()
		if dep.isdigit() and int(dep) >= at:
			values["depends_on_sequences"] = str(int(dep) + 1)
		_set(ITEM, row.name, values)

	template = frappe.get_doc(TEMPLATE, AIR_IMPORT)
	template.append("tasks", _new_step(POST_CLEARANCE_FINANCE, at))
	template.save(ignore_permissions=True)

	subjects = _subjects_by_seq(AIR_IMPORT)
	for gate in _gates(AIR_IMPORT):
		seq = int(gate.min_completed_task_seq or 0)
		if seq > at:
			_point_gate(gate.name, seq + 1, subjects)
		elif gate.shipment_workflow_state == "Post-clearance" and seq == at:
			# Reached when Finance has paid, as pre-clearance is.
			_point_gate(gate.name, at + 1, subjects)
	print(f"{AIR_IMPORT}: added {POST_CLEARANCE_FINANCE!r} at step {at + 1}")


def _append_final_step():
	rows = _items(AIR_IMPORT)
	if not rows or _find(rows, FINAL_STEP):
		return
	at = max(int(r.sequence_no or 0) for r in rows)

	template = frappe.get_doc(TEMPLATE, AIR_IMPORT)
	template.append("tasks", _new_step(FINAL_STEP, at))
	template.save(ignore_permissions=True)

	subjects = _subjects_by_seq(AIR_IMPORT)
	for gate in _gates(AIR_IMPORT):
		if gate.shipment_workflow_state == "Completed":
			_point_gate(gate.name, at + 1, subjects)
	print(f"{AIR_IMPORT}: added {FINAL_STEP!r} at step {at + 1}")


# --------------------------------------------------------------------------- export


def _align_air_export():
	if not frappe.db.exists(TEMPLATE, AIR_EXPORT):
		return
	rows = _items(AIR_EXPORT)
	# What each gate waits on now, so it can follow its step.
	by_seq = {int(r.sequence_no or 0): (r.subject or "").strip() for r in rows}
	gate_subject = {
		g.name: (g.task_subject or "").strip() or by_seq.get(int(g.min_completed_task_seq or 0), "")
		for g in _gates(AIR_EXPORT)
	}

	awb = _find(rows, AIRWAYBILL_STEP)
	if awb and (awb.department_role or "") != "Documentation":
		_set(ITEM, awb.name, {"department_role": "Documentation"})
		print(f"{AIR_EXPORT}: {AIRWAYBILL_STEP!r} moved to Documentation")

	dropped = [r for r in rows if (r.subject or "").strip() in AIR_EXPORT_DROPPED]
	for row in dropped:
		frappe.db.delete(ITEM, {"name": row.name})
	if dropped:
		print(f"{AIR_EXPORT}: dropped {sorted((r.subject or '') for r in dropped)}")

	template = frappe.get_doc(TEMPLATE, AIR_EXPORT)
	for subject in CLOSING_STEPS:
		if _find(template.tasks, subject):
			continue
		template.append(
			"tasks",
			{"subject": subject, "department_role": "Documentation", "task_role": "Standard"},
		)
		print(f"{AIR_EXPORT}: added {subject!r}")

	# One straight line, as it always was.
	kept = sorted(template.tasks, key=lambda r: (int(r.sequence_no or 0) or 9999, r.idx))
	for position, row in enumerate(kept, start=1):
		row.sequence_no = position
		row.depends_on_sequences = str(position - 1) if position > 1 else ""
		row.idx = position
	template.save(ignore_permissions=True)

	subjects = {int(r.sequence_no or 0): (r.subject or "").strip() for r in template.tasks}
	new_seq = {subject: seq for seq, subject in subjects.items()}
	last = max(subjects) if subjects else 0
	for gate in _gates(AIR_EXPORT):
		state = gate.shipment_workflow_state
		subject = gate_subject.get(gate.name, "")
		if state == "Completed":
			want = last
		elif subject in AIR_EXPORT_DROPPED:
			# The manifest marks the same moment the departure did.
			want = new_seq.get(MANIFEST_STEP, last)
		else:
			want = new_seq.get(subject, int(gate.min_completed_task_seq or 0))
		if want and (
			want != int(gate.min_completed_task_seq or 0)
			or (gate.task_subject or "") != subjects.get(want, "")
		):
			_point_gate(gate.name, want, subjects)
			print(f"{AIR_EXPORT}: gate {state} now waits on step {want}")


# --------------------------------------------------------------------------- live work


def _air_import_tasks(project_name: str) -> list:
	return frappe.get_all(
		"Task",
		filters={"project": project_name, "custom_task_flow_key": AIR_IMPORT},
		fields=["name", "subject", "custom_sequence_no", "status", "custom_task_role"],
		order_by="custom_sequence_no asc",
	)


def _stamp_intake_task(project_name: str, tasks: list) -> None:
	"""The template's intake rules reach a step nobody has worked yet."""
	intake = next((t for t in tasks if (t.subject or "").strip() == INTAKE_STEP), None)
	if not intake or intake.status in ("Completed", "Cancelled"):
		return
	values = {}
	if (intake.custom_task_role or "") != _intake_role():
		values["custom_task_role"] = _intake_role()
	if not (
		frappe.db.get_value("Task", intake.name, "custom_required_document_types") or ""
	).strip():
		values["custom_required_document_types"] = _intake_documents()
	if values:
		_set("Task", intake.name, values)
		print(f"{project_name}: {INTAKE_STEP!r} stamped {sorted(values)}")


def _add_task(project_name: str, subject: str, at: int, after: str) -> None:
	from cgm_shipping.cgm_worldwide_shipping.task_engine import (
		_create_single_task,
		_get_company_abbr,
	)

	project = frappe.get_doc("Project", project_name)
	frappe.flags.cgm_skip_task_project_sync = True
	try:
		_create_single_task(
			item=_new_step(subject, at),
			project=project,
			template_name=AIR_IMPORT,
			company_abbr=_get_company_abbr(project.company),
			created_map={at: after},
		)
	finally:
		frappe.flags.cgm_skip_task_project_sync = False
	print(f"{project_name}: added {subject!r} at step {at + 1}")


def _carry_live_air_import_projects():
	"""Give untouched air import shipments the steps their template just gained."""
	projects = {
		row.project
		for row in frappe.get_all(
			"Task", filters={"custom_task_flow_key": AIR_IMPORT}, fields=["project"]
		)
		if row.project
	}
	for project_name in sorted(projects):
		tasks = _air_import_tasks(project_name)
		_stamp_intake_task(project_name, tasks)

		worked = [t for t in tasks if t.status in ("Completed", "Cancelled")]
		if worked:
			# Renumbering or gating a step under way would disrupt it.
			print(f"{project_name}: {len(worked)} step(s) already worked; left as it is")
			continue

		old = next((t for t in tasks if (t.subject or "").strip() == ENTRY_PAYMENT_WAS), None)
		if old:
			_set("Task", old.name, {"subject": ENTRY_PAYMENT_NOW})

		application = next(
			(t for t in tasks if (t.subject or "").strip() == POST_CLEARANCE_APPLICATION), None
		)
		if application and not any(
			(t.subject or "").strip() == POST_CLEARANCE_FINANCE for t in tasks
		):
			at = int(application.custom_sequence_no or 0)
			for task in sorted(tasks, key=lambda t: int(t.custom_sequence_no or 0), reverse=True):
				seq = int(task.custom_sequence_no or 0)
				if seq > at:
					_set("Task", task.name, {"custom_sequence_no": seq + 1})
			_add_task(project_name, POST_CLEARANCE_FINANCE, at, application.name)
			tasks = _air_import_tasks(project_name)

		if tasks and not any((t.subject or "").strip() == FINAL_STEP for t in tasks):
			last = max(tasks, key=lambda t: int(t.custom_sequence_no or 0))
			_add_task(project_name, FINAL_STEP, int(last.custom_sequence_no or 0), last.name)
