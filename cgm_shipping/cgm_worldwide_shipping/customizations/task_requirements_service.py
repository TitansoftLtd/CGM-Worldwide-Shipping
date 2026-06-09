"""
Strict interpreter for sea task requirements in CGM Shipping Settings.

Settings hold the rules; this module reads and validates them - no runtime fallbacks.
"""
from __future__ import annotations

import frappe

SUPPLIER_INVOICE_CODE = "SUP_INV"
PRE_CLEARANCE_STAGE = "Pre-clearance"

_SETTINGS_REQUIREMENTS_FIELD = "custom_sea_clearance_task_requirements"
_SETTINGS_LINK = "CGM Shipping Settings → Sea clearance task requirements"


def ensure_sea_task_requirements_configured() -> None:
	"""Fail fast when sea task requirements are missing or incomplete."""
	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field(_SETTINGS_REQUIREMENTS_FIELD):
		frappe.throw(
			f"Field <b>{_SETTINGS_REQUIREMENTS_FIELD}</b> is not installed. Run <b>bench migrate</b>."
		)

	settings = frappe.get_single("CGM Shipping Settings")
	rows = settings.get(_SETTINGS_REQUIREMENTS_FIELD) or []
	if not rows:
		frappe.throw(
			f"Configure <b>{_SETTINGS_LINK}</b> before using the sea import workflow."
		)

	grouped = rows_by_sequence()
	if not grouped:
		frappe.throw(
			f"Add at least one row with a sequence number in <b>{_SETTINGS_LINK}</b>."
		)

	for seq in permit_application_sequences():
		_permit_stage_value_for_application(seq)

	for seq in finance_payment_sequences():
		_finance_payment_kind_value(seq)


@frappe.request_cache
def rows_by_sequence() -> dict[int, list]:
	"""Sea task requirement rows grouped by sequence (one Settings read per request)."""
	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field(_SETTINGS_REQUIREMENTS_FIELD):
		return {}
	settings = frappe.get_single("CGM Shipping Settings")
	grouped: dict[int, list] = {}
	for row in settings.get(_SETTINGS_REQUIREMENTS_FIELD) or []:
		seq = int(row.sequence_no or 0)
		if not seq:
			continue
		grouped.setdefault(seq, []).append(row)
	return grouped


def get_required_document_codes(sequence_no: int) -> list[str]:
	rows = rows_by_sequence().get(sequence_no) or []
	return [
		(row.value or "").strip().upper()
		for row in rows
		if row.requirement_type == "Document" and (row.value or "").strip()
	]


def is_permit_application_task(sequence_no: int) -> bool:
	return any(
		r.requirement_type == "Permit Application" for r in rows_by_sequence().get(sequence_no, [])
	)


def is_light_proof_task(sequence_no: int) -> bool:
	return any(r.requirement_type == "Light Proof" for r in rows_by_sequence().get(sequence_no, []))


def is_ucr_application_task(sequence_no: int) -> bool:
	return any(
		r.requirement_type == "UCR Application" for r in rows_by_sequence().get(sequence_no, [])
	)


def is_finance_payment_task(sequence_no: int) -> bool:
	return any(
		r.requirement_type == "Finance Payment" for r in rows_by_sequence().get(sequence_no, [])
	)


def is_auto_complete_task(sequence_no: int) -> bool:
	return any(r.requirement_type == "Auto Complete" for r in rows_by_sequence().get(sequence_no, []))


def _permit_stage_value_for_application(sequence_no: int) -> str:
	for row in rows_by_sequence().get(sequence_no, []):
		if row.requirement_type == "Permit Stage" and (row.value or "").strip():
			return row.value.strip()
	frappe.throw(
		f"Permit Application at sequence <b>{sequence_no}</b> requires a "
		f"<b>Permit Stage</b> row in {_SETTINGS_LINK}."
	)


def get_permit_stage_for_sequence(sequence_no: int) -> str:
	if is_permit_application_task(sequence_no):
		return _permit_stage_value_for_application(sequence_no)
	stages = permit_stage_by_sequence()
	if sequence_no in stages:
		return stages[sequence_no]
	frappe.throw(
		f"No permit stage for sequence <b>{sequence_no}</b>. "
		f"Check permit application/finance pairing in {_SETTINGS_LINK}."
	)


def _normalize_finance_payment_kind(value: str) -> str:
	normalized = value.strip().upper()
	if normalized == "UCR":
		return "UCR"
	if normalized == "PERMIT":
		return "Permit"
	if normalized == "STANDARD":
		return "Standard"
	return value.strip()


def _finance_payment_kind_value(sequence_no: int) -> str:
	for row in rows_by_sequence().get(sequence_no, []):
		if row.requirement_type != "Finance Payment":
			continue
		val = (row.value or "").strip()
		if not val:
			frappe.throw(
				f"Finance Payment at sequence <b>{sequence_no}</b> requires a value "
				f"(UCR, Permit, or Standard) in {_SETTINGS_LINK}."
			)
		return _normalize_finance_payment_kind(val)
	frappe.throw(
		f"Finance Payment at sequence <b>{sequence_no}</b> is missing from {_SETTINGS_LINK}."
	)


def get_finance_payment_kind(sequence_no: int) -> str | None:
	"""UCR, Permit, or Standard finance payment step; None if not a finance task."""
	if not is_finance_payment_task(sequence_no):
		return None
	return _finance_payment_kind_value(sequence_no)


def permit_application_sequences() -> frozenset[int]:
	return frozenset(
		seq
		for seq, rows in rows_by_sequence().items()
		if any(r.requirement_type == "Permit Application" for r in rows)
	)


