"""Configuration-driven application + finance payment workflows (UCR, Entry Slip, …).

Profiles are registered in APPLICATION_FINANCE_PROFILES; task sequence pairing comes from
CGM Shipping Settings (requirement types + Finance Payment kind), not from hardcoded seq numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import frappe
from frappe.utils import cint, flt, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	ENTRY_INVOICE_TO_FINANCE,
	ENTRY_RECEIPT_FOR_DECLARANT,
	ENTRY_RECEIPT_VERIFY_FINANCE,
	SHIPPING_LINE_INVOICE_TO_FINANCE,
	SHIPPING_LINE_RECEIPT_FOR_DECLARANT,
	SHIPPING_LINE_RECEIPT_VERIFY_FINANCE,
	SEA_TASK_FLOW_KEY,
	SHIPMENT_DOCUMENTS_FIELD,
	TASK_DOCUMENTS_FIELD,
	TASK_FINANCE_FIELD,
	UCR_INVOICE_TO_FINANCE,
	UCR_RECEIPT_FOR_DECLARANT,
	UCR_RECEIPT_VERIFY_FINANCE,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
	append_verified_doc_row,
	get_document_type_link_name,
)

LINE_INVOICE = "Invoice"
LINE_RECEIPT = "Receipt"


@dataclass(frozen=True)
class ApplicationFinanceProfile:
	"""Metadata for one application → finance payment subflow."""

	key: str
	application_requirement_type: str
	finance_payment_kind: str
	payment_item: str
	invoice_label: str
	receipt_label: str
	certificate_document_code: str
	gate_rule: str
	notification_invoice: str
	notification_receipt_declarant: str
	notification_receipt_verify: str
	application_submitted_field: str | None
	application_invoice_verified_field: str | None
	application_receipt_verified_field: str | None
	sync_to_idf_record: bool
	legacy_certificate_codes: frozenset[str]


APPLICATION_FINANCE_PROFILES: dict[str, ApplicationFinanceProfile] = {
	"UCR Application": ApplicationFinanceProfile(
		key="ucr",
		application_requirement_type="UCR Application",
		finance_payment_kind="UCR",
		payment_item="UCR",
		invoice_label="UCR Invoice",
		receipt_label="UCR Receipt",
		certificate_document_code="IDF_CERT",
		gate_rule="UCR Finance Complete",
		notification_invoice=UCR_INVOICE_TO_FINANCE,
		notification_receipt_declarant=UCR_RECEIPT_FOR_DECLARANT,
		notification_receipt_verify=UCR_RECEIPT_VERIFY_FINANCE,
		application_submitted_field="custom_ucr_invoice_submitted",
		application_invoice_verified_field="custom_ucr_invoice_verified",
		application_receipt_verified_field="custom_ucr_receipt_verified",
		sync_to_idf_record=True,
		legacy_certificate_codes=frozenset({"IDF_CERT", "UCR_CERT", "IDF"}),
	),
	"Entry Application": ApplicationFinanceProfile(
		key="entry",
		application_requirement_type="Entry Application",
		finance_payment_kind="Entry Slip",
		payment_item="ENTRY_SLIP",
		invoice_label="Entry Slip Invoice",
		receipt_label="Entry Slip Receipt",
		certificate_document_code="ENTRY",
		gate_rule="Entry Finance Complete",
		notification_invoice=ENTRY_INVOICE_TO_FINANCE,
		notification_receipt_declarant=ENTRY_RECEIPT_FOR_DECLARANT,
		notification_receipt_verify=ENTRY_RECEIPT_VERIFY_FINANCE,
		application_submitted_field=None,
		application_invoice_verified_field=None,
		application_receipt_verified_field=None,
		sync_to_idf_record=False,
		legacy_certificate_codes=frozenset({"ENTRY"}),
	),
	"Shipping Line Application": ApplicationFinanceProfile(
		key="shipping_line",
		application_requirement_type="Shipping Line Application",
		finance_payment_kind="Shipping Line",
		payment_item="Shipping Line",
		invoice_label="Shipping Line Invoice",
		receipt_label="Shipping Line Receipt",
		certificate_document_code="",
		gate_rule="Standard",
		notification_invoice=SHIPPING_LINE_INVOICE_TO_FINANCE,
		notification_receipt_declarant=SHIPPING_LINE_RECEIPT_FOR_DECLARANT,
		notification_receipt_verify=SHIPPING_LINE_RECEIPT_VERIFY_FINANCE,
		application_submitted_field=None,
		application_invoice_verified_field=None,
		application_receipt_verified_field=None,
		sync_to_idf_record=False,
		legacy_certificate_codes=frozenset(),
	),
}


def all_profiles() -> tuple[ApplicationFinanceProfile, ...]:
	return tuple(APPLICATION_FINANCE_PROFILES.values())


def profile_by_requirement_type(requirement_type: str) -> ApplicationFinanceProfile | None:
	return APPLICATION_FINANCE_PROFILES.get(requirement_type)


def profile_by_finance_kind(kind: str) -> ApplicationFinanceProfile | None:
	normalized = (kind or "").strip()
	for profile in all_profiles():
		if profile.finance_payment_kind == normalized:
			return profile
	return None


def profile_by_payment_item(payment_item: str) -> ApplicationFinanceProfile | None:
	key = (payment_item or "").strip()
	for profile in all_profiles():
		if profile.payment_item == key:
			return profile
	return None


def _rows_by_sequence():
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import rows_by_sequence

	return rows_by_sequence()


def _get_finance_payment_kind(sequence_no: int) -> str | None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import get_finance_payment_kind

	return get_finance_payment_kind(sequence_no)


def is_application_task(sequence_no: int, profile: ApplicationFinanceProfile) -> bool:
	return any(
		r.requirement_type == profile.application_requirement_type
		for r in _rows_by_sequence().get(sequence_no, [])
	)


def is_application_finance_task(sequence_no: int, profile: ApplicationFinanceProfile) -> bool:
	return _get_finance_payment_kind(sequence_no) == profile.finance_payment_kind


def is_application_workflow_task(sequence_no: int, profile: ApplicationFinanceProfile) -> bool:
	return is_application_task(sequence_no, profile) or is_application_finance_task(
		sequence_no, profile
	)


def application_sequences(profile: ApplicationFinanceProfile) -> frozenset[int]:
	return frozenset(
		seq
		for seq, rows in _rows_by_sequence().items()
		if any(r.requirement_type == profile.application_requirement_type for r in rows)
	)


def application_finance_sequences(profile: ApplicationFinanceProfile) -> frozenset[int]:
	return frozenset(
		seq
		for seq in _rows_by_sequence()
		if is_application_finance_task(seq, profile)
	)


def get_application_sequence(profile: ApplicationFinanceProfile) -> int | None:
	seqs = sorted(application_sequences(profile))
	return seqs[0] if seqs else None


def get_application_finance_sequence(profile: ApplicationFinanceProfile) -> int | None:
	seqs = sorted(application_finance_sequences(profile))
	return seqs[0] if seqs else None


def get_application_task(project: str, profile: ApplicationFinanceProfile) -> str | None:
	seq = get_application_sequence(profile)
	if not seq or not project:
		return None
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import get_task_name_by_sequence

	return get_task_name_by_sequence(project, seq)


def get_application_finance_task(project: str, profile: ApplicationFinanceProfile) -> str | None:
	seq = get_application_finance_sequence(profile)
	if not seq or not project:
		return None
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import get_task_name_by_sequence

	return get_task_name_by_sequence(project, seq)


def profile_for_task(task) -> ApplicationFinanceProfile | None:
	seq = int(task.get("custom_sequence_no") or 0)
	for profile in all_profiles():
		if is_application_workflow_task(seq, profile):
			return profile
	return None


def task_has_finance_table(task) -> bool:
	return bool(task.meta.has_field(TASK_FINANCE_FIELD))


def _find_line(task, line_type: str, profile: ApplicationFinanceProfile):
	if not task:
		return None
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if row.line_type == line_type and (row.payment_item or profile.payment_item) == profile.payment_item:
			return row
	return None


def get_invoice_line(task, profile: ApplicationFinanceProfile):
	return _find_line(task, LINE_INVOICE, profile)


def get_receipt_line(task, profile: ApplicationFinanceProfile):
	return _find_line(task, LINE_RECEIPT, profile)


def invoice_attached(task, profile: ApplicationFinanceProfile) -> bool:
	line = get_invoice_line(task, profile)
	return bool(line and line.attachment)


def receipt_attached(task, profile: ApplicationFinanceProfile) -> bool:
	line = get_receipt_line(task, profile)
	return bool(line and line.attachment)


def invoice_verified(task, profile: ApplicationFinanceProfile) -> bool:
	line = get_invoice_line(task, profile)
	return bool(line and line.verified)


def receipt_verified(task, profile: ApplicationFinanceProfile) -> bool:
	line = get_receipt_line(task, profile)
	return bool(line and line.verified)


def _ensure_line(task, line_type: str, profile: ApplicationFinanceProfile):
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_purchase_item_for_payment_item,
		task_finance_line_has_item_code,
	)

	label = profile.invoice_label if line_type == LINE_INVOICE else profile.receipt_label
	row = _find_line(task, line_type, profile)
	if row:
		if not row.line_label:
			row.line_label = label
		if (
			line_type == LINE_INVOICE
			and task_finance_line_has_item_code()
			and not row.get("item_code")
		):
			row.item_code = get_purchase_item_for_payment_item(profile.payment_item, task.company)
		return row
	payload = {
		"line_label": label,
		"line_type": line_type,
		"payment_item": profile.payment_item,
	}
	if line_type == LINE_INVOICE and task_finance_line_has_item_code():
		payload["item_code"] = get_purchase_item_for_payment_item(profile.payment_item, task.company)
	task.append(TASK_FINANCE_FIELD, payload)
	return task.get(TASK_FINANCE_FIELD)[-1]


def seed_application_finance_lines(task, profile: ApplicationFinanceProfile) -> None:
	if not task_has_finance_table(task):
		return
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_application_workflow_task(seq, profile):
		return
	_ensure_line(task, LINE_INVOICE, profile)
	_ensure_line(task, LINE_RECEIPT, profile)
	if is_application_finance_task(seq, profile):
		copy_application_invoice_to_finance_task(task, profile)


def ensure_application_finance_lines_saved(task, profile: ApplicationFinanceProfile) -> bool:
	if not task_has_finance_table(task):
		return False
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_application_workflow_task(seq, profile):
		return False
	before = {
		(r.line_type, r.payment_item or profile.payment_item)
		for r in task.get(TASK_FINANCE_FIELD) or []
	}
	seed_application_finance_lines(task, profile)
	after = {
		(r.line_type, r.payment_item or profile.payment_item)
		for r in task.get(TASK_FINANCE_FIELD) or []
	}
	if after - before:
		frappe.flags.cgm_ensuring_application_finance_lines = True
		try:
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_ensuring_application_finance_lines = False
		return True
	return False


def copy_application_invoice_to_finance_task(
	finance_task, profile: ApplicationFinanceProfile
) -> None:
	if not is_application_finance_task(int(finance_task.get("custom_sequence_no") or 0), profile):
		return
	if not finance_task.project:
		return
	app_name = get_application_task(finance_task.project, profile)
	if not app_name:
		return
	app = frappe.get_doc("Task", app_name)
	app_line = get_invoice_line(app, profile)
	if not app_line or not app_line.attachment:
		return
	fin_line = _ensure_line(finance_task, LINE_INVOICE, profile)
	if not fin_line.attachment:
		fin_line.attachment = app_line.attachment
	if app_line.amount and not fin_line.amount:
		fin_line.amount = app_line.amount
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_purchase_item_for_payment_item,
		task_finance_line_has_item_code,
	)

	if task_finance_line_has_item_code():
			app_item = app_line.get("item_code")
			fin_item = fin_line.get("item_code")
			if app_item and not fin_item:
				fin_line.item_code = app_item
			elif not fin_item:
				fin_line.item_code = get_purchase_item_for_payment_item(
					profile.payment_item, finance_task.company
				)


def copy_application_receipt_to_finance_task(
	application_task, profile: ApplicationFinanceProfile
) -> str | None:
	if not is_application_task(int(application_task.get("custom_sequence_no") or 0), profile):
		return None
	if not application_task.project:
		return None
	app_rec = get_receipt_line(application_task, profile)
	if not app_rec or not app_rec.attachment:
		return None
	finance_name = get_application_finance_task(application_task.project, profile)
	if not finance_name:
		return None
	finance_task = frappe.get_doc("Task", finance_name)
	seed_application_finance_lines(finance_task, profile)
	fin_rec = get_receipt_line(finance_task, profile)
	if not fin_rec:
		return None
	if not fin_rec.name:
		frappe.flags.cgm_syncing_application_receipt = True
		try:
			finance_task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_application_receipt = False
		fin_rec = get_receipt_line(frappe.get_doc("Task", finance_name), profile)
		if not fin_rec:
			return None
	if fin_rec.attachment == app_rec.attachment:
		return finance_name
	updates = {"attachment": app_rec.attachment}
	if app_rec.amount and not fin_rec.amount:
		updates["amount"] = app_rec.amount
	frappe.db.set_value("Task Finance Line", fin_rec.name, updates, update_modified=False)
	return finance_name


def application_payment_made_for_project(
	project: str, profile: ApplicationFinanceProfile
) -> bool:
	if not project:
		return False
	finance_name = get_application_finance_task(project, profile)
	if not finance_name:
		return False
	pe_name = frappe.db.get_value("Task", finance_name, "custom_payment_entry")
	if not pe_name:
		return False
	return int(frappe.db.get_value("Payment Entry", pe_name, "docstatus") or 0) == 1


def ensure_certificate_document_row(task, profile: ApplicationFinanceProfile) -> None:
	"""Application task: certificate doc on Clearance Documents (optional until issued)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_document_type_code,
		is_invoice_clearance_document_row,
		remove_invoice_rows_from_task_documents,
	)

	if not is_application_task(int(task.get("custom_sequence_no") or 0), profile):
		return
	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return
	remove_invoice_rows_from_task_documents(task)
	dt_name = get_document_type_link_name(profile.certificate_document_code)
	if not dt_name:
		return
	existing = {r.document_type for r in task.get(TASK_DOCUMENTS_FIELD) or [] if r.document_type}
	if dt_name in existing:
		return
	task.append(TASK_DOCUMENTS_FIELD, {"document_type": dt_name, "status": "Missing"})


