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
	IDF_CERTIFICATE_CODES,
	SHIPPING_LINE_INVOICE_TO_FINANCE,
	SHIPPING_LINE_RECEIPT_FOR_DECLARANT,
	SHIPPING_LINE_RECEIPT_VERIFY_FINANCE,
	KPA_INVOICE_TO_FINANCE,
	KPA_RECEIPT_FOR_SUPERVISOR,
	KPA_RECEIPT_VERIFY_FINANCE,
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
LINE_POP = "POP"
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
	# Shipping Line: POP (proof of payment) between pay and Documentation receipt.
	requires_pop: bool = False
	pop_label: str = ""
	# Create Entry: complete when Finance verifies the invoice (ENTRY doc optional).
	complete_on_invoice_verified: bool = False
	# After company payment, Finance must attach + verify the receipt before complete.
	# Only Entry Slip keeps the receipt optional (set requires_receipt_verification=False).
	requires_receipt_verification: bool = True


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
		legacy_certificate_codes=IDF_CERTIFICATE_CODES,
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
		complete_on_invoice_verified=True,
		requires_receipt_verification=False,
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
		requires_pop=True,
		pop_label="Shipping Line POP",
	),
	"KPA Application": ApplicationFinanceProfile(
		key="kpa",
		application_requirement_type="KPA Application",
		finance_payment_kind="KPA",
		payment_item="KPA",
		invoice_label="KPA Invoice",
		receipt_label="KPA Receipt",
		certificate_document_code="",
		gate_rule="KPA Finance Complete",
		notification_invoice=KPA_INVOICE_TO_FINANCE,
		notification_receipt_declarant=KPA_RECEIPT_FOR_SUPERVISOR,
		notification_receipt_verify=KPA_RECEIPT_VERIFY_FINANCE,
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
	"""First matching line (primary Invoice / POP / Receipt — not amendment invoices)."""
	if not task:
		return None
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if row.line_type != line_type:
			continue
		if (row.payment_item or profile.payment_item) != profile.payment_item:
			continue
		# Prefer the original (non-amendment) invoice when looking up "the" invoice line.
		if line_type == LINE_INVOICE and cint(row.get("is_amendment")):
			continue
		return row
	# Fallback: any matching invoice (legacy single-row or only amendments present).
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if row.line_type == line_type and (row.payment_item or profile.payment_item) == profile.payment_item:
			return row
	return None


def get_invoice_lines(task, profile: ApplicationFinanceProfile) -> list:
	"""All Invoice rows for this profile (primary + amendments), in table order."""
	if not task:
		return []
	return [
		row
		for row in (task.get(TASK_FINANCE_FIELD) or [])
		if row.line_type == LINE_INVOICE
		and (row.payment_item or profile.payment_item) == profile.payment_item
	]


def invoice_line_is_settled(row, task=None) -> bool:
	"""True when this Invoice line has company JE or client-pays settlement."""
	if not row or not row.get("attachment"):
		return False
	if not cint(row.get("verified")):
		# Task-level verified flag may still cover the primary line.
		return False
	if row.get("journal_entry") and frappe.db.exists("Journal Entry", row.journal_entry):
		return True
	if cint(row.get("client_paid_directly")) or cint(row.get("client_reported_paid")):
		return True
	# Legacy: primary (non-amendment) line settled via task-level JE / client-paid.
	if task and not cint(row.get("is_amendment")):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			task_client_paid_directly,
		)

		task_je = task.get("custom_journal_entry")
		if task_je and frappe.db.exists("Journal Entry", task_je):
			# Do not treat an amendment's JE (also stored on the task) as primary settlement.
			on_other_line = any(
				(r.get("journal_entry") or "") == task_je
				and cint(r.get("is_amendment"))
				for r in (task.get(TASK_FINANCE_FIELD) or [])
				if (r.line_type or LINE_INVOICE) == LINE_INVOICE
			)
			if not on_other_line:
				return True
		if task_client_paid_directly(task):
			return True
	return False


def finance_has_client_paid_invoice_line(task, profile: ApplicationFinanceProfile) -> bool:
	"""True when any attached Invoice row is marked Client will pay."""
	return any(
		cint(r.get("client_paid_directly"))
		for r in get_invoice_lines(task, profile)
		if r.get("attachment")
	)


def _finance_line_client_paid_changed(task, row) -> bool:
	"""True when Client will pay was toggled on this Invoice row."""
	prev = task.get_doc_before_save()
	if not prev:
		return bool(cint(row.get("client_paid_directly")))
	prev_row = None
	if row.name:
		prev_row = next(
			(
				r
				for r in (prev.get(TASK_FINANCE_FIELD) or [])
				if r.name == row.name
			),
			None,
		)
	if not prev_row:
		# Match by amendment + label when the row is new this save.
		for r in prev.get(TASK_FINANCE_FIELD) or []:
			if (r.line_type or LINE_INVOICE) != LINE_INVOICE:
				continue
			if cint(r.get("is_amendment")) != cint(row.get("is_amendment")):
				continue
			if (r.get("line_label") or "") == (row.get("line_label") or ""):
				prev_row = r
				break
	if not prev_row:
		return bool(cint(row.get("client_paid_directly")))
	return cint(row.get("client_paid_directly")) != cint(prev_row.get("client_paid_directly"))


def _journal_entries_linked_to_finance_task(task_name: str) -> list[str]:
	"""Existing JEs created from this finance task (oldest first). Does not alter JEs."""
	names: list[str] = []
	seen: set[str] = set()

	def _add(name: str | None):
		name = (name or "").strip()
		if not name or name in seen:
			return
		if not frappe.db.exists("Journal Entry", name):
			return
		seen.add(name)
		names.append(name)

	# Prefer source-task link (covers primary + amendment payments in creation order).
	if frappe.get_meta("Journal Entry").has_field("custom_cgm_source_task"):
		for row in frappe.get_all(
			"Journal Entry",
			filters={"custom_cgm_source_task": task_name, "docstatus": ("<", 2)},
			fields=["name"],
			order_by="creation asc",
		):
			_add(row.name)

	# Tasks that only stored JE on custom_journal_entry (no source-task stamp).
	task_je = frappe.db.get_value("Task", task_name, "custom_journal_entry")
	_add(task_je)
	return names