def ucr_application_sequences() -> frozenset[int]:
	return frozenset(
		seq
		for seq, rows in rows_by_sequence().items()
		if any(r.requirement_type == "UCR Application" for r in rows)
	)


def light_proof_sequences() -> frozenset[int]:
	return frozenset(
		seq
		for seq, rows in rows_by_sequence().items()
		if any(r.requirement_type == "Light Proof" for r in rows)
	)


def finance_payment_sequences() -> frozenset[int]:
	return frozenset(
		seq
		for seq, rows in rows_by_sequence().items()
		if any(r.requirement_type == "Finance Payment" for r in rows)
	)


def auto_complete_sequences() -> frozenset[int]:
	return frozenset(
		seq
		for seq, rows in rows_by_sequence().items()
		if any(r.requirement_type == "Auto Complete" for r in rows)
	)


def is_ucr_finance_payment_task(sequence_no: int) -> bool:
	return get_finance_payment_kind(sequence_no) == "UCR"


def is_permit_finance_payment_task(sequence_no: int) -> bool:
	return get_finance_payment_kind(sequence_no) == "Permit"


def is_ucr_workflow_task(sequence_no: int) -> bool:
	return is_ucr_application_task(sequence_no) or is_ucr_finance_payment_task(sequence_no)


def get_ucr_create_sequence() -> int | None:
	seqs = sorted(ucr_application_sequences())
	return seqs[0] if seqs else None


def get_ucr_payment_sequence() -> int | None:
	seqs = sorted(s for s in finance_payment_sequences() if is_ucr_finance_payment_task(s))
	return seqs[0] if seqs else None


@frappe.request_cache
def permit_finance_by_application_sequence() -> dict[int, int]:
	"""Permit application sequence → paired finance permit sequence (from Settings)."""
	mapping: dict[int, int] = {}
	permit_finance = sorted(
		s for s in finance_payment_sequences() if is_permit_finance_payment_task(s)
	)
	if not permit_finance:
		return mapping
	for app_seq in sorted(permit_application_sequences()):
		if _permit_stage_value_for_application(app_seq) == PRE_CLEARANCE_STAGE:
			mapping[app_seq] = permit_finance[0]
	return mapping


def get_permit_finance_sequence_for_application(application_seq: int) -> int | None:
	return permit_finance_by_application_sequence().get(application_seq)


def get_pre_clearance_permit_application_sequence() -> int | None:
	for seq in sorted(permit_application_sequences()):
		if _permit_stage_value_for_application(seq) == PRE_CLEARANCE_STAGE:
			return seq
	return None


@frappe.request_cache
def permit_stage_by_sequence() -> dict[int, str]:
	"""Permit stage label per sequence (application + finance permit steps)."""
	stages: dict[int, str] = {}
	for seq in permit_application_sequences():
		stages[seq] = _permit_stage_value_for_application(seq)
	for app_seq, fin_seq in permit_finance_by_application_sequence().items():
		stages[fin_seq] = stages[app_seq]
	return stages


@frappe.request_cache
def ucr_linked_task_pairs() -> tuple[tuple[int, int], ...]:
	create = get_ucr_create_sequence()
	payment = get_ucr_payment_sequence()
	if create and payment:
		return ((create, payment),)
	return ()


@frappe.request_cache
def permit_linked_task_pairs() -> tuple[tuple[int, int], ...]:
	return tuple(
		(app, fin) for app, fin in sorted(permit_finance_by_application_sequence().items())
	)


def finance_payment_with_supplier_invoice_sequences() -> frozenset[int]:
	"""Finance steps that require supplier invoice on Task Documents (not UCR/permit payment)."""
	return frozenset(
		seq
		for seq in finance_payment_sequences()
		if get_finance_payment_kind(seq) == "Standard"
	)


def is_sea_finance_payment_task(task) -> bool:
	"""Task is a sea import finance payment step (settings-driven)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SEA_TASK_FLOW_KEY

	return (
		task.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY
		and is_finance_payment_task(int(task.get("custom_sequence_no") or 0))
	)


def is_sea_auto_complete_task(task) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SEA_TASK_FLOW_KEY

	return (
		task.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY
		and is_auto_complete_task(int(task.get("custom_sequence_no") or 0))
	)


@frappe.whitelist()
def get_sea_task_ui_sequences() -> dict:
	"""Sequence lists and role flags for Task form UI (from CGM Shipping Settings)."""
	ensure_sea_task_requirements_configured()

	from cgm_shipping.cgm_worldwide_shipping.customizations.notifications_service import (
		get_task_form_permissions,
	)

	permit_finance = sorted(s for s in finance_payment_sequences() if is_permit_finance_payment_task(s))
	ucr_finance = sorted(s for s in finance_payment_sequences() if is_ucr_finance_payment_task(s))
	stage_by_seq = permit_stage_by_sequence()
	return {
		"payment_seqs": sorted(finance_payment_sequences()),
		"auto_complete_seqs": sorted(auto_complete_sequences()),
		"permit_application_seqs": sorted(permit_application_sequences()),
		"light_proof_seqs": sorted(light_proof_sequences()),
		"ucr_application_seqs": sorted(ucr_application_sequences()),
		"finance_document_seqs": sorted(finance_payment_with_supplier_invoice_sequences()),
		"permit_finance_seqs": permit_finance,
		"ucr_finance_seqs": ucr_finance,
		"permit_stage_by_seq": {str(k): v for k, v in stage_by_seq.items()},
		"permissions": get_task_form_permissions(),
	}