def prepare_application_task_tables(task, profile: ApplicationFinanceProfile) -> None:
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_application_workflow_task(seq, profile):
		return
	seed_application_finance_lines(task, profile)
	if is_application_task(seq, profile):
		ensure_certificate_document_row(task, profile)
	elif is_application_finance_task(seq, profile):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			remove_invoice_rows_from_task_documents,
		)

		remove_invoice_rows_from_task_documents(task)
		copy_application_invoice_to_finance_task(task, profile)


def certificate_uploaded(task, profile: ApplicationFinanceProfile) -> bool:
	if not profile.certificate_document_code and not profile.legacy_certificate_codes:
		return True
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import get_document_type_code

	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		code = get_document_type_code(row.document_type)
		if code in profile.legacy_certificate_codes and row.attachment:
			return True
	return False


def sync_certificate_to_project(task, profile: ApplicationFinanceProfile) -> None:
	if not task.project:
		return
	cert_url = None
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import get_document_type_code

	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		code = get_document_type_code(row.document_type)
		if code in profile.legacy_certificate_codes and row.attachment:
			cert_url = row.attachment
			break
	if not cert_url:
		return
	project = frappe.get_doc("Project", task.project)
	dt_name = get_document_type_link_name(profile.certificate_document_code)
	if dt_name and project.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		append_verified_doc_row(project, dt_name, cert_url)
		frappe.flags.cgm_syncing_permits = True
		try:
			project.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_permits = False
	if profile.sync_to_idf_record and frappe.db.exists("DocType", "IDF UCR Record"):
		idf_meta = frappe.get_meta("IDF UCR Record")
		if idf_meta.has_field("idf_certificate"):
			record_name = frappe.db.get_value("IDF UCR Record", {"project": task.project}, "name")
			if record_name:
				frappe.db.set_value(
					"IDF UCR Record",
					record_name,
					"idf_certificate",
					cert_url,
					update_modified=True,
				)