def backfill_legacy_payment_onto_invoice_lines(
	task, profile: ApplicationFinanceProfile
) -> bool:
	"""Move existing task-level / source-task JEs onto Invoice finance lines.

	Does not create, cancel, or edit Journal Entry documents — only fills empty
	``journal_entry`` / ``client_paid_directly`` on Task Finance Line rows.

	Assignment order: primary invoice first, then amendments by idx. Oldest
	linked JE goes to the first unsettled line so a later amendment payment does
	not steal the primary row's JE.
	"""
	if not task_has_finance_table(task) or not task.name:
		return False
	if not is_application_finance_task(int(task.get("custom_sequence_no") or 0), profile):
		return False

	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CLIENT_PAID_FIELD,
	)

	changed = False
	lines = [
		r
		for r in get_invoice_lines(task, profile)
		if r.get("attachment") and r.name
	]
	if not lines:
		return False

	# Primary first, then amendments in table order.
	lines.sort(key=lambda r: (cint(r.get("is_amendment")), cint(r.get("idx") or 0)))

	used_jes: set[str] = {
		(r.get("journal_entry") or "").strip()
		for r in lines
		if (r.get("journal_entry") or "").strip()
	}
	candidates = [
		je for je in _journal_entries_linked_to_finance_task(task.name) if je not in used_jes
	]

	for row in lines:
		if (row.get("journal_entry") or "").strip():
			continue
		if cint(row.get("client_paid_directly")) or cint(row.get("client_reported_paid")):
			continue
		if not candidates:
			break
		je = candidates.pop(0)
		frappe.db.set_value(
			"Task Finance Line",
			row.name,
			"journal_entry",
			je,
			update_modified=False,
		)
		row.journal_entry = je
		used_jes.add(je)
		changed = True

	# Task-level Client will pay → primary line only when no line already has it.
	primary = next((r for r in lines if not cint(r.get("is_amendment"))), None)
	if (
		primary
		and primary.name
		and cint(task.get(CLIENT_PAID_FIELD))
		and not cint(primary.get("client_paid_directly"))
		and not any(cint(r.get("client_paid_directly")) for r in lines)
		and not (primary.get("journal_entry") or "").strip()
	):
		frappe.db.set_value(
			"Task Finance Line",
			primary.name,
			"client_paid_directly",
			1,
			update_modified=False,
		)
		primary.client_paid_directly = 1
		changed = True

	if changed:
		frappe.clear_document_cache("Task", task.name)
	return changed


def sync_finance_line_payments_to_application_task(
	finance_task, profile: ApplicationFinanceProfile
) -> bool:
	"""Copy line JE / client-pays from Finance onto matching Create/Application rows."""
	if not finance_task.project:
		return False
	app_name = get_application_task(finance_task.project, profile)
	if not app_name:
		return False
	app = frappe.get_doc("Task", app_name)
	if not task_has_finance_table(app):
		return False

	fin_lines = list(get_invoice_lines(finance_task, profile))
	app_lines = list(get_invoice_lines(app, profile))
	used: set[int] = set()
	changed = False
	for fin in fin_lines:
		if not fin.get("attachment"):
			continue
		if not (fin.get("journal_entry") or cint(fin.get("client_paid_directly"))):
			continue
		idx, app_line = _match_finance_invoice_line(app_lines, fin, used)
		if app_line is None or not app_line.name:
			continue
		used.add(idx)
		updates = {}
		if fin.get("journal_entry") and app_line.get("journal_entry") != fin.journal_entry:
			updates["journal_entry"] = fin.journal_entry
		if cint(fin.get("client_paid_directly")) and not cint(app_line.get("client_paid_directly")):
			updates["client_paid_directly"] = 1
		if updates:
			frappe.db.set_value(
				"Task Finance Line", app_line.name, updates, update_modified=False
			)
			changed = True
	if changed:
		frappe.clear_document_cache("Task", app_name)
	return changed


