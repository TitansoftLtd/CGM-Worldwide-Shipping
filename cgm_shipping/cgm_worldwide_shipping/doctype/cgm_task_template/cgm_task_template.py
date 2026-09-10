# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
	ROLE_APPLICATION,
	ROLE_AUTO_COMPLETE,
	ROLE_FINANCE_PAYMENT,
	ROLE_PERMIT_APPLICATION,
	ROLE_PERMIT_FINANCE,
)

PAYMENT_KIND_ROLES = (ROLE_APPLICATION, ROLE_FINANCE_PAYMENT)
PERMIT_STAGE_ROLES = (ROLE_PERMIT_APPLICATION, ROLE_PERMIT_FINANCE)


class CGMTaskTemplate(Document):
	"""A workflow plan. Every task a project gets is stamped from these rows.

	The stamps drive department visibility, finance pairing, permit flow and
	document gating, so a bad row here surfaces later as a task nobody can see
	or complete. These checks fail the save instead.
	"""

	def validate(self):
		self.validate_unique_sequences()
		self.validate_departments_resolve()
		self.validate_dependencies_resolve()
		self.validate_role_requirements()
		self.validate_finance_pairs()
		self.validate_completion_conditions()
		self.validate_required_document_types()

	def _rows(self):
		return self.get("tasks") or []

	def _label(self, row) -> str:
		return f"{_('Row')} {row.idx} ({row.get('subject') or _('untitled')})"

	def validate_unique_sequences(self) -> None:
		"""Sequence numbers key everything downstream - duplicates collide silently."""
		seen: dict[int, str] = {}
		for row in self._rows():
			seq = int(row.get("sequence_no") or 0)
			if not seq:
				frappe.throw(
					_("{0}: Sequence is required.").format(self._label(row)),
					title=_("Missing Sequence"),
				)
			if seq in seen:
				frappe.throw(
					_("Sequence {0} is used twice: {1} and {2}. Task behaviour, "
					  "department visibility and finance pairing all key on it.").format(
						frappe.bold(seq), seen[seq], self._label(row)
					),
					title=_("Duplicate Sequence"),
				)
			seen[seq] = self._label(row)

	def validate_departments_resolve(self) -> None:
		"""A stem with no matching Department produces an invisible task.

		Task creation appends the company abbreviation to this stem, and the
		department drives who can see the task. A typo here does not fail - it
		creates a task pointing at a department nobody belongs to. Checked
		against the Department master rather than a hardcoded list, so a site
		can name its departments however it likes.
		"""
		from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
			normalize_department_stem,
		)

		known = {
			row.department_name
			for row in frappe.get_all(
				"Department", filters={"disabled": 0}, fields=["department_name"]
			)
			if row.department_name
		}
		if not known:
			return  # fresh site, departments not seeded yet

		for row in self._rows():
			stem = normalize_department_stem(row.get("department_role"))
			if not stem:
				frappe.throw(
					_("{0}: Department is required.").format(self._label(row)),
					title=_("Missing Department"),
				)
			if stem not in known:
				frappe.throw(
					_("{0}: no Department named {1}. Tasks would be created against a "
					  "department nobody belongs to, and hidden from everyone. "
					  "Existing departments: {2}").format(
						self._label(row), frappe.bold(stem), ", ".join(sorted(known))
					),
					title=_("Unknown Department"),
				)

	def validate_dependencies_resolve(self) -> None:
		"""A dependency on a sequence that is not in this template never links."""
		sequences = {int(r.get("sequence_no") or 0) for r in self._rows()}
		for row in self._rows():
			raw = (row.get("depends_on_sequences") or "").strip()
			if not raw:
				continue
			for token in raw.split(","):
				token = token.strip()
				if not token:
					continue
				if not token.isdigit() or int(token) not in sequences:
					frappe.throw(
						_("{0}: Depends On sequence {1} is not a task in this template.").format(
							self._label(row), frappe.bold(token)
						),
						title=_("Unknown Dependency"),
					)
				if int(token) == int(row.get("sequence_no") or 0):
					frappe.throw(
						_("{0}: A task cannot depend on itself.").format(self._label(row)),
						title=_("Invalid Dependency"),
					)

	def uses_paired_finance(self) -> bool:
		"""True when this template drives the Application -> Finance Payment flow.

		Import plans pair every finance step with an Application the Declarant
		attaches the invoice to. The export and outbound plans have finance steps
		with no Application rows at all - Finance simply records the payment.
		Payment Kind means nothing there, so the pairing warnings stay quiet.
		"""
		return any(
			(row.get("task_role") or "").strip() == ROLE_APPLICATION for row in self._rows()
		)

	def validate_role_requirements(self) -> None:
		"""Roles that drive finance / permit flow need the field that selects it.

		A missing Payment Kind degrades that step (no invoice copy, no receipt
		sync) but does not corrupt anything, and several templates predate this
		check - so it warns rather than blocking an unrelated edit. The permit
		stage is a hard requirement: the permit flow cannot pick a side without it.
		"""
		missing_kind = [
			self._label(row)
			for row in self._rows()
			if (row.get("task_role") or "").strip() in PAYMENT_KIND_ROLES
			and not (row.get("payment_kind") or "").strip()
		]
		if missing_kind and self.uses_paired_finance():
			frappe.msgprint(
				_("No Payment Kind on: {0}. Those steps will not copy invoices or sync "
				  "receipts until one is set - it pairs the Application with the "
				  "Finance Payment that settles it.").format(", ".join(missing_kind)),
				title=_("Missing Payment Kind"),
				indicator="orange",
			)

		for row in self._rows():
			role = (row.get("task_role") or "").strip()
			if role in PERMIT_STAGE_ROLES and not (row.get("permit_stage") or "").strip():
				frappe.throw(
					_("{0}: {1} tasks need a Permit Stage (Pre-clearance or Post-clearance).").format(
						self._label(row), frappe.bold(role)
					),
					title=_("Missing Permit Stage"),
				)

	def validate_finance_pairs(self) -> None:
		"""Every Finance Payment settles an Application of the same Payment Kind."""
		if not self.uses_paired_finance():
			return
		applications = {
			(r.get("payment_kind") or "").strip()
			for r in self._rows()
			if (r.get("task_role") or "").strip() == ROLE_APPLICATION
		}
		for row in self._rows():
			if (row.get("task_role") or "").strip() != ROLE_FINANCE_PAYMENT:
				continue
			kind = (row.get("payment_kind") or "").strip()
			if kind and kind not in applications:
				# Warn, not block: the pair may legitimately live in a template this
				# one extends, and an unpaired finance step degrades rather than breaks.
				frappe.msgprint(
					_("{0} pays {1}, but this template has no Application task for it. "
					  "Invoice copy and receipt sync need both halves.").format(
						self._label(row), frappe.bold(kind)
					),
					title=_("Unpaired Finance Task"),
					indicator="orange",
				)

	def validate_completion_conditions(self) -> None:
		"""A malformed condition silently never fires - the task waits forever."""
		project_meta = frappe.get_meta("Project")
		for row in self._rows():
			condition = (row.get("completion_condition") or "").strip()
			if not condition:
				continue
			parts = condition.split(".", 1)
			if len(parts) != 2 or parts[0] != "project" or not parts[1]:
				frappe.throw(
					_("{0}: Completion Condition must look like {1}.").format(
						self._label(row), frappe.bold("project.fieldname")
					),
					title=_("Invalid Completion Condition"),
				)
			if not project_meta.has_field(parts[1]):
				frappe.throw(
					_("{0}: Project has no field {1}.").format(
						self._label(row), frappe.bold(parts[1])
					),
					title=_("Unknown Project Field"),
				)

	def validate_required_document_types(self) -> None:
		"""Make Required Document Types behave like a link to Document Type.

		It cannot be a Table MultiSelect - CGM Task Template Item is itself a
		child table and Frappe does not support a table inside a table (see
		patches/fix_cgm_task_template_item_nested_table). Unknown names are
		rejected here instead, and accepted ones rewritten to the canonical
		Document Type name so the template, the Task stamp, the seeded Task
		Documents rows and the completion check all agree.
		"""
		from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
			parse_required_document_types,
			resolve_legacy_document_type_name,
			serialize_required_document_types,
		)

		for row in self._rows():
			tokens = parse_required_document_types(row.get("required_document_types"))
			if not tokens:
				continue

			resolved: list[str] = []
			unknown: list[str] = []
			for token in tokens:
				name = resolve_legacy_document_type_name(token)
				if not name:
					unknown.append(token)
				elif name not in resolved:
					resolved.append(name)

			if unknown:
				frappe.throw(
					_("{0}: {1} is not a Document Type. Pick from the Document Type list.").format(
						self._label(row), ", ".join(frappe.bold(u) for u in unknown)
					),
					title=_("Unknown Document Type"),
				)

			row.required_document_types = serialize_required_document_types(resolved)


def sync_open_tasks_from_template(doc, _method=None):
	"""When admins edit Required Document Types, push changes onto open Tasks."""
	if frappe.flags.in_import or frappe.flags.in_patch:
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		sync_tasks_for_template,
	)

	sync_tasks_for_template(doc.name)