def sync_application_finance_lines_to_idf_record(task, profile: ApplicationFinanceProfile) -> None:
	"""Mirror invoice/receipt from Task Finance → Project IDF UCR Record (UCR profile only)."""
	if not profile.sync_to_idf_record:
		return
	if not task.project or not frappe.db.exists("DocType", "IDF UCR Record"):
		return
	if not task_has_finance_table(task):
		return
	record_name = frappe.db.get_value("IDF UCR Record", {"project": task.project}, "name")
	if record_name:
		doc = frappe.get_doc("IDF UCR Record", record_name)
	else:
		doc = frappe.new_doc("IDF UCR Record")
		doc.project = task.project
	inv = get_invoice_line(task, profile)
	rec = get_receipt_line(task, profile)
	if inv and inv.attachment:
		doc.payment_invoice = inv.attachment
		if doc.payment_status in (None, "", "Pending Invoice"):
			doc.payment_status = "Invoice Submitted"
	if inv and inv.verified:
		doc.invoice_verified = 1
		doc.payment_status = "Invoice Verified"
	if task.get("custom_purchase_invoice"):
		doc.purchase_invoice = task.custom_purchase_invoice
	if task.get("custom_payment_entry"):
		doc.payment_entry = task.custom_payment_entry
		doc.payment_status = "Paid"
	if rec and rec.attachment:
		doc.payment_receipt = rec.attachment
		doc.payment_status = "Receipt Submitted"
	if rec and rec.verified:
		doc.receipt_verified = 1
		doc.payment_status = "Receipt Verified"
	if task.status == "Completed" and is_application_finance_task(
		int(task.get("custom_sequence_no") or 0), profile
	):
		doc.payment_status = "Complete"
	doc.save(ignore_permissions=True)