def sync_invoice_line_client_paid_to_task_field(
	task, profile: ApplicationFinanceProfile
) -> None:
	"""Keep hidden task-level Client will pay in sync for legacy application mirrors.

	Set when every attached invoice is client-pays, or the sole primary invoice is.
	Clear when mixed (company JE on one line, client-pays on another).
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CLIENT_PAID_BY_FIELD,
		CLIENT_PAID_FIELD,
		CLIENT_PAID_ON_FIELD,
	)

	if not task.meta.has_field(CLIENT_PAID_FIELD):
		return
	if not is_application_finance_task(int(task.get("custom_sequence_no") or 0), profile):
		return

	lines = [r for r in get_invoice_lines(task, profile) if r.get("attachment")]
	if not lines:
		return
	all_client = all(cint(r.get("client_paid_directly")) for r in lines)
	sole_primary = (
		len(lines) == 1
		and not cint(lines[0].get("is_amendment"))
		and cint(lines[0].get("client_paid_directly"))
	)
	want = 1 if (all_client or sole_primary) else 0
	have = 1 if task.get(CLIENT_PAID_FIELD) else 0
	if want == have:
		return
	task.set(CLIENT_PAID_FIELD, want)
	if want:
		if task.meta.has_field(CLIENT_PAID_BY_FIELD) and not task.get(CLIENT_PAID_BY_FIELD):
			task.set(CLIENT_PAID_BY_FIELD, frappe.session.user)
		if task.meta.has_field(CLIENT_PAID_ON_FIELD) and not task.get(CLIENT_PAID_ON_FIELD):
			task.set(CLIENT_PAID_ON_FIELD, now_datetime())
	else:
		for field in (CLIENT_PAID_BY_FIELD, CLIENT_PAID_ON_FIELD):
			if task.meta.has_field(field):
				task.set(field, None)


def unpaid_invoice_lines(task, profile: ApplicationFinanceProfile) -> list:
	return [r for r in get_invoice_lines(task, profile) if r.get("attachment") and not invoice_line_is_settled(r, task)]


def all_invoice_lines_settled(task, profile: ApplicationFinanceProfile) -> bool:
	rows = [r for r in get_invoice_lines(task, profile) if r.get("attachment")]
	if not rows:
		return False
	return all(invoice_line_is_settled(r, task) for r in rows)


def all_invoice_lines_verified(task, profile: ApplicationFinanceProfile) -> bool:
	rows = [r for r in get_invoice_lines(task, profile) if r.get("attachment")]
	if not rows:
		return False
	ok = all(cint(r.get("verified")) for r in rows)
	if ok:
		return True
	# Legacy primary-only verified field on task.
	if len(rows) == 1 and profile.application_invoice_verified_field:
		return bool(task.get(profile.application_invoice_verified_field))
	return False


def get_invoice_line(task, profile: ApplicationFinanceProfile):
	return _find_line(task, LINE_INVOICE, profile)


def get_pop_line(task, profile: ApplicationFinanceProfile):
	return _find_line(task, LINE_POP, profile)


def get_receipt_line(task, profile: ApplicationFinanceProfile):
	return _find_line(task, LINE_RECEIPT, profile)


def invoice_attached(task, profile: ApplicationFinanceProfile) -> bool:
	line = get_invoice_line(task, profile)
	return bool(line and line.attachment)


def pop_attached(task, profile: ApplicationFinanceProfile) -> bool:
	if not profile.requires_pop:
		return True
	line = get_pop_line(task, profile)
	return bool(line and line.attachment)


def receipt_attached(task, profile: ApplicationFinanceProfile) -> bool:
	line = get_receipt_line(task, profile)
	return bool(line and line.attachment)


def invoice_verified(task, profile: ApplicationFinanceProfile) -> bool:
	return all_invoice_lines_verified(task, profile)


def receipt_verified(task, profile: ApplicationFinanceProfile) -> bool:
	line = get_receipt_line(task, profile)
	return bool(line and line.verified)


def _ensure_line(task, line_type: str, profile: ApplicationFinanceProfile):
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_purchase_item_for_payment_item,
		task_finance_line_has_item_code,
	)

	if line_type == LINE_INVOICE:
		label = profile.invoice_label
	elif line_type == LINE_POP:
		label = profile.pop_label or "POP"
	else:
		label = profile.receipt_label
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
	if profile.requires_pop:
		_ensure_line(task, LINE_POP, profile)
	_ensure_line(task, LINE_RECEIPT, profile)
	reorder_application_finance_lines(task, profile)
	if is_application_finance_task(seq, profile):
		copy_application_invoice_to_finance_task(task, profile)


def _finance_line_sort_key(line_type: str, profile: ApplicationFinanceProfile) -> int:
	"""Invoice → POP → Receipt so Shipping Line POP sits in the middle."""
	order = {LINE_INVOICE: 1}
	if profile.requires_pop:
		order[LINE_POP] = 2
		order[LINE_RECEIPT] = 3
	else:
		order[LINE_RECEIPT] = 2
	return order.get(line_type or "", 99)


def reorder_application_finance_lines(task, profile: ApplicationFinanceProfile) -> bool:
	"""Keep profile finance lines in Invoice / POP / Receipt order (in memory)."""
	all_rows = task.get(TASK_FINANCE_FIELD) or []
	rows = [
		r
		for r in all_rows
		if (r.payment_item or profile.payment_item) == profile.payment_item
	]
	other = [
		r
		for r in all_rows
		if (r.payment_item or profile.payment_item) != profile.payment_item
	]
	if len(rows) < 2 and not other:
		return False
	desired = sorted(
		rows,
		key=lambda r: (_finance_line_sort_key(r.line_type, profile), cint(r.idx or 0)),
	)
	changed = False
	for idx, row in enumerate(desired, start=1):
		if cint(row.idx) != idx:
			row.idx = idx
			changed = True
	next_idx = len(desired) + 1
	for row in other:
		if cint(row.idx) != next_idx:
			row.idx = next_idx
			changed = True
		next_idx += 1

	ordered = desired + other
	before_ids = [r.name or id(r) for r in all_rows]
	after_ids = [r.name or id(r) for r in ordered]
	if before_ids != after_ids:
		all_rows[:] = ordered
		changed = True
	return changed


def _finance_lines_snapshot(task, profile: ApplicationFinanceProfile) -> tuple:
	"""Detect row add/remove, order, and invoice Purchase Item / attachment drift."""
	rows = []
	for r in task.get(TASK_FINANCE_FIELD) or []:
		rows.append(
			(
				cint(r.idx or 0),
				r.line_type,
				r.payment_item or profile.payment_item,
				(r.get("item_code") or "").strip(),
				r.attachment or "",
			)
		)
	return tuple(rows)


def ensure_application_finance_lines_saved(task, profile: ApplicationFinanceProfile) -> bool:
	"""Ensure Invoice / POP / Receipt rows exist without bumping Task.modified.

	Full ``task.save()`` on form open races with Desk (TimestampMismatchError).
	Missing child rows are inserted directly; label/item_code/idx fixes use db.set_value.
	"""
	if not task_has_finance_table(task):
		return False
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_application_workflow_task(seq, profile):
		return False

	before = _finance_lines_snapshot(task, profile)
	seed_application_finance_lines(task, profile)
	after = _finance_lines_snapshot(task, profile)
	if after == before:
		return False

	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_purchase_item_for_payment_item,
		task_finance_line_has_item_code,
	)

	frappe.flags.cgm_ensuring_application_finance_lines = True
	try:
		changed = False
		for row in task.get(TASK_FINANCE_FIELD) or []:
			if (row.payment_item or profile.payment_item) != profile.payment_item:
				continue
			if not row.get("name"):
				# New unsaved child from seed — insert without parent.save().
				payload = {
					"doctype": "Task Finance Line",
					"parent": task.name,
					"parenttype": "Task",
					"parentfield": TASK_FINANCE_FIELD,
					"line_label": row.line_label,
					"line_type": row.line_type,
					"payment_item": row.payment_item or profile.payment_item,
					"idx": cint(row.idx) or 0,
				}
				if row.line_type == LINE_INVOICE and task_finance_line_has_item_code():
					payload["item_code"] = row.get("item_code") or get_purchase_item_for_payment_item(
						profile.payment_item, task.company
					)
				if row.get("attachment"):
					payload["attachment"] = row.attachment
				child = frappe.get_doc(payload)
				child.insert(ignore_permissions=True)
				row.name = child.name
				changed = True
				continue

			updates = {}
			if not row.line_label:
				if row.line_type == LINE_INVOICE:
					updates["line_label"] = profile.invoice_label
				elif row.line_type == LINE_POP:
					updates["line_label"] = profile.pop_label or "POP"
				else:
					updates["line_label"] = profile.receipt_label
			if (
				row.line_type == LINE_INVOICE
				and task_finance_line_has_item_code()
				and not row.get("item_code")
			):
				updates["item_code"] = get_purchase_item_for_payment_item(
					profile.payment_item, task.company
				)
			db_idx = frappe.db.get_value("Task Finance Line", row.name, "idx")
			if cint(row.idx) and cint(row.idx) != cint(db_idx):
				updates["idx"] = cint(row.idx)
			if updates:
				frappe.db.set_value(
					"Task Finance Line", row.name, updates, update_modified=False
				)
				changed = True

		if is_application_finance_task(seq, profile):
			# Invoice attachment copy may have been applied in-memory only.
			fin_line = get_invoice_line(task, profile)
			if fin_line and fin_line.name and fin_line.get("attachment"):
				db_att = frappe.db.get_value("Task Finance Line", fin_line.name, "attachment")
				if fin_line.attachment != db_att:
					frappe.db.set_value(
						"Task Finance Line",
						fin_line.name,
						{"attachment": fin_line.attachment},
						update_modified=False,
					)
					changed = True
				if task_finance_line_has_item_code() and fin_line.get("item_code"):
					db_item = frappe.db.get_value("Task Finance Line", fin_line.name, "item_code")
					if fin_line.item_code != db_item:
						frappe.db.set_value(
							"Task Finance Line",
							fin_line.name,
							{"item_code": fin_line.item_code},
							update_modified=False,
						)
						changed = True

		if changed:
			frappe.clear_document_cache("Task", task.name)
			frappe.publish_realtime(
				"cgm_task_status_changed",
				{"task": task.name, "project": task.project, "soft_sync": 1},
			)
		return changed
	finally:
		frappe.flags.cgm_ensuring_application_finance_lines = False


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
	app_lines = get_invoice_lines(app, profile)
	if not app_lines:
		return
	fin_lines = list(get_invoice_lines(finance_task, profile))
	used: set[int] = set()
	for app_line in app_lines:
		if not app_line.get("attachment") and not cint(app_line.get("is_amendment")):
			# Still ensure primary row exists.
			fin_line = _ensure_line(finance_task, LINE_INVOICE, profile)
			_sync_purchase_item_from_application_line(
				fin_line, app_line, finance_task, profile.payment_item
			)
			continue
		idx, fin_line = _match_finance_invoice_line(fin_lines, app_line, used)
		if fin_line is None:
			payload = {
				"line_label": app_line.get("line_label") or profile.invoice_label,
				"line_type": LINE_INVOICE,
				"payment_item": profile.payment_item,
				"is_amendment": cint(app_line.get("is_amendment")),
				"attachment": app_line.get("attachment"),
				"verified": 0,
			}
			if app_line.get("item_code"):
				payload["item_code"] = app_line.item_code
			finance_task.append(TASK_FINANCE_FIELD, payload)
			fin_lines = list(get_invoice_lines(finance_task, profile))
			continue
		used.add(idx)
		if app_line.attachment and not fin_line.attachment:
			fin_line.attachment = app_line.attachment
		if not fin_line.get("journal_entry"):
			_sync_purchase_item_from_application_line(
				fin_line, app_line, finance_task, profile.payment_item
			)


def _match_finance_invoice_line(fin_lines: list, app_line, used: set[int]):
	"""Match application → finance Invoice rows (primary + amendments)."""
	is_amend = cint(app_line.get("is_amendment"))
	attachment = _normalize_attach((app_line.get("attachment") or "").strip())
	label = (app_line.get("line_label") or "").strip()

	if attachment:
		for i, fin in enumerate(fin_lines):
			if i in used:
				continue
			if cint(fin.get("is_amendment")) != is_amend:
				continue
			if _normalize_attach(fin.get("attachment") or "") == attachment:
				return i, fin

	if not is_amend:
		for i, fin in enumerate(fin_lines):
			if i in used:
				continue
			if not cint(fin.get("is_amendment")):
				return i, fin
		return None, None

	# Amendment: same label, or empty attachment slot.
	for i, fin in enumerate(fin_lines):
		if i in used or not cint(fin.get("is_amendment")):
			continue
		if label and (fin.get("line_label") or "").strip() == label:
			return i, fin
	for i, fin in enumerate(fin_lines):
		if i in used or not cint(fin.get("is_amendment")):
			continue
		if not (fin.get("attachment") or "").strip():
			return i, fin
	return None, None


def _normalize_attach(path: str) -> str:
	path = (path or "").strip()
	if not path:
		return ""
	for prefix in ("/private/files/", "/files/"):
		if prefix in path:
			return path.split(prefix, 1)[-1].split("?", 1)[0]
	return path.rsplit("/", 1)[-1].split("?", 1)[0]


def _sync_purchase_item_from_application_line(
	fin_line, app_line, finance_task, payment_item: str
) -> bool:
	"""Keep finance Purchase Item aligned with the application task.

	Returns True when fin_line.item_code changed. Stops once this line has a
	Journal Entry so a posted payment is not silently retargeted.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_purchase_item_for_payment_item,
		task_finance_line_has_item_code,
	)

	if not task_finance_line_has_item_code():
		return False
	if fin_line.get("journal_entry"):
		return False
	# Legacy primary: task-level JE means the first invoice was already paid.
	if (
		not cint(fin_line.get("is_amendment"))
		and finance_task.get("custom_journal_entry")
		and frappe.db.exists("Journal Entry", finance_task.custom_journal_entry)
	):
		return False

	app_item = (app_line.get("item_code") or "").strip()
	fin_item = (fin_line.get("item_code") or "").strip()
	if app_item:
		if fin_item == app_item:
			return False
		fin_line.item_code = app_item
		return True
	if fin_item:
		return False
	fin_line.item_code = get_purchase_item_for_payment_item(
		payment_item, finance_task.company
	)
	return bool(fin_line.item_code)


def sync_application_purchase_item_to_finance(
	application_task, profile: ApplicationFinanceProfile
) -> bool:
	"""Push Purchase Item (and missing invoice fields) from Create/Attach task → Finance."""
	if not is_application_task(int(application_task.get("custom_sequence_no") or 0), profile):
		return False
	if not application_task.project:
		return False
	app_line = get_invoice_line(application_task, profile)
	if not app_line:
		return False
	finance_name = get_application_finance_task(application_task.project, profile)
	if not finance_name:
		return False
	finance_task = frappe.get_doc("Task", finance_name)
	if finance_task.status == "Completed":
		return False
	fin_line = _ensure_line(finance_task, LINE_INVOICE, profile)
	changed = False
	if app_line.attachment and fin_line.attachment != app_line.attachment and not fin_line.verified:
		fin_line.attachment = app_line.attachment
		changed = True
	if _sync_purchase_item_from_application_line(
		fin_line, app_line, finance_task, profile.payment_item
	):
		changed = True
	if not changed:
		return False
	if fin_line.name:
		updates = {"item_code": fin_line.item_code}
		if fin_line.attachment:
			updates["attachment"] = fin_line.attachment
		frappe.db.set_value("Task Finance Line", fin_line.name, updates, update_modified=False)
		frappe.clear_document_cache("Task", finance_name)
	else:
		finance_task.flags.ignore_links = True
		try:
			from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
				preserve_completed_status_against_stale_save,
			)

			preserve_completed_status_against_stale_save(finance_task)
			finance_task.save(ignore_permissions=True)
		finally:
			finance_task.flags.ignore_links = False
	frappe.publish_realtime(
		"cgm_task_status_changed",
		{"task": finance_name, "project": application_task.project},
	)
	return True