def _sync_line_verification_to_application(
	finance_task,
	profile: ApplicationFinanceProfile,
	line_getter: Callable,
	line_type: str,
	app_field: str | None,
	*,
	seed: bool = False,
) -> bool:
	if (
		not is_application_finance_task(int(finance_task.get("custom_sequence_no") or 0), profile)
		or not finance_task.project
		or not task_has_finance_table(finance_task)
	):
		return False
	app_name = get_application_task(finance_task.project, profile)
	if not app_name:
		return False
	if seed:
		seed_application_finance_lines(finance_task, profile)
	fin_line = line_getter(finance_task, profile)
	if not fin_line or not fin_line.verified:
		return False
	app_line_name = frappe.db.get_value(
		"Task Finance Line",
		{
			"parent": app_name,
			"parenttype": "Task",
			"parentfield": TASK_FINANCE_FIELD,
			"line_type": line_type,
			"payment_item": profile.payment_item,
		},
		"name",
	)
	if not app_line_name:
		return False
	changed = False
	if not frappe.db.get_value("Task Finance Line", app_line_name, "verified"):
		frappe.db.set_value(
			"Task Finance Line",
			app_line_name,
			{
				"verified": 1,
				"verified_by": fin_line.verified_by,
				"verified_on": fin_line.verified_on,
			},
			update_modified=False,
		)
		changed = True
	if app_field:
		app_task = frappe.get_doc("Task", app_name)
		if app_task.meta.has_field(app_field) and not app_task.get(app_field):
			frappe.db.set_value("Task", app_name, app_field, 1, update_modified=False)
			changed = True
	return changed