def copy_application_receipt_to_finance_task(
	application_task, profile: ApplicationFinanceProfile
) -> str | None:
	"""Copy legacy application-task receipt onto finance (open projects / old handoff)."""
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
	# Do not overwrite a receipt Finance already uploaded on the finance task.
	if fin_rec.attachment:
		return finance_name
	updates = {"attachment": app_rec.attachment}
	frappe.db.set_value("Task Finance Line", fin_rec.name, updates, update_modified=False)
	return finance_name


def copy_finance_receipt_to_application_task(
	finance_task, profile: ApplicationFinanceProfile
) -> str | None:
	"""Mirror Finance-uploaded receipt onto the application task so Declarant can view it."""
	if not is_application_finance_task(int(finance_task.get("custom_sequence_no") or 0), profile):
		return None
	if not finance_task.project:
		return None
	fin_rec = get_receipt_line(finance_task, profile)
	if not fin_rec or not fin_rec.attachment:
		return None
	app_name = get_application_task(finance_task.project, profile)
	if not app_name:
		return None
	app = frappe.get_doc("Task", app_name)
	seed_application_finance_lines(app, profile)
	ensure_application_finance_lines_saved(app, profile)
	app.reload()
	app_rec = get_receipt_line(app, profile)
	if not app_rec:
		return None
	if not app_rec.name:
		frappe.flags.cgm_syncing_application_receipt = True
		try:
			app.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_application_receipt = False
		app_rec = get_receipt_line(frappe.get_doc("Task", app_name), profile)
		if not app_rec:
			return None

	updates = {"attachment": fin_rec.attachment}
	# Mirror verification when Finance marks / auto-stamps the receipt.
	if cint(fin_rec.verified):
		updates["verified"] = 1
		if fin_rec.verified_by:
			updates["verified_by"] = fin_rec.verified_by
		if fin_rec.verified_on:
			updates["verified_on"] = fin_rec.verified_on
	needs_update = any(app_rec.get(k) != v for k, v in updates.items())
	if not needs_update:
		return None
	frappe.db.set_value("Task Finance Line", app_rec.name, updates, update_modified=False)
	if (
		profile.application_receipt_verified_field
		and cint(fin_rec.verified)
		and frappe.get_meta("Task").has_field(profile.application_receipt_verified_field)
	):
		frappe.db.set_value(
			"Task",
			app_name,
			profile.application_receipt_verified_field,
			1,
			update_modified=False,
		)
	frappe.clear_document_cache("Task", app_name)
	frappe.publish_realtime(
		"cgm_task_status_changed",
		{
			"task": app_name,
			"project": finance_task.project,
			"receipt_synced": 1,
			"soft_sync": 1,
		},
	)
	return app_name


def copy_finance_pop_to_application_task(
	finance_task, profile: ApplicationFinanceProfile
) -> str | None:
	"""Mirror Finance/client POP onto the Documentation application task (read-only there)."""
	if not profile.requires_pop:
		return None
	if not is_application_finance_task(int(finance_task.get("custom_sequence_no") or 0), profile):
		return None
	if not finance_task.project:
		return None
	fin_pop = get_pop_line(finance_task, profile)
	if not fin_pop or not fin_pop.attachment:
		return None
	app_name = get_application_task(finance_task.project, profile)
	if not app_name:
		return None
	# Cheap gate — avoid seed/ensure/soft_sync when already mirrored.
	existing = frappe.db.get_value(
		"Task Finance Line",
		{
			"parent": app_name,
			"parenttype": "Task",
			"line_type": LINE_POP,
			"payment_item": profile.payment_item,
		},
		["name", "attachment"],
		as_dict=True,
	)
	if existing and existing.attachment == fin_pop.attachment:
		return None
	app = frappe.get_doc("Task", app_name)
	seed_application_finance_lines(app, profile)
	ensure_application_finance_lines_saved(app, profile)
	app.reload()
	app_pop = get_pop_line(app, profile)
	if not app_pop or not app_pop.name:
		return None
	if app_pop.attachment == fin_pop.attachment:
		return None
	frappe.db.set_value(
		"Task Finance Line",
		app_pop.name,
		{"attachment": fin_pop.attachment},
		update_modified=False,
	)
	frappe.clear_document_cache("Task", app_name)
	frappe.publish_realtime(
		"cgm_task_status_changed",
		{
			"task": app_name,
			"project": finance_task.project,
			"pop_synced": 1,
			"soft_sync": 1,
		},
	)
	return app_name


def ensure_finance_pop_visible_on_application_task(
	application_task, profile: ApplicationFinanceProfile
) -> bool:
	"""On application open: pull Finance POP so Documentation can see it.

	Returns True only when the application task was actually updated.
	"""
	if not profile.requires_pop:
		return False
	if not is_application_task(int(application_task.get("custom_sequence_no") or 0), profile):
		return False
	if not application_task.project:
		return False
	if pop_attached(application_task, profile):
		return False
	finance_name = get_application_finance_task(application_task.project, profile)
	if not finance_name:
		return False
	finance_task = frappe.get_doc("Task", finance_name)
	if not pop_attached(finance_task, profile):
		return False
	return bool(copy_finance_pop_to_application_task(finance_task, profile))


def ensure_finance_receipt_visible_on_application_task(
	application_task, profile: ApplicationFinanceProfile
) -> bool:
	"""On application open: pull Finance receipt if Declarant does not have it yet.

	Returns True only when the application task was actually updated.
	"""
	if not is_application_task(int(application_task.get("custom_sequence_no") or 0), profile):
		return False
	if not application_task.project:
		return False
	if receipt_attached(application_task, profile):
		return False
	finance_name = get_application_finance_task(application_task.project, profile)
	if not finance_name:
		return False
	finance_task = frappe.get_doc("Task", finance_name)
	if not receipt_attached(finance_task, profile):
		return False
	return bool(copy_finance_receipt_to_application_task(finance_task, profile))


def ensure_application_receipt_on_finance_task(
	finance_task, profile: ApplicationFinanceProfile
) -> bool:
	"""Ensure finance has a receipt: prefer local, else copy from application task."""
	seq = int(finance_task.get("custom_sequence_no") or 0)
	if not is_application_finance_task(seq, profile):
		return False
	if receipt_attached(finance_task, profile):
		return True
	if not finance_task.project:
		return False
	app_name = get_application_task(finance_task.project, profile)
	if not app_name:
		return False
	# Shipping Line: Documentation may attach receipt on the application task after POP.
	if not copy_application_receipt_to_finance_task(
		frappe.get_doc("Task", app_name), profile
	):
		return False
	finance_task.reload()
	return receipt_attached(finance_task, profile)


def application_payment_made_for_project(
	project: str, profile: ApplicationFinanceProfile
) -> bool:
	"""True when the paired finance task has a Journal Entry or submitted Payment Entry."""
	if not project:
		return False
	finance_name = get_application_finance_task(project, profile)
	if not finance_name:
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import task_has_recorded_payment

	return task_has_recorded_payment(frappe.get_doc("Task", finance_name))


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
	"""Mirror every verified Invoice line (primary + amendments) onto Create/Application.

	Uses db.set_value / child.insert only — never Task.save() — to avoid on_update
	loops (application ↔ finance sync).
	"""
	if frappe.flags.get("cgm_syncing_invoice_verification"):
		return False
	if (
		not is_application_finance_task(int(finance_task.get("custom_sequence_no") or 0), profile)
		or not finance_task.project
		or not task_has_finance_table(finance_task)
	):
		return False
	app_name = get_application_task(finance_task.project, profile)
	if not app_name:
		return False

	frappe.flags.cgm_syncing_invoice_verification = True
	try:
		seed_application_finance_lines(finance_task, profile)
		fin_lines = [
			r
			for r in get_invoice_lines(finance_task, profile)
			if r.get("attachment") and cint(r.get("verified"))
		]
		if not fin_lines:
			return False

		app = frappe.get_doc("Task", app_name)
		if not task_has_finance_table(app):
			return False
		# Persist any seed rows without parent.save().
		ensure_application_finance_lines_saved(app, profile)
		app.reload()
		app_lines = list(get_invoice_lines(app, profile))
		used: set[int] = set()
		changed = False

		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			task_finance_line_has_item_code,
		)

		for fin_line in fin_lines:
			idx, app_line = _match_finance_invoice_line(app_lines, fin_line, used)
			if app_line is None:
				payload = {
					"doctype": "Task Finance Line",
					"parent": app_name,
					"parenttype": "Task",
					"parentfield": TASK_FINANCE_FIELD,
					"line_label": fin_line.get("line_label") or profile.invoice_label,
					"line_type": LINE_INVOICE,
					"payment_item": profile.payment_item,
					"is_amendment": cint(fin_line.get("is_amendment")),
					"attachment": fin_line.get("attachment"),
					"verified": 1,
					"verified_by": fin_line.get("verified_by"),
					"verified_on": fin_line.get("verified_on"),
					"idx": len(app.get(TASK_FINANCE_FIELD) or []) + 1,
				}
				if fin_line.get("journal_entry"):
					payload["journal_entry"] = fin_line.journal_entry
				if task_finance_line_has_item_code() and fin_line.get("item_code"):
					payload["item_code"] = fin_line.item_code
				child = frappe.get_doc(payload)
				child.insert(ignore_permissions=True)
				app.append(TASK_FINANCE_FIELD, child.as_dict())
				app_lines = list(get_invoice_lines(app, profile))
				used.add(len(app_lines) - 1)
				changed = True
				continue

			used.add(idx)
			updates = {}
			if not cint(app_line.get("verified")):
				updates["verified"] = 1
				updates["verified_by"] = fin_line.get("verified_by")
				updates["verified_on"] = fin_line.get("verified_on")
			if fin_line.get("attachment") and app_line.get("attachment") != fin_line.attachment:
				updates["attachment"] = fin_line.attachment
			if fin_line.get("journal_entry") and app_line.get("journal_entry") != fin_line.journal_entry:
				updates["journal_entry"] = fin_line.journal_entry
			if fin_line.get("line_label") and app_line.get("line_label") != fin_line.line_label:
				updates["line_label"] = fin_line.line_label
			if cint(fin_line.get("is_amendment")) and not cint(app_line.get("is_amendment")):
				updates["is_amendment"] = 1
			if updates and app_line.name:
				frappe.db.set_value(
					"Task Finance Line", app_line.name, updates, update_modified=False
				)
				for key, value in updates.items():
					app_line.set(key, value)
				changed = True

		# Task-level verified flag only when every attached invoice is verified.
		app_field = profile.application_invoice_verified_field
		if app_field and app.meta.has_field(app_field):
			app.reload()
			if all_invoice_lines_verified(app, profile) and not app.get(app_field):
				frappe.db.set_value("Task", app_name, app_field, 1, update_modified=False)
				changed = True

		if changed:
			frappe.clear_document_cache("Task", app_name)
			frappe.publish_realtime(
				"cgm_task_status_changed",
				{"task": app_name, "project": finance_task.project, "soft_sync": 1},
			)
		return changed
	finally:
		frappe.flags.cgm_syncing_invoice_verification = False


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
	# With amendment invoices, every attached Invoice line must be verified —
	# do not trust the legacy task-level verified flag alone.
	rows = [r for r in get_invoice_lines(task, profile) if r.get("attachment")]
	if len(rows) > 1 or any(cint(r.get("is_amendment")) for r in rows):
		if not all_invoice_lines_verified(task, profile):
			return False
		if finance_task is None and task.project:
			finance_name = get_application_finance_task(task.project, profile)
			finance_task = frappe.get_doc("Task", finance_name) if finance_name else None
		if finance_task:
			fin_rows = [r for r in get_invoice_lines(finance_task, profile) if r.get("attachment")]
			if fin_rows and not all_invoice_lines_verified(finance_task, profile):
				return False
		return True

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