def sync_invoice_verification_to_application_task(
	finance_task, profile: ApplicationFinanceProfile
) -> bool:
	return _sync_line_verification_to_application(
		finance_task,
		profile,
		get_invoice_line,
		LINE_INVOICE,
		profile.application_invoice_verified_field,
		seed=True,
	)


def sync_receipt_verification_to_application_task(
	finance_task, profile: ApplicationFinanceProfile
) -> bool:
	return _sync_line_verification_to_application(
		finance_task,
		profile,
		get_receipt_line,
		LINE_RECEIPT,
		profile.application_receipt_verified_field,
	)


def sync_status_from_finance_to_application(
	application_task, profile: ApplicationFinanceProfile
) -> bool:
	if not is_application_task(int(application_task.get("custom_sequence_no") or 0), profile):
		return False
	if not application_task.project:
		return False
	finance_name = get_application_finance_task(application_task.project, profile)
	if not finance_name:
		return False
	finance_task = frappe.get_doc("Task", finance_name)
	changed = sync_invoice_verification_to_application_task(finance_task, profile)
	changed = sync_receipt_verification_to_application_task(finance_task, profile) or changed
	return changed


def invoice_submitted(task_name: str, profile: ApplicationFinanceProfile) -> bool:
	if not task_name or not frappe.db.exists("Task", task_name):
		return False
	task = frappe.get_doc("Task", task_name)
	if (
		profile.application_submitted_field
		and task.meta.has_field(profile.application_submitted_field)
		and task.get(profile.application_submitted_field)
	):
		return True
	if task_has_finance_table(task):
		return invoice_attached(task, profile)
	return False