def application_has_pending_amendment_invoice(task, profile: ApplicationFinanceProfile) -> bool:
	"""True when an amendment Invoice row still needs attachment or Finance verify."""
	for row in get_invoice_lines(task, profile):
		if not cint(row.get("is_amendment")):
			continue
		if not row.get("attachment") or not cint(row.get("verified")):
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
	if finance_task is None and task.project:
		finance_name = get_application_finance_task(task.project, profile)
		finance_task = frappe.get_doc("Task", finance_name) if finance_name else None
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		task_client_paid_directly,
	)

	# Pending amendment invoices keep Create/Application open until Finance verifies them.
	if application_has_pending_amendment_invoice(task, profile):
		return False
	if finance_task and application_has_pending_amendment_invoice(finance_task, profile):
		return False

	# Client-pays and company-pays share the same application requirements:
	# invoice submitted + Finance-verified (+ certificate or POP when configured).
	# Only the finance task skips the Journal Entry on the client-pays path.
	submitted = invoice_attached(task, profile)
	if profile.application_submitted_field and task.meta.has_field(profile.application_submitted_field):
		submitted = submitted or bool(task.get(profile.application_submitted_field))
	if not submitted:
		return False
	if not invoice_verified_for_application_task(task, profile, finance_task):
		return False

	# Shipping Line: both tasks complete only after Finance verifies the receipt
	# (POP visible on Documentation; Documentation attaches receipt; Finance verifies).
	if profile.requires_pop:
		pop_ok = pop_attached(task, profile) or (
			finance_task is not None and pop_attached(finance_task, profile)
		)
		if not pop_ok:
			return False
		rec_ok = receipt_verified(task, profile) or (
			finance_task is not None and receipt_verified(finance_task, profile)
		)
		return bool(rec_ok)

	# Entry: complete as soon as Finance verifies the Entry Slip invoice.
	# ENTRY customs document remains optional on Clearance Documents.
	if profile.complete_on_invoice_verified:
		return True

	if not profile.certificate_document_code and not profile.legacy_certificate_codes:
		# No certificate step (e.g. KPA): keep open for explicit Mark Completed
		# when Finance uses the client-pays path; company-pays may auto-complete.
		if finance_task and task_client_paid_directly(finance_task):
			return False
		return True
	return certificate_uploaded(task, profile)


def can_complete_application_finance_task(task, profile: ApplicationFinanceProfile) -> bool:
	if not is_application_finance_task(int(task.get("custom_sequence_no") or 0), profile):
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		client_paid_settlement_ready,
		task_client_paid_directly,
		task_has_recorded_payment,
	)

	rows = [r for r in get_invoice_lines(task, profile) if r.get("attachment")]
	if not rows:
		return False
	if not all_invoice_lines_verified(task, profile):
		return False

	# Every invoice line must be settled (per-line JE / client-pays, or legacy task-level).
	if not all_invoice_lines_settled(task, profile):
		# Backward compat: single primary invoice + task-level payment / client-pays.
		if len(rows) == 1 and not cint(rows[0].get("is_amendment")):
			if task_client_paid_directly(task):
				if not client_paid_settlement_ready(task):
					return False
			elif not task_has_recorded_payment(task):
				return False
		else:
			return False

	# Shipping Line: POP + Documentation receipt + Finance receipt verify.
	if profile.requires_pop:
		if not pop_attached(task, profile):
			return False
		if not receipt_attached_for_payment_workflow(task, profile):
			return False
		if not receipt_verified(task, profile):
			return False
		return True

	# Receipt required after settlement except Entry Slip (requires_receipt_verification=False).
	if profile.requires_receipt_verification:
		if not receipt_attached_for_payment_workflow(task, profile):
			return False
		if not receipt_verified(task, profile):
			return False
		return True

	# Entry Slip: receipt attachment is optional.
	return True