def project_has_submitted_invoice(project: str, profile: ApplicationFinanceProfile) -> bool:
	task_name = get_application_task(project, profile)
	return bool(task_name and invoice_submitted(task_name, profile))


def invoice_verified_for_application_task(
	task, profile: ApplicationFinanceProfile, finance_task=None
) -> bool:
	if (
		profile.application_invoice_verified_field
		and task.get(profile.application_invoice_verified_field)
	):
		return True
	if invoice_verified(task, profile):
		return True
	if finance_task is None and task.project:
		finance_name = get_application_finance_task(task.project, profile)
		finance_task = frappe.get_doc("Task", finance_name) if finance_name else None
	if finance_task:
		fin_inv = get_invoice_line(finance_task, profile)
		if fin_inv and fin_inv.verified:
			return True
	return False


def receipt_attached_for_payment_workflow(
	task, profile: ApplicationFinanceProfile
) -> bool:
	if receipt_attached(task, profile):
		return True
	if not task.project:
		return False
	app_name = get_application_task(task.project, profile)
	if not app_name:
		return False
	app = frappe.get_doc("Task", app_name)
	return receipt_attached(app, profile)


def can_complete_application_task(
	task, profile: ApplicationFinanceProfile, finance_task=None
) -> bool:
	if not is_application_task(int(task.get("custom_sequence_no") or 0), profile):
		return False
	submitted = invoice_attached(task, profile)
	if profile.application_submitted_field and task.meta.has_field(profile.application_submitted_field):
		submitted = submitted or bool(task.get(profile.application_submitted_field))
	if not submitted:
		return False
	if not invoice_verified_for_application_task(task, profile, finance_task):
		return False
	if not receipt_attached(task, profile):
		return False
	return certificate_uploaded(task, profile)


def can_complete_application_finance_task(task, profile: ApplicationFinanceProfile) -> bool:
	if not is_application_finance_task(int(task.get("custom_sequence_no") or 0), profile):
		return False
	if task.project and not project_has_submitted_invoice(task.project, profile):
		return False
	inv_ok = invoice_verified(task, profile)
	if profile.application_invoice_verified_field:
		inv_ok = inv_ok or bool(task.get(profile.application_invoice_verified_field))
	if not inv_ok:
		return False
	rec_ok = receipt_verified(task, profile)
	if profile.application_receipt_verified_field:
		rec_ok = rec_ok or bool(task.get(profile.application_receipt_verified_field))
	if not rec_ok:
		return False
	if not receipt_attached_for_payment_workflow(task, profile):
		return False
	return True


def build_application_purchase_invoice_lines(
	task, profile: ApplicationFinanceProfile
) -> list[dict]:
	if not is_application_finance_task(int(task.get("custom_sequence_no") or 0), profile):
		return []
	inv = get_invoice_line(task, profile)
	if not inv or not flt(inv.amount):
		return []
	amount = flt(inv.amount)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_purchase_item_for_payment_item,
		task_finance_line_has_item_code,
	)

	item_code = (
		inv.get("item_code") if task_finance_line_has_item_code() else None
	) or get_purchase_item_for_payment_item(profile.payment_item, task.company)
	item_name = frappe.db.get_value("Item", item_code, "item_name") or profile.invoice_label
	desc = profile.invoice_label
	if inv.attachment:
		desc += f" (ref: {inv.attachment.split('/')[-1]})"
	return [
		{
			"item_code": item_code,
			"item_name": item_name,
			"description": desc,
			"qty": 1,
			"rate": amount,
			"amount": amount,
			"project": task.project,
			"payment_item": profile.payment_item,
		}
	]