def build_application_purchase_invoice_lines(
	task, profile: ApplicationFinanceProfile
) -> list[dict]:
	"""PI lines from the invoice attachment + Purchase Item.

	Amount is entered on Make Payment (Journal Entry), not on the finance line.
	"""
	if not is_application_finance_task(int(task.get("custom_sequence_no") or 0), profile):
		return []
	inv = get_invoice_line(task, profile)
	if not inv or not inv.attachment:
		return []
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
			"rate": 0,
			"amount": 0,
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
	# Non-POP flows: Finance upload of the receipt is confirmation — auto-stamp verified.
	# Shipping Line: Documentation attaches receipt; Finance verifies manually — do not auto-stamp.
	if is_application_finance_task(seq, profile) and not profile.requires_pop:
		rec = get_receipt_line(task, profile)
		if rec and rec.attachment and not cint(rec.verified):
			rec.verified = 1
			rec.verified_by = rec.verified_by or frappe.session.user
			rec.verified_on = rec.verified_on or now_datetime()
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
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		ACTION_CONFIRM_CLIENT_PAID,
		ACTION_UPLOAD_POP,
		ACTION_UPLOAD_RECEIPT,
		ACTION_VERIFY_INVOICE,
		flow_for_profile,
		throw_unless_responsibility,
		user_has_responsibility,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import _finance_line_verified_changed
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		task_client_paid_directly,
		task_has_recorded_payment,
	)

	if frappe.session.user == "Administrator":
		return
	if frappe.flags.get("cgm_syncing_application_receipt") or frappe.flags.get(
		"cgm_ensuring_application_finance_lines"
	):
		return
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_application_workflow_task(seq, profile) or not task_has_finance_table(task):
		return
	flow = flow_for_profile(profile)
	can_verify = user_has_responsibility(flow, ACTION_VERIFY_INVOICE)
	can_receipt = user_has_responsibility(flow, ACTION_UPLOAD_RECEIPT)
	can_pop = user_has_responsibility(flow, ACTION_UPLOAD_POP)
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if (row.payment_item or profile.payment_item) != profile.payment_item:
			continue
		if row.verified and not can_verify and _finance_line_verified_changed(task, row):
			frappe.throw(
				f"Only the configured <b>Verify Invoice</b> role group can verify "
				f"<b>{row.line_label or 'finance line'}</b> "
				"(CGM Shipping Settings → Document responsibilities)."
			)
		if not row.verified and not can_verify and _finance_line_verified_changed(task, row):
			prev = task.get_doc_before_save()
			prev_row = _find_line(prev, row.line_type, profile) if prev else None
			if prev_row and cint(prev_row.verified):
				frappe.throw(
					f"<b>{row.line_label or 'Finance line'}</b> is verified and cannot be changed here."
				)

		# Per-invoice Client will pay (replaces task-level checkbox on finance forms).
		if row.line_type == LINE_INVOICE and _finance_line_client_paid_changed(task, row):
			if not is_application_finance_task(seq, profile):
				frappe.throw(
					"<b>Client will pay</b> can only be set on the finance payment task."
				)
			throw_unless_responsibility(
				flow, ACTION_CONFIRM_CLIENT_PAID, label="select Client will pay"
			)

		prev = task.get_doc_before_save()
		prev_row = _find_line(prev, row.line_type, profile) if prev else None
		prev_attachment = prev_row.attachment if prev_row else None
		if not row.attachment or row.attachment == prev_attachment:
			continue

		if row.line_type == LINE_POP and profile.requires_pop:
			if is_application_task(seq, profile):
				frappe.throw(
					f"The <b>{profile.pop_label or 'POP'}</b> is attached on the finance payment task "
					"after payment (Finance bank POP or client portal upload). "
					"It appears here automatically for Documentation."
				)
			if is_application_finance_task(seq, profile) and not can_pop:
				# Client portal / system uploads set flags and bypass; desk users need Upload POP.
				frappe.throw(
					f"Only the configured <b>Upload POP</b> role group can attach the "
					f"<b>{profile.pop_label or 'POP'}</b> "
					"(CGM Shipping Settings → Document responsibilities)."
				)
			if is_application_finance_task(seq, profile):
				if not (
					task_has_recorded_payment(task)
					or task_client_paid_directly(task)
					or finance_has_client_paid_invoice_line(task, profile)
				):
					frappe.throw(
						f"Record payment (or tick <b>Client will pay</b> on the invoice row) before attaching the "
						f"<b>{profile.pop_label or 'POP'}</b>."
					)
			continue

		if row.line_type != LINE_RECEIPT:
			continue
		if profile.requires_pop:
			# Shipping Line: Documentation attaches receipt (application or finance) after POP.
			pop_ready = pop_attached(task, profile)
			if not pop_ready and task.project:
				fin_name = get_application_finance_task(task.project, profile)
				if fin_name:
					pop_ready = pop_attached(frappe.get_doc("Task", fin_name), profile)
			if is_application_task(seq, profile):
				if not can_receipt:
					frappe.throw(
						f"Only the configured <b>Upload Receipt</b> role group can attach the "
						f"<b>{profile.receipt_label}</b> "
						"(CGM Shipping Settings → Document responsibilities)."
					)
				if not pop_ready:
					frappe.throw(
						f"Wait for Finance/client to attach the <b>{profile.pop_label or 'POP'}</b> "
						f"before uploading the <b>{profile.receipt_label}</b>."
					)
				continue
			if is_application_finance_task(seq, profile):
				if not can_receipt:
					frappe.throw(
						f"Only the configured <b>Upload Receipt</b> role group can attach the "
						f"<b>{profile.receipt_label}</b> "
						"(CGM Shipping Settings → Document responsibilities)."
					)
				if not pop_ready:
					frappe.throw(
						f"Attach the <b>{profile.pop_label or 'POP'}</b> before uploading the "
						f"<b>{profile.receipt_label}</b>."
					)
			continue

		# Legacy non-POP flows: receipt on finance after payment.
		if is_application_task(seq, profile):
			frappe.throw(
				f"The <b>{profile.receipt_label}</b> is uploaded on the finance payment task "
				"after recording payment. Attach only the invoice (and certificate) here."
			)
		if is_application_finance_task(seq, profile):
			if not can_receipt:
				frappe.throw(
					f"Only the configured <b>Upload Receipt</b> role group can attach the "
					f"<b>{profile.receipt_label}</b> "
					"(CGM Shipping Settings → Document responsibilities)."
				)
			if task.project and not application_payment_made_for_project(task.project, profile):
				frappe.throw(
					f"Record payment before uploading the <b>{profile.receipt_label}</b>."
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