def normalize_application_finance_verification(task, profile: ApplicationFinanceProfile) -> None:
	if not task_has_finance_table(task):
		return
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_application_workflow_task(seq, profile):
		return
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if (row.payment_item or profile.payment_item) != profile.payment_item:
			continue
		if row.verified:
			if not row.verified_by:
				row.verified_by = frappe.session.user
			if not row.verified_on:
				row.verified_on = now_datetime()
		elif row.verified_by or row.verified_on:
			row.verified_by = None
			row.verified_on = None
	if is_application_finance_task(seq, profile):
		inv = get_invoice_line(task, profile)
		rec = get_receipt_line(task, profile)
		if (
			inv
			and inv.verified
			and profile.application_invoice_verified_field
			and task.meta.has_field(profile.application_invoice_verified_field)
		):
			setattr(task, profile.application_invoice_verified_field, 1)
		if (
			rec
			and rec.verified
			and profile.application_receipt_verified_field
			and task.meta.has_field(profile.application_receipt_verified_field)
		):
			setattr(task, profile.application_receipt_verified_field, 1)


def enforce_application_finance_line_permissions(
	task, profile: ApplicationFinanceProfile
) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		user_has_department_for_sequence,
		user_has_finance_department_access,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import _finance_line_verified_changed

	if frappe.session.user == "Administrator":
		return
	if frappe.flags.get("cgm_syncing_application_receipt") or frappe.flags.get(
		"cgm_ensuring_application_finance_lines"
	):
		return
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_application_workflow_task(seq, profile) or not task_has_finance_table(task):
		return
	is_finance = user_has_finance_department_access()
	can_attach_receipt = user_has_department_for_sequence(frappe.session.user, seq)
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if (row.payment_item or profile.payment_item) != profile.payment_item:
			continue
		if row.verified and not is_finance and _finance_line_verified_changed(task, row):
			frappe.throw(
				f"Only <b>Finance</b> can verify <b>{row.line_label or 'finance line'}</b>."
			)
		if not row.verified and not is_finance and _finance_line_verified_changed(task, row):
			prev = task.get_doc_before_save()
			prev_row = _find_line(prev, row.line_type, profile) if prev else None
			if prev_row and cint(prev_row.verified):
				frappe.throw(
					f"<b>{row.line_label or 'Finance line'}</b> is verified by Finance and cannot be changed here."
				)
		if row.line_type == LINE_RECEIPT and is_application_task(seq, profile) and row.attachment:
			if not can_attach_receipt:
				frappe.throw(
					f"Only <b>Declarant</b> or <b>Operations</b> can attach <b>{row.line_label}</b>."
				)
			if task.project and not application_payment_made_for_project(task.project, profile):
				frappe.throw(
					f"Finance must record payment before uploading the <b>{profile.receipt_label}</b>."
				)
		if (
			row.line_type == LINE_RECEIPT
			and is_application_finance_task(seq, profile)
			and row.attachment
			and not frappe.flags.get("cgm_syncing_application_receipt")
		):
			prev = task.get_doc_before_save()
			prev_rec = get_receipt_line(prev, profile) if prev else None
			prev_attachment = prev_rec.attachment if prev_rec else None
			if row.attachment != prev_attachment:
				frappe.throw(
					f"Declarant uploads the <b>{profile.receipt_label}</b> on the application task. "
					"Finance verifies it here."
				)


def get_profile_for_sequence(sequence_no: int) -> ApplicationFinanceProfile | None:
	for profile in all_profiles():
		if is_application_workflow_task(sequence_no, profile):
			return profile
	return None


def is_any_application_workflow_task(sequence_no: int) -> bool:
	return get_profile_for_sequence(sequence_no) is not None


def linked_application_finance_pairs() -> tuple[tuple[int, int], ...]:
	pairs: list[tuple[int, int]] = []
	for profile in all_profiles():
		app = get_application_sequence(profile)
		fin = get_application_finance_sequence(profile)
		if app and fin:
			pairs.append((app, fin))
	return tuple(pairs)
