"""Task hooks, requirements, finance, and completion rules."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	PERMIT_REGISTER_FIELD,
	PRE_CLEARANCE_STAGE,
	SEA_TASK_FLOW_KEY,
	TASK_DOCUMENTS_FIELD,
	TASK_FINANCE_FIELD,
	TASK_PERMITS_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.documents import refresh_project_documents


def task_sequence(task) -> int:
	return int(task.get("custom_sequence_no") or 0)


def get_task_name_by_sequence(project: str, sequence_no: int) -> str | None:
	if not project or not sequence_no:
		return None
	return frappe.db.get_value(
		"Task",
		{
			"project": project,
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": sequence_no,
		},
		"name",
	)



# ==================== Sea task requirements ====================

"""
Strict interpreter for sea task requirements in CGM Shipping Settings.

Settings hold the rules; this module reads and validates them - no runtime fallbacks.
"""

SUPPLIER_INVOICE_CODE = "SUP_INV"

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


def is_document_checkpoint_task(sequence_no: int) -> bool:
	return any(
		r.requirement_type == "Document Checkpoint" for r in rows_by_sequence().get(sequence_no, [])
	)


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


def document_checkpoint_sequences() -> frozenset[int]:
	return frozenset(
		seq
		for seq, rows in rows_by_sequence().items()
		if any(r.requirement_type == "Document Checkpoint" for r in rows)
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

	from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
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
		"document_checkpoint_seqs": sorted(document_checkpoint_sequences()),
		"ucr_application_seqs": sorted(ucr_application_sequences()),
		"finance_document_seqs": sorted(finance_payment_with_supplier_invoice_sequences()),
		"permit_finance_seqs": permit_finance,
		"ucr_finance_seqs": ucr_finance,
		"permit_stage_by_seq": {str(k): v for k, v in stage_by_seq.items()},
		"permissions": get_task_form_permissions(),
		"finance_department": frappe.db.get_single_value(
			"CGM Shipping Settings", "custom_finance_department"
		),
	}


# ==================== Task finance lines ====================

"""Task Finance Lines - invoices and receipts (separate from clearance documents)."""
from frappe.utils import cint, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_DOCUMENTS_FIELD

LINE_INVOICE = "Invoice"
LINE_RECEIPT = "Receipt"
PAYMENT_UCR = "UCR"

UCR_INVOICE_LABEL = "UCR Invoice"
UCR_RECEIPT_LABEL = "UCR Receipt"

# Document types that belong on Task Finance Lines, not Task Documents.
INVOICE_DOCUMENT_TYPE_CODES = frozenset({"UCR_DOC", "UCR_INV", "UCR Invoice", "SUP_INV"})
# Link values that may still exist on rows after the Document Type master was removed.
LEGACY_INVOICE_DOCUMENT_TYPE_LINKS = frozenset(
	{"UCR_DOC", "UCR_INV", "UCR Invoice", "SUP_INV", "Supplier Invoice"}
)


def task_has_finance_table(task) -> bool:
	return bool(task.meta.has_field(TASK_FINANCE_FIELD))


@frappe.request_cache
def task_finance_line_has_item_code() -> bool:
	"""True when Task Finance Line.item_code is installed (after bench migrate)."""
	meta = frappe.get_meta("Task Finance Line")
	if not meta.has_field("item_code"):
		return False
	return bool(frappe.db.has_column("Task Finance Line", "item_code"))


def _task_seq(task) -> int:
	return int(task.get("custom_sequence_no") or 0)


def is_invoice_clearance_document_row(document_type: str | None) -> bool:
	"""True when this Shipment Document row is an invoice (not IDF certificate, etc.)."""
	if not document_type:
		return False
	if document_type in LEGACY_INVOICE_DOCUMENT_TYPE_LINKS:
		return True
	if frappe.db.exists("Document Type", document_type):
		code = frappe.db.get_value("Document Type", document_type, "code")
		return code in INVOICE_DOCUMENT_TYPE_CODES
	return False


def purge_invoice_rows_from_task_documents_db(task_name: str) -> int:
	"""Delete invoice rows from DB (runs before link validation on save)."""
	if not task_name:
		return 0
	legacy = tuple(LEGACY_INVOICE_DOCUMENT_TYPE_LINKS)
	placeholders = ", ".join(["%s"] * len(legacy))
	names = frappe.db.sql(
		f"""
		SELECT name
		FROM `tabShipment Document`
		WHERE parenttype = 'Task'
		  AND parentfield = 'custom_task_documents'
		  AND parent = %s
		  AND document_type IN ({placeholders})
		""",
		(task_name, *legacy),
		pluck=True,
	)
	for name in names:
		frappe.db.delete("Shipment Document", name)
	return len(names)


def purge_all_invoice_clearance_document_rows() -> int:
	"""Remove all legacy invoice rows from Task Clearance Documents."""
	legacy = tuple(LEGACY_INVOICE_DOCUMENT_TYPE_LINKS)
	placeholders = ", ".join(["%s"] * len(legacy))
	names = frappe.db.sql(
		f"""
		SELECT name
		FROM `tabShipment Document`
		WHERE parenttype = 'Task'
		  AND parentfield = 'custom_task_documents'
		  AND document_type IN ({placeholders})
		""",
		legacy,
		pluck=True,
	)
	for name in names:
		frappe.db.delete("Shipment Document", name)
	return len(names)


def migrate_invoice_attachments_to_finance_lines_sql() -> None:
	"""Copy invoice attachments to Task Finance Lines without loading/saving Task."""
	if not frappe.db.table_exists("tabTask Finance Line"):
		return
	legacy = tuple(LEGACY_INVOICE_DOCUMENT_TYPE_LINKS)
	placeholders = ", ".join(["%s"] * len(legacy))
	frappe.db.sql(
		f"""
		UPDATE `tabTask Finance Line` tfl
		INNER JOIN `tabShipment Document` sd
			ON sd.parent = tfl.parent
			AND sd.parenttype = 'Task'
			AND sd.parentfield = 'custom_task_documents'
			AND sd.document_type IN ({placeholders})
		SET tfl.attachment = sd.attachment
		WHERE tfl.parenttype = 'Task'
		  AND tfl.parentfield = %s
		  AND tfl.line_type = %s
		  AND (tfl.payment_item IS NULL OR tfl.payment_item = %s)
		  AND IFNULL(tfl.attachment, '') = ''
		  AND IFNULL(sd.attachment, '') != ''
		""",
		(*legacy, TASK_FINANCE_FIELD, LINE_INVOICE, PAYMENT_UCR),
	)


def remove_invoice_rows_from_task_documents(task) -> None:
	"""Drop invoice/receipt rows from Clearance Documents - those use Task Finance Lines."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_DOCUMENTS_FIELD

	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return
	for row in list(task.get(TASK_DOCUMENTS_FIELD) or []):
		if is_invoice_clearance_document_row(row.document_type):
			task.remove(row)


def ensure_idf_certificate_document_row(task) -> None:
	"""Task 3: only IDF/UCR certificate on Clearance Documents (optional until issued)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import get_document_type_link_name

	if not is_ucr_application_task(_task_seq(task)):
		return
	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return
	remove_invoice_rows_from_task_documents(task)
	dt_name = get_document_type_link_name("IDF_CERT")
	if not dt_name:
		return
	existing = {r.document_type for r in task.get(TASK_DOCUMENTS_FIELD) or [] if r.document_type}
	if dt_name in existing:
		return
	task.append(TASK_DOCUMENTS_FIELD, {"document_type": dt_name, "status": "Missing"})


def prepare_ucr_task_tables(task) -> None:
	"""UCR tasks: finance lines for invoice/receipt; clearance docs for IDF certificate only."""
	seq = _task_seq(task)
	if not is_ucr_workflow_task(seq):
		return
	seed_ucr_finance_lines(task)
	if is_ucr_application_task(seq):
		ensure_idf_certificate_document_row(task)
	elif is_ucr_finance_payment_task(seq):
		remove_invoice_rows_from_task_documents(task)
		copy_ucr_invoice_to_finance_task(task)


def _find_line(task, line_type: str, payment_item: str = PAYMENT_UCR):
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if row.line_type == line_type and (row.payment_item or PAYMENT_UCR) == payment_item:
			return row
	return None


def _ensure_line(task, line_type: str, label: str, payment_item: str = PAYMENT_UCR):
	row = _find_line(task, line_type, payment_item)
	if row:
		if not row.line_label:
			row.line_label = label
		if (
			line_type == LINE_INVOICE
			and task_finance_line_has_item_code()
			and not row.get("item_code")
		):
			row.item_code = get_purchase_item_for_payment_item(payment_item, task.company)
		return row
	payload = {
		"line_label": label,
		"line_type": line_type,
		"payment_item": payment_item,
	}
	if line_type == LINE_INVOICE and task_finance_line_has_item_code():
		payload["item_code"] = get_purchase_item_for_payment_item(payment_item, task.company)
	task.append(TASK_FINANCE_FIELD, payload)
	return task.get(TASK_FINANCE_FIELD)[-1]


def seed_ucr_finance_lines(task) -> None:
	"""Pre-fill UCR Invoice + UCR Receipt rows on UCR tasks."""
	if not task_has_finance_table(task):
		return
	seq = _task_seq(task)
	if not is_ucr_workflow_task(seq):
		return

	_ensure_line(task, LINE_INVOICE, UCR_INVOICE_LABEL)
	_ensure_line(task, LINE_RECEIPT, UCR_RECEIPT_LABEL)
	if is_ucr_finance_payment_task(seq):
		copy_ucr_invoice_to_finance_task(task)


def ensure_ucr_finance_lines_saved(task) -> bool:
	"""Persist missing UCR Invoice / UCR Receipt rows on Create UCR and Finance pays UCR."""
	if not task_has_finance_table(task):
		return False
	seq = _task_seq(task)
	if not is_ucr_workflow_task(seq):
		return False

	before = {
		(r.line_type, r.payment_item or PAYMENT_UCR)
		for r in task.get(TASK_FINANCE_FIELD) or []
	}
	seed_ucr_finance_lines(task)
	after = {
		(r.line_type, r.payment_item or PAYMENT_UCR)
		for r in task.get(TASK_FINANCE_FIELD) or []
	}
	if after - before:
		frappe.flags.cgm_ensuring_ucr_finance_lines = True
		try:
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_ensuring_ucr_finance_lines = False
		return True
	return False


def migrate_invoice_attachments_from_documents(task) -> None:
	"""Move legacy invoice attachments from Clearance Documents → finance lines."""
	if not task_has_finance_table(task):
		return
	seq = _task_seq(task)
	if not is_ucr_workflow_task(seq):
		return

	seed_ucr_finance_lines(task)
	inv_line = _find_line(task, LINE_INVOICE)
	if not inv_line:
		return
	for row in list(task.get(TASK_DOCUMENTS_FIELD) or []):
		if not is_invoice_clearance_document_row(row.document_type):
			continue
		if row.attachment and not inv_line.attachment:
			inv_line.attachment = row.attachment
		task.remove(row)


def copy_ucr_invoice_to_finance_task(finance_task) -> None:
	"""Copy declarant UCR invoice onto the finance task for review."""
	if not is_ucr_finance_payment_task(_task_seq(finance_task)) or not finance_task.project:
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		get_ucr_application_task,
	)

	app_name = get_ucr_application_task(finance_task.project)
	if not app_name:
		return

	app = frappe.get_doc("Task", app_name)
	app_line = _find_line(app, LINE_INVOICE)
	if not app_line or not app_line.attachment:
		return

	fin_line = _ensure_line(finance_task, LINE_INVOICE, UCR_INVOICE_LABEL)
	if not fin_line.attachment:
		fin_line.attachment = app_line.attachment
	if app_line.amount and not fin_line.amount:
		fin_line.amount = app_line.amount
	if task_finance_line_has_item_code():
		app_item = app_line.get("item_code")
		fin_item = fin_line.get("item_code")
		if app_item and not fin_item:
			fin_line.item_code = app_item
		elif not fin_item:
			fin_line.item_code = get_purchase_item_for_payment_item(
				PAYMENT_UCR, finance_task.company
			)


def ucr_payment_made_for_project(project: str) -> bool:
	"""True when Finance pays UCR has a Journal Entry (Draft or Submitted).

	A Journal Entry attached to the finance task counts as "payment recorded"
	even before it is posted, so Operations can upload the UCR receipt without
	waiting for Finance to submit; only a Cancelled JE (docstatus 2) does not.
	"""
	if not project:
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		get_ucr_finance_task,
	)

	finance_name = get_ucr_finance_task(project)
	if not finance_name:
		return False
	je_name = frappe.db.get_value("Task", finance_name, "custom_journal_entry")
	if not je_name or not frappe.db.exists("Journal Entry", je_name):
		return False
	return int(frappe.db.get_value("Journal Entry", je_name, "docstatus") or 0) != 2


def copy_ucr_receipt_to_finance_task(application_task) -> str | None:
	"""Copy declarant UCR receipt onto Finance pays UCR. Returns finance task name."""
	if not is_ucr_application_task(_task_seq(application_task)) or not application_task.project:
		return None

	app_rec = _find_line(application_task, LINE_RECEIPT)
	if not app_rec or not app_rec.attachment:
		return None

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		get_ucr_finance_task,
	)

	finance_name = get_ucr_finance_task(application_task.project)
	if not finance_name:
		return None

	finance_task = frappe.get_doc("Task", finance_name)
	seed_ucr_finance_lines(finance_task)
	fin_rec = _find_line(finance_task, LINE_RECEIPT)
	if not fin_rec:
		return None

	# Persist a new receipt row without running finance before_save hooks.
	if not fin_rec.name:
		frappe.flags.cgm_syncing_ucr_receipt = True
		try:
			finance_task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_ucr_receipt = False
		fin_rec = _find_line(frappe.get_doc("Task", finance_name), LINE_RECEIPT)
		if not fin_rec:
			return None

	if fin_rec.attachment == app_rec.attachment:
		return finance_name

	updates = {"attachment": app_rec.attachment}
	if app_rec.amount and not fin_rec.amount:
		updates["amount"] = app_rec.amount
	frappe.db.set_value("Task Finance Line", fin_rec.name, updates, update_modified=False)

	return finance_name


def get_ucr_invoice_line(task):
	return _find_line(task, LINE_INVOICE)


def get_ucr_receipt_line(task):
	return _find_line(task, LINE_RECEIPT)


def ucr_invoice_attached(task) -> bool:
	line = get_ucr_invoice_line(task)
	return bool(line and line.attachment)


def ucr_receipt_attached(task) -> bool:
	line = get_ucr_receipt_line(task)
	return bool(line and line.attachment)


def ucr_invoice_verified(task) -> bool:
	line = get_ucr_invoice_line(task)
	return bool(line and line.verified)


def ucr_receipt_verified(task) -> bool:
	line = get_ucr_receipt_line(task)
	return bool(line and line.verified)


def normalize_finance_line_verification(task) -> None:
	"""Set verified_by / verified_on when Finance ticks Verified."""
	if not task_has_finance_table(task):
		return
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if row.verified:
			if not row.verified_by:
				row.verified_by = frappe.session.user
			if not row.verified_on:
				row.verified_on = now_datetime()
		elif row.verified_by or row.verified_on:
			row.verified_by = None
			row.verified_on = None

	seq = _task_seq(task)
	if is_ucr_finance_payment_task(seq):
		inv = get_ucr_invoice_line(task)
		rec = get_ucr_receipt_line(task)
		if inv and inv.verified and task.meta.has_field("custom_ucr_invoice_verified"):
			task.custom_ucr_invoice_verified = 1
		if rec and rec.verified and task.meta.has_field("custom_ucr_receipt_verified"):
			task.custom_ucr_receipt_verified = 1


def _find_line_in_task(task, line_type: str, payment_item: str = PAYMENT_UCR):
	if not task:
		return None
	return _find_line(task, line_type, payment_item)


def _finance_line_verified_changed(task, row) -> bool:
	"""True when Verified by Finance was toggled on this save."""
	prev = task.get_doc_before_save()
	if not prev:
		return bool(row.verified)
	prev_row = _find_line_in_task(prev, row.line_type, row.payment_item or PAYMENT_UCR)
	if not prev_row:
		return bool(row.verified)
	return cint(row.verified) != cint(prev_row.verified)


def enforce_finance_line_permissions(task) -> None:
	"""Only users with finance-payment template department roles may verify finance lines."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		user_has_department_for_sequence,
		user_has_finance_department_access,
	)

	if frappe.session.user == "Administrator":
		return
	if frappe.flags.get("cgm_syncing_ucr_receipt") or frappe.flags.get("cgm_ensuring_ucr_finance_lines"):
		return

	seq = _task_seq(task)
	if not is_ucr_workflow_task(seq) or not task_has_finance_table(task):
		return

	is_finance = user_has_finance_department_access()
	can_attach_receipt = user_has_department_for_sequence(frappe.session.user, seq)

	for row in task.get(TASK_FINANCE_FIELD) or []:
		if row.verified and not is_finance and _finance_line_verified_changed(task, row):
			frappe.throw(
				f"Only <b>Finance</b> can verify <b>{row.line_label or 'finance line'}</b>."
			)
		if not row.verified and not is_finance and _finance_line_verified_changed(task, row):
			# Declarant must not uncheck Finance verification synced from Finance pays UCR.
			prev = task.get_doc_before_save()
			prev_row = _find_line_in_task(prev, row.line_type, row.payment_item or PAYMENT_UCR)
			if prev_row and cint(prev_row.verified):
				frappe.throw(
					f"<b>{row.line_label or 'Finance line'}</b> is verified by Finance and cannot be changed here."
				)
		if row.line_type == LINE_RECEIPT and is_ucr_application_task(seq) and row.attachment:
			if not can_attach_receipt:
				frappe.throw(
					f"Only <b>Declarant</b> or <b>Operations</b> can attach <b>{row.line_label}</b>."
				)
			if task.project and not ucr_payment_made_for_project(task.project):
				frappe.throw(
					"Finance must record UCR payment before uploading the <b>UCR Receipt</b>."
				)
		if row.line_type == LINE_RECEIPT and is_ucr_finance_payment_task(seq) and row.attachment:
			if frappe.flags.get("cgm_syncing_ucr_receipt"):
				continue
			prev = task.get_doc_before_save()
			prev_rec = get_ucr_receipt_line(prev) if prev else None
			prev_attachment = prev_rec.attachment if prev_rec else None
			if row.attachment != prev_attachment:
				frappe.throw(
					"Declarant uploads the <b>UCR Receipt</b> on <b>Create UCR (IDF)</b>. "
					"Finance verifies it here."
				)
		if (
			row.line_type == LINE_INVOICE
			and is_ucr_finance_payment_task(seq)
			and row.attachment
			and row.verified is None
		):
			pass


def sync_ucr_finance_lines_to_idf_record(task) -> None:
	"""Mirror UCR invoice/receipt from Task Finance → Project IDF UCR Record."""
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

	inv = get_ucr_invoice_line(task)
	rec = get_ucr_receipt_line(task)

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
	if task.status == "Completed" and is_ucr_finance_payment_task(_task_seq(task)):
		doc.payment_status = "Complete"

	doc.save(ignore_permissions=True)


def sync_idf_certificate_to_project(task) -> None:
	"""Copy IDF/UCR certificate from Task Documents → Project shipment documents + IDF record."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SHIPMENT_DOCUMENTS_FIELD
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		append_verified_doc_row,
		get_document_type_link_name,
	)

	if not task.project:
		return

	cert_url = None
	for row in task.get("custom_task_documents") or []:
		code = get_document_type_code(row.document_type)
		if code in ("IDF_CERT", "UCR_CERT", "IDF") and row.attachment:
			cert_url = row.attachment
			break

	if not cert_url:
		return

	project = frappe.get_doc("Project", task.project)
	dt_name = get_document_type_link_name("IDF_CERT") or get_document_type_link_name("IDF")
	if dt_name and project.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		append_verified_doc_row(project, dt_name, cert_url)
		frappe.flags.cgm_syncing_permits = True
		try:
			project.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_permits = False

	if frappe.db.exists("DocType", "IDF UCR Record"):
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


def _sync_ucr_line_verification_to_application(
	finance_task, line_getter, line_type, app_field, seed=False
) -> bool:
	"""Mirror one UCR finance line's verification from Finance pays UCR (seq 4) onto the
	matching line + flag on the Create UCR task (seq 3). Shared by invoice/receipt."""
	if (
		not is_ucr_finance_payment_task(_task_seq(finance_task))
		or not finance_task.project
		or not task_has_finance_table(finance_task)
	):
		return False

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		get_ucr_application_task,
	)

	app_name = get_ucr_application_task(finance_task.project)
	if not app_name:
		return False

	if seed:
		seed_ucr_finance_lines(finance_task)
	fin_line = line_getter(finance_task)
	if not fin_line or not fin_line.verified:
		return False

	app_line_name = frappe.db.get_value(
		"Task Finance Line",
		{
			"parent": app_name,
			"parenttype": "Task",
			"parentfield": TASK_FINANCE_FIELD,
			"line_type": line_type,
			"payment_item": PAYMENT_UCR,
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

	app_task = frappe.get_doc("Task", app_name)
	if app_task.meta.has_field(app_field) and not app_task.get(app_field):
		frappe.db.set_value("Task", app_name, app_field, 1, update_modified=False)
		changed = True

	if changed and finance_task.project:
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			auto_complete_ucr_application_for_project,
		)

		auto_complete_ucr_application_for_project(finance_task.project)

	return changed


def sync_ucr_verification_to_application_task(finance_task) -> bool:
	"""Mirror invoice verification from Finance pays UCR (seq 4) → Create UCR task (seq 3)."""
	return _sync_ucr_line_verification_to_application(
		finance_task, get_ucr_invoice_line, LINE_INVOICE, "custom_ucr_invoice_verified", seed=True
	)


def sync_ucr_receipt_verification_to_application_task(finance_task) -> bool:
	"""Mirror receipt verification from Finance pays UCR (seq 4) → Create UCR task (seq 3)."""
	return _sync_ucr_line_verification_to_application(
		finance_task, get_ucr_receipt_line, LINE_RECEIPT, "custom_ucr_receipt_verified"
	)


def sync_ucr_status_from_finance_to_application(application_task) -> bool:
	"""Pull invoice + receipt verification from Finance pays UCR when opening Create UCR."""
	if not is_ucr_application_task(_task_seq(application_task)) or not application_task.project:
		return False

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		get_ucr_finance_task,
	)

	finance_name = get_ucr_finance_task(application_task.project)
	if not finance_name:
		return False

	finance_task = frappe.get_doc("Task", finance_name)
	changed = sync_ucr_verification_to_application_task(finance_task)
	changed = sync_ucr_receipt_verification_to_application_task(finance_task) or changed
	return changed




# ==================== Task completion rules ====================

"""
Sea task completion rules - driven by CGM Shipping Settings where possible.

Task level: invoices/receipts on Task Finance Lines; clearance docs on Task Documents; permits on Task Permits.
Project level: custom_permit_register synced from Task permits (see sync_task_permits_to_project).
"""

from cgm_shipping.cgm_worldwide_shipping.customizations.documents import get_document_type_link_name
from cgm_shipping.cgm_worldwide_shipping.customizations.project import derive_permit_clearance_phase

TASK_DOCUMENT_TYPE_DEFAULTS: dict[str, dict] = {
	"SUP_INV": {
		"category": "Finance",
		"required_stage": "IDF & UCR",
		"default_required": 0,
	},
	"IDF_CERT": {
		"category": "Customs",
		"required_stage": "IDF & UCR",
		"default_required": 0,
	},
	"INSPECT": {
		"category": "Compliance",
		"required_stage": "Client inspection",
		"default_required": 0,
	},
	"MANIFEST": {
		"category": "Customs",
		"required_stage": "Arrival & manifest",
		"default_required": 0,
	},
	"ENTRY": {
		"category": "Customs",
		"required_stage": "Customs entry & taxes",
		"default_required": 0,
	},
	"DO": {
		"category": "Customs",
		"required_stage": "Port & line (DO / charges)",
		"default_required": 0,
	},
	"FIELD": {
		"category": "Compliance",
		"required_stage": "Field clearance & release",
		"default_required": 0,
	},
	"BL": {
		"category": "Transport",
		"required_stage": "Arrival & manifest",
		"default_required": 0,
	},
}


def ensure_task_document_types() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		DOCUMENT_TYPE_DEFAULTS,
		ensure_document_types,
	)

	ensure_document_types()
	for code, defaults in TASK_DOCUMENT_TYPE_DEFAULTS.items():
		if get_document_type_link_name(code):
			continue
		doc = frappe.new_doc("Document Type")
		doc.code = code
		for key, value in defaults.items():
			setattr(doc, key, value)
		doc.insert(ignore_permissions=True)
		if doc.meta.is_submittable and doc.docstatus == 0:
			doc.submit()


def get_document_type_code(document_type_link: str | None) -> str | None:
	if not document_type_link:
		return None
	return frappe.db.get_value("Document Type", document_type_link, "code")


def attached_document_codes(task) -> set[str]:
	codes = set()
	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		code = get_document_type_code(row.document_type)
		if code and row.attachment:
			codes.add(code)
	return codes


def strip_task_documents_for_checkpoint(task) -> bool:
	"""Document checkpoint tasks review Project files — no Task Documents child rows."""
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_document_checkpoint_task(seq) or not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return False
	rows = list(task.get(TASK_DOCUMENTS_FIELD) or [])
	if not rows:
		return False
	for row in rows:
		task.remove(row)
	return True


def seed_required_task_document_rows(task) -> None:
	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return
	seq = int(task.get("custom_sequence_no") or 0)
	if is_document_checkpoint_task(seq):
		strip_task_documents_for_checkpoint(task)
		return
	if is_ucr_application_task(seq):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			ensure_idf_certificate_document_row,
		)

		ensure_idf_certificate_document_row(task)
		return

	required = get_required_document_codes(seq)
	if not required:
		return

	existing_types = {row.document_type for row in task.get(TASK_DOCUMENTS_FIELD) or [] if row.document_type}
	for code in required:
		dt_name = get_document_type_link_name(code)
		if not dt_name or dt_name in existing_types:
			continue
		task.append(
			TASK_DOCUMENTS_FIELD,
			{"document_type": dt_name, "status": "Missing"},
		)
		existing_types.add(dt_name)


def validate_sea_task_can_complete(task) -> None:
	if task.get("custom_task_flow_key") != SEA_TASK_FLOW_KEY:
		return
	if frappe.flags.get("cgm_auto_completing_sea_task"):
		return

	seq = int(task.get("custom_sequence_no") or 0)
	if is_auto_complete_task(seq):
		return

	seed_required_task_document_rows(task)

	if is_permit_application_task(seq):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			validate_permit_application_can_complete,
		)

		validate_permit_application_task(task, seq)
		validate_permit_application_can_complete(task)
	elif is_ucr_application_task(seq):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			validate_ucr_application_not_manually_completed,
		)

		validate_ucr_application_not_manually_completed(task)
	elif is_document_checkpoint_task(seq):
		validate_document_checkpoint_task(task)
	elif is_light_proof_task(seq):
		validate_light_proof_task(task)
	elif not is_finance_payment_task(seq):
		validate_required_documents(task, seq)

	if is_finance_payment_task(seq):
		if is_ucr_finance_payment_task(seq):
			from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
				validate_finance_ucr_payment_task,
			)

			validate_finance_ucr_payment_task(task)
		else:
			validate_finance_task(task)
			if is_permit_finance_payment_task(seq):
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
					validate_finance_permit_payment_task,
				)

				validate_finance_permit_payment_task(task)


def validate_required_documents(task, seq: int) -> None:
	required_codes = get_required_document_codes(seq)
	if not required_codes:
		return

	attached = attached_document_codes(task)
	missing = []
	for code in required_codes:
		if code not in attached:
			label = frappe.db.get_value("Document Type", {"code": code}, "name") or code
			missing.append(label)

	if missing:
		frappe.throw(
			"Attach required documents on <b>Task Documents</b> before completing this task: "
			f"<b>{', '.join(missing)}</b>."
		)

	empty_rows = [
		row.document_type or "Document"
		for row in task.get(TASK_DOCUMENTS_FIELD) or []
		if row.document_type and not row.attachment
	]
	if empty_rows:
		frappe.throw(
			"Remove empty document rows or upload attachments for: "
			f"<b>{', '.join(empty_rows)}</b>."
		)


def validate_document_checkpoint_task(task) -> None:
	"""Human confirmation only — documents live on the Project, not on the Task."""
	if not (task.description or "").strip():
		frappe.throw(
			"Add a brief confirmation note in <b>Description</b> "
			"(e.g. <i>Final BL and COC confirmed received from client</i>) after reviewing "
			"documents on the linked <b>Project</b>."
		)


def validate_light_proof_task(task) -> None:
	has_doc = bool(attached_document_codes(task))
	has_text = bool((task.description or "").strip())
	has_ref = bool((task.get("custom_external_ref_no") or "").strip())
	if not (has_doc or has_text or has_ref):
		frappe.throw(
			"Add a task document, <b>Description</b>, or <b>External Ref No</b> before completing this step."
		)


def _permit_type_examples(limit: int = 5) -> str:
	"""Example permit codes from the Permit Type master (no hardcoded list)."""
	if not frappe.db.exists("DocType", "Permit Type"):
		return ""
	names = frappe.get_all("Permit Type", pluck="name", order_by="name asc", limit=limit)
	return ", ".join(names)


def validate_permit_application_task(task, seq: int) -> None:
	if not task.meta.has_field(TASK_PERMITS_FIELD):
		frappe.throw("Task Permits table is not available on this site. Run <b>bench migrate</b>.")

	rows = task.get(TASK_PERMITS_FIELD) or []
	examples = _permit_type_examples()
	eg = f" (e.g. {examples})" if examples else ""
	if not rows:
		frappe.throw(
			f"Add at least one permit on <b>Task Permits</b>{eg} "
			"and attach the <b>Permit Invoice</b> for each before completing this task."
		)

	missing = []
	for row in rows:
		label = row.permit_type or "Permit"
		if not row.permit_type:
			missing.append(f"Permit type{eg}")
			continue
		if not row.get("payment_invoice"):
			missing.append(f"{label} - supplier/permit invoice")

	if missing:
		frappe.throw(
			"Complete <b>Task Permits</b> before finishing this task:<ul>"
			+ "".join(f"<li>{m}</li>" for m in missing)
			+ "</ul>",
			title="Permit documents required",
		)


def validate_finance_task(task) -> None:
	seq = int(task.get("custom_sequence_no") or 0)
	# Permit finance completes via the declarant receipt-verification flow.
	if is_permit_finance_payment_task(seq):
		return
	je = task.get("custom_journal_entry")
	# A Journal Entry (even a Draft) lets the finance task proceed/complete so work
	# can move on; only a Cancelled JE (docstatus 2) does not count. The task is
	# flagged "Unpaid" (see show_finance_payment_indicator) until the JE is
	# submitted, at which point it reads "Paid".
	je_ok = bool(je) and int(frappe.db.get_value("Journal Entry", je, "docstatus") or 0) != 2
	if not je_ok:
		frappe.throw(
			"Record payment via <b>Make Payment</b> (a <b>Journal Entry</b> is created) "
			"before completing this finance task."
		)


def sync_task_permits_to_project(task) -> None:
	if frappe.flags.get("cgm_syncing_permits"):
		return
	if not task.get("project") or not task.meta.has_field(TASK_PERMITS_FIELD):
		return
	rows = task.get(TASK_PERMITS_FIELD) or []
	if not rows:
		return

	if not frappe.db.exists("Project", task.project):
		return

	project = frappe.get_doc("Project", task.project)
	if not project.meta.has_field(PERMIT_REGISTER_FIELD):
		return

	seq = int(task.get("custom_sequence_no") or 0)
	default_stage = get_permit_stage_for_sequence(seq)
	is_finance_permit_payment = is_permit_finance_payment_task(seq)

	by_type: dict[str, object] = {
		r.permit_type: r for r in project.get(PERMIT_REGISTER_FIELD) or [] if r.permit_type
	}

	for trow in rows:
		if not trow.permit_type:
			continue
		prow = by_type.get(trow.permit_type)
		if not prow:
			prow = project.append(PERMIT_REGISTER_FIELD, {})
			by_type[trow.permit_type] = prow

		prow.permit_type = trow.permit_type
		prow.stage = trow.stage or default_stage
		if trow.get("payment_invoice"):
			prow.payment_invoice = trow.payment_invoice
			prow.status = "Invoice Submitted"
			if trow.get("invoice_amount"):
				prow.invoice_amount = trow.invoice_amount
		if trow.get("permit_document"):
			prow.permit_document = trow.permit_document
		if trow.get("payment_receipt"):
			prow.payment_receipt = trow.payment_receipt
			prow.status = prow.status or "Receipt Submitted"

		if is_finance_permit_payment and task.get("custom_purchase_invoice"):
			prow.purchase_invoice = task.custom_purchase_invoice
			prow.invoice_verified = 1
			prow.status = "Invoice Verified"
		if is_finance_permit_payment and task.get("custom_payment_entry"):
			prow.payment_entry = task.custom_payment_entry
			prow.payment_date = frappe.db.get_value(
				"Payment Entry", task.custom_payment_entry, "posting_date"
			)
			prow.status = "Paid"
		if is_finance_permit_payment and trow.get("receipt_verified"):
			prow.receipt_verified = trow.receipt_verified

		if hasattr(prow, "custom_source_task"):
			prow.custom_source_task = task.name
		prow.clearance_phase = derive_permit_clearance_phase(prow)

	frappe.flags.cgm_syncing_permits = True
	try:
		project.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_syncing_permits = False


def apply_finance_payment_to_project_permits(task) -> None:
	if not is_permit_finance_payment_task(int(task.get("custom_sequence_no") or 0)):
		return
	sync_task_permits_to_project(task)


@frappe.whitelist()
def reopen_task_for_permit_attachments(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_permit_application_task(seq):
		frappe.throw("This action is only for pre-/post-clearance permit application tasks.")

	missing = [r.permit_type for r in task.get(TASK_PERMITS_FIELD) or [] if not r.get("payment_invoice")]
	if not missing and task.status != "Completed":
		frappe.throw("Task is already open, or all permit rows already have invoices attached.")

	task.status = "Open"
	task.progress = 0
	task.completed_by = None
	task.completed_on = None
	task.save(ignore_permissions=True)
	sync_task_permits_to_project(task)
	return {"task": task.name, "status": task.status, "missing_invoices": missing}


# ==================== Finance document linking ====================

"""Link Purchase Invoice / Payment Entry to sea finance Tasks and Project."""
from frappe.utils import flt, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
	is_sea_payment_task,
)


def payment_entry_allocates_purchase_invoice(payment_entry_name, purchase_invoice_name):
	"""Return True when the Payment Entry references the given Purchase Invoice."""
	if not payment_entry_name or not purchase_invoice_name:
		return False

	pe = frappe.get_doc("Payment Entry", payment_entry_name)
	for row in pe.get("references") or []:
		if row.reference_doctype == "Purchase Invoice" and row.reference_name == purchase_invoice_name:
			return True
	return False


def ensure_finance_custom_fields() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		_create_cf,
	)

	for dt, insert_after in (
		("Purchase Invoice", "project"),
		("Payment Entry", "project"),
	):
		_create_cf(
			dt,
			{
				"fieldname": "custom_cgm_source_task",
				"label": "CGM Source Task",
				"fieldtype": "Link",
				"options": "Task",
				"insert_after": insert_after,
				"read_only": 1,
				"no_copy": 1,
			},
		)


def _task_context(task) -> dict:
	if not is_sea_payment_task(task):
		frappe.throw(
			"This action is only for sea import finance payment tasks "
			"(UCR, permits, line charges, entry, KPA)."
		)
	if not task.project:
		frappe.throw("Task must be linked to a <b>Project</b> before creating finance documents.")

	company = task.company or frappe.db.get_value("Project", task.project, "company")
	return {
		"task": task.name,
		"project": task.project,
		"company": company,
		"subject": task.subject,
		"sequence_no": task.get("custom_sequence_no"),
		"purchase_invoice": task.get("custom_purchase_invoice"),
		"payment_entry": task.get("custom_payment_entry"),
	}


@frappe.whitelist()
def create_journal_payment_from_task(
	task_name: str,
	amount,
	pay_from_account: str,
	pay_to_account: str,
	posting_date: str | None = None,
	party_type: str | None = None,
	party: str | None = None,
	cheque_no: str | None = None,
	cheque_date: str | None = None,
	user_remark: str | None = None,
) -> str:
	"""Create a *draft* Journal Entry to pay a finance Task.

	Accounts are chosen in the dialog: ``pay_to_account`` is debited (the expense
	or payable being settled) and ``pay_from_account`` (Bank/Cash) is credited.
	A Party is attached to whichever account is a Payable/Receivable account.
	"""
	from frappe.utils import flt, getdate, today

	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	frappe.has_permission("Journal Entry", ptype="create", throw=True)

	task = frappe.get_doc("Task", task_name)
	amount = flt(amount)
	if amount <= 0:
		frappe.throw("Enter a payment <b>Amount</b> greater than zero.")
	if not pay_from_account or not pay_to_account:
		frappe.throw("Select both the <b>Pay From</b> and <b>Pay To</b> accounts.")
	if pay_from_account == pay_to_account:
		frappe.throw("<b>Pay From</b> and <b>Pay To</b> accounts must be different.")

	company = task.company or (
		frappe.db.get_value("Project", task.project, "company") if task.project else None
	)
	if not company:
		company = frappe.db.get_value("Account", pay_from_account, "company")
	if not company:
		frappe.throw("Could not determine the Company for this payment.")

	for acc in (pay_from_account, pay_to_account):
		acc_company = frappe.db.get_value("Account", acc, "company")
		if acc_company and acc_company != company:
			frappe.throw(f"Account <b>{acc}</b> does not belong to company <b>{company}</b>.")

	pay_to_type = frappe.db.get_value("Account", pay_to_account, "account_type")
	pay_from_type = frappe.db.get_value("Account", pay_from_account, "account_type")
	party_side = None
	if pay_to_type in ("Payable", "Receivable"):
		party_side = "to"
	elif pay_from_type in ("Payable", "Receivable"):
		party_side = "from"
	if party_side and not (party and party_type):
		frappe.throw(
			"A selected account is a <b>Party</b> account — choose a Party Type and Party."
		)

	remark = user_remark or f"{task.subject} ({task.name})"

	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	from_currency = frappe.db.get_value("Account", pay_from_account, "account_currency") or company_currency
	to_currency = frappe.db.get_value("Account", pay_to_account, "account_currency") or company_currency

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	if from_currency != company_currency or to_currency != company_currency:
		je.multi_currency = 1
	je.posting_date = getdate(posting_date) if posting_date else today()
	je.user_remark = remark
	if cheque_no:
		je.cheque_no = cheque_no
	if cheque_date:
		je.cheque_date = getdate(cheque_date)
	if je.meta.has_field("custom_cgm_source_task"):
		je.custom_cgm_source_task = task.name

	debit_row = {
		"account": pay_to_account,
		"debit_in_account_currency": amount,
		"project": task.project,
		"user_remark": remark,
	}
	credit_row = {
		"account": pay_from_account,
		"credit_in_account_currency": amount,
		"project": task.project,
		"user_remark": remark,
	}
	if party_side == "to":
		debit_row.update({"party_type": party_type, "party": party})
	elif party_side == "from":
		credit_row.update({"party_type": party_type, "party": party})

	je.append("accounts", debit_row)
	je.append("accounts", credit_row)
	je.insert()

	if task.meta.has_field("custom_journal_entry"):
		frappe.db.set_value(
			"Task", task.name, "custom_journal_entry", je.name, update_modified=False
		)

	return je.name


PAYMENT_ITEM_ITEM_CANDIDATES: dict[str, tuple[str, ...]] = {
	"UCR": ("UCR Fee", "UCR", "CGM-UCR", "Import UCR"),
	"Shipping Line": ("Shipping Line Charge", "Shipping Line", "Line Charges"),
	"Customs Entry": ("Customs Entry", "Entry Payment", "Customs Entry Charge"),
	"KPA": ("KPA Invoice", "KPA", "KPA Charge"),
}


def candidates_for_payment_item(payment_item: str) -> list[str]:
	key = (payment_item or "").strip()
	if not key:
		return []
	out: list[str] = []
	for value in PAYMENT_ITEM_ITEM_CANDIDATES.get(key, ()):
		out.append(value)
	out.extend((f"{key} Charge", key, key.upper(), key.title()))
	return out


def resolve_purchase_item_for_payment_item(payment_item: str) -> str | None:
	"""Return Item code for a task finance payment item, or None if no match."""
	return _resolve_item_code(candidates_for_payment_item(payment_item))


def get_purchase_item_for_payment_item(payment_item: str, company: str | None = None) -> str:
	"""Item for PI line from Task Finance Line payment_item (UCR, KPA, etc.)."""
	item = resolve_purchase_item_for_payment_item(payment_item)
	if item:
		return item
	return get_default_purchase_item_code(company)


def get_default_purchase_item_code(company: str | None = None) -> str:
	"""Default PI item for permit / clearance lines."""
	settings_item = None
	if frappe.db.exists("DocType", "CGM Shipping Settings"):
		settings_item = frappe.db.get_single_value(
			"CGM Shipping Settings", "custom_default_purchase_item"
		)
	if settings_item and frappe.db.exists("Item", settings_item):
		return settings_item

	for name in ("CGM-CLEARANCE-CHARGE", "Import Clearance Charge"):
		if frappe.db.exists("Item", name):
			return name

	filters = {"is_purchase_item": 1, "disabled": 0}
	item = frappe.db.get_value("Item", filters, "name", order_by="modified desc")
	if item:
		return item

	frappe.throw(
		"Set <b>Default Purchase Item</b> on <b>CGM Shipping Settings</b> "
		"(or create Item <b>CGM-CLEARANCE-CHARGE</b>) for auto-filled permit lines on Purchase Invoice."
	)


def get_permit_rows_for_purchase_invoice(task) -> list[dict]:
	"""Permit rows with invoice + amount for PI line pre-fill (permit finance steps)."""
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_permit_finance_payment_task(seq):
		return []

	if task.meta.has_field(TASK_PERMITS_FIELD) and not task.get(TASK_PERMITS_FIELD):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			ensure_finance_permit_rows_saved,
		)

		ensure_finance_permit_rows_saved(task)
		task.reload()

	rows: list = list(task.get(TASK_PERMITS_FIELD) or [])

	if not rows and task.project:
		app_seq = next(
			(app for app, fin in permit_finance_by_application_sequence().items() if fin == seq),
			None,
		)
		stage = get_permit_stage_for_sequence(app_seq) if app_seq else "Pre-clearance"
		project = frappe.get_doc("Project", task.project)
		rows = [
			r
			for r in project.get(PERMIT_REGISTER_FIELD) or []
			if r.permit_type and r.get("payment_invoice") and (r.stage or stage) == stage
		]

	out = []
	for row in rows:
		if not row.permit_type:
			continue
		out.append(
			{
				"permit_type": row.permit_type,
				"invoice_amount": flt(row.get("invoice_amount")),
				"payment_invoice": row.get("payment_invoice"),
				"stage": row.get("stage"),
			}
		)
	return out


def build_permit_purchase_invoice_lines(task) -> list[dict]:
	"""Purchase Invoice Item rows from Task / Project permits."""

	permit_rows = get_permit_rows_for_purchase_invoice(task)
	if not permit_rows:
		return []

	lines = []
	for row in permit_rows:
		permit_type = row.get("permit_type") or "Permit"
		amount = flt(row.get("invoice_amount"))
		if not amount:
			continue

		item_code = get_purchase_item_for_permit_type(permit_type, task.company)
		item_name = frappe.db.get_value("Item", item_code, "item_name") or permit_type
		desc = f"Pre-clearance permit - {permit_type}"
		invoice_ref = row.get("payment_invoice")
		if invoice_ref:
			desc += f" (ref: {invoice_ref.split('/')[-1]})"
		lines.append(
			{
				"item_code": item_code,
				"item_name": item_name,
				"description": desc,
				"qty": 1,
				"rate": amount,
				"amount": amount,
				"project": task.project,
				"permit_type": permit_type,
			}
		)
	return lines


def build_ucr_purchase_invoice_lines(task) -> list[dict]:
	"""Purchase Invoice Item rows from the UCR invoice finance line on Finance pays UCR."""
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_ucr_finance_payment_task(seq):
		return []

	inv = get_ucr_invoice_line(task)
	if not inv or not flt(inv.amount):
		return []

	amount = flt(inv.amount)
	payment_item = inv.payment_item or PAYMENT_UCR
	item_code = (
		inv.get("item_code")
		if task_finance_line_has_item_code()
		else None
	) or get_purchase_item_for_payment_item(payment_item, task.company)
	item_name = frappe.db.get_value("Item", item_code, "item_name") or UCR_INVOICE_LABEL
	desc = UCR_INVOICE_LABEL
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
			"payment_item": payment_item,
		}
	]


@frappe.whitelist()
def get_task_defaults(task_name: str) -> dict:
	"""Defaults for Purchase Invoice / Payment Entry opened from a finance Task."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	ctx = _task_context(task)
	seq = int(task.get("custom_sequence_no") or 0)
	if is_permit_finance_payment_task(seq):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			ensure_finance_permit_rows_saved,
		)

		ensure_finance_permit_rows_saved(task)
		task.reload()
	if is_ucr_finance_payment_task(seq):
		ensure_ucr_finance_lines_saved(task)
		task.reload()
	permit_rows = get_permit_rows_for_purchase_invoice(task)
	permit_lines = build_permit_purchase_invoice_lines(task)
	ucr_lines = build_ucr_purchase_invoice_lines(task)
	finance_line_items = permit_lines + ucr_lines
	remarks = f"{task.subject} ({task.name}) - {ctx['project']}"
	if is_ucr_finance_payment_task(int(task.get("custom_sequence_no") or 0)):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			get_ucr_application_task,
		)

		app_task = get_ucr_application_task(task.project) if task.project else None
		if app_task:
			remarks += f" | UCR invoice on task {app_task}"
		if ucr_lines:
			remarks += f" | {UCR_INVOICE_LABEL}: {flt(ucr_lines[0].get('rate'))}"
	if permit_rows:
		remarks += " | Permits: " + ", ".join(r["permit_type"] for r in permit_rows if r.get("permit_type"))

	return {
		**ctx,
		"permit_line_items": finance_line_items,
		"purchase_invoice_defaults": {
			"project": ctx["project"],
			"company": ctx["company"],
			"custom_cgm_source_task": task.name,
			"remarks": remarks,
		},
	}


def apply_project_from_task_to_purchase_invoice(purchase_invoice: str, task_name: str) -> None:
	"""Set Project (and source task) on PI from the finance task."""
	if not purchase_invoice or not task_name:
		return
	task = frappe.get_doc("Task", task_name)
	if not task.project:
		return

	updates = {}
	pi_meta = frappe.get_meta("Purchase Invoice")
	if pi_meta.has_field("project"):
		updates["project"] = task.project
	if pi_meta.has_field("custom_cgm_source_task"):
		updates["custom_cgm_source_task"] = task.name

	if updates:
		frappe.db.set_value("Purchase Invoice", purchase_invoice, updates, update_modified=True)

	# Avoid pi.save() here - it deadlocks when called from Purchase Invoice on_submit.
	frappe.db.sql(
		"""
		UPDATE `tabPurchase Invoice Item`
		SET project = %s
		WHERE parent = %s AND IFNULL(project, '') = ''
		""",
		(task.project, purchase_invoice),
	)


def _set_task_fields(task_name: str, values: dict) -> None:
	"""Update task finance link fields without triggering full save hooks."""
	meta = frappe.get_meta("Task")
	updates = {k: v for k, v in values.items() if meta.has_field(k)}
	if updates:
		frappe.db.set_value("Task", task_name, updates, update_modified=True)


def _enqueue_finance_job(method: str, **kwargs) -> None:
	"""Run linking in a separate job after commit (avoids Task row lock conflicts)."""

	def _enqueue():
		frappe.enqueue(
			f"cgm_shipping.cgm_worldwide_shipping.customizations.task.{method}",
			queue="short",
			enqueue_after_commit=True,
			**kwargs,
		)

	frappe.db.after_commit.add(_enqueue)


def _find_payment_entry_for_purchase_invoice(purchase_invoice: str) -> str | None:
	rows = frappe.db.sql(
		"""
		SELECT pe.name
		FROM `tabPayment Entry` pe
		INNER JOIN `tabPayment Entry Reference` ref ON ref.parent = pe.name
		WHERE ref.reference_doctype = 'Purchase Invoice'
		  AND ref.reference_name = %s
		  AND pe.docstatus = 1
		ORDER BY pe.modified DESC
		LIMIT 1
		""",
		purchase_invoice,
		pluck=True,
	)
	return rows[0] if rows else None


def _resolve_purchase_invoice_for_task(task, payment_entry: str) -> str | None:
	task_name = task.name
	pi_name = task.get("custom_purchase_invoice")
	if pi_name and frappe.db.exists("Purchase Invoice", pi_name):
		return pi_name

	ref_pi = frappe.db.get_value(
		"Payment Entry Reference",
		{"parent": payment_entry, "reference_doctype": "Purchase Invoice"},
		"reference_name",
	)
	if ref_pi:
		_set_task_fields(task_name, {"custom_purchase_invoice": ref_pi})
		return ref_pi

	return frappe.db.get_value(
		"Purchase Invoice",
		{"custom_cgm_source_task": task_name, "docstatus": 1},
		"name",
		order_by="modified desc",
	)


def job_link_pi_to_task(task_name: str, purchase_invoice: str) -> None:
	"""Background: link PI to task; if already paid, link PE too."""
	try:
		link_purchase_invoice_to_task_enhanced(task_name, purchase_invoice, notify=False)
		pe_name = _find_payment_entry_for_purchase_invoice(purchase_invoice)
		if pe_name:
			job_link_pe_to_task(task_name, pe_name)
	except Exception:
		frappe.log_error(
			title="CGM link PI to task failed",
			message=f"PI {purchase_invoice} → task {task_name}",
		)


def job_link_pe_to_task(task_name: str, payment_entry: str) -> None:
	"""Background: ensure PI + PE are linked on the finance task."""
	try:
		task = frappe.get_doc("Task", task_name)
		pi_name = _resolve_purchase_invoice_for_task(task, payment_entry)
		if pi_name and task.get("custom_purchase_invoice") != pi_name:
			link_purchase_invoice_to_task_enhanced(task_name, pi_name, notify=False)
		complete_task_with_payment_enhanced(task_name, payment_entry)
	except Exception:
		frappe.log_error(
			title="CGM link PE to task failed",
			message=f"PE {payment_entry} → task {task_name}",
		)


def purchase_invoice_validate_from_task(doc, method=None):
	"""On save/submit: keep Project aligned with source finance task."""
	task_name = doc.get("custom_cgm_source_task")
	if not task_name and doc.get("remarks"):
		import re

		match = re.search(r"TASK-\d+", doc.remarks or "")
		if match:
			task_name = match.group(0)
	if not task_name or not frappe.db.exists("Task", task_name):
		return
	task = frappe.get_doc("Task", task_name)
	if not task.project:
		return
	if doc.meta.has_field("project") and not doc.project:
		doc.project = task.project
	if doc.meta.has_field("custom_cgm_source_task") and not doc.custom_cgm_source_task:
		doc.custom_cgm_source_task = task.name
	for row in doc.get("items") or []:
		if not row.project:
			row.project = task.project


def purchase_invoice_on_submit(doc, method=None) -> None:
	"""Link submitted PI to the finance task after commit (avoid submit deadlocks)."""
	task_name = doc.get("custom_cgm_source_task")
	if not task_name or not frappe.db.exists("Task", task_name):
		return
	task = frappe.get_doc("Task", task_name)
	if not is_sea_payment_task(task):
		return
	if task.get("custom_purchase_invoice") == doc.name:
		return
	_enqueue_finance_job("job_link_pi_to_task", task_name=task_name, purchase_invoice=doc.name)


def payment_entry_on_submit(doc, method=None) -> None:
	"""Link submitted PE to the finance task in a background job."""
	task_name = doc.get("custom_cgm_source_task")
	if not task_name:
		task_name = _task_from_payment_references(doc)
	if not task_name or not frappe.db.exists("Task", task_name):
		return
	task = frappe.get_doc("Task", task_name)
	if not is_sea_payment_task(task):
		return
	if task.get("custom_payment_entry") == doc.name:
		return
	_enqueue_finance_job("job_link_pe_to_task", task_name=task_name, payment_entry=doc.name)


def _task_from_payment_references(doc) -> str | None:
	for row in doc.get("references") or []:
		if row.reference_doctype != "Purchase Invoice" or not row.reference_name:
			continue
		task_name = frappe.db.get_value(
			"Purchase Invoice", row.reference_name, "custom_cgm_source_task"
		)
		if task_name:
			return task_name
	return None


def payment_entry_validate_from_task(doc, method=None):
	"""Ensure PE project / source task match the finance task or its Purchase Invoice."""
	if not doc.get("custom_cgm_source_task"):
		for row in doc.get("references") or []:
			if row.reference_doctype == "Purchase Invoice" and row.reference_name:
				task_name = frappe.db.get_value(
					"Purchase Invoice", row.reference_name, "custom_cgm_source_task"
				)
				if task_name and doc.meta.has_field("custom_cgm_source_task"):
					doc.custom_cgm_source_task = task_name
					break

	task_name = doc.get("custom_cgm_source_task")
	if task_name and frappe.db.exists("Task", task_name):
		project = frappe.db.get_value("Task", task_name, "project")
		if project and doc.meta.has_field("project") and not doc.project:
			doc.project = project


def link_purchase_invoice_to_task_enhanced(
	task_name: str, purchase_invoice: str, *, notify: bool = True
) -> dict:
	"""Link submitted PI to task and sync Project."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
		notify_finance_for_task,
	)

	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	if not purchase_invoice or not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw("Purchase Invoice not found.")

	task = frappe.get_doc("Task", task_name)
	_task_context(task)
	project = task.project

	if task.get("custom_purchase_invoice") == purchase_invoice:
		return {"task": task.name, "purchase_invoice": purchase_invoice, "project": project}

	pi_status = frappe.db.get_value("Purchase Invoice", purchase_invoice, "docstatus")
	if int(pi_status or 0) != 1:
		frappe.throw("Purchase Invoice must be submitted before linking to the task.")

	apply_project_from_task_to_purchase_invoice(purchase_invoice, task_name)
	_set_task_fields(task_name, {"custom_purchase_invoice": purchase_invoice})
	if notify:
		notify_finance_for_task(task_name)

	return {"task": task_name, "purchase_invoice": purchase_invoice, "project": project}


def complete_task_with_payment_enhanced(task_name: str, payment_entry: str) -> dict:
	"""Link submitted PE to task; require allocation against task PI; complete task."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw(f"Task {task_name} not found")
	if not payment_entry or not frappe.db.exists("Payment Entry", payment_entry):
		frappe.throw(f"Payment Entry {payment_entry} not found")

	payment_status = frappe.db.get_value("Payment Entry", payment_entry, "docstatus")
	if int(payment_status or 0) != 1:
		frappe.throw("Payment Entry must be submitted before linking it to the task.")

	task = frappe.get_doc("Task", task_name)
	_task_context(task)
	task_fields = frappe.get_meta("Task")

	if task.get("custom_payment_entry") == payment_entry:
		return {
			"task": task.name,
			"status": task.status,
			"payment_entry": payment_entry,
			"auto_completed": task.status == "Completed",
			"message": "Payment already linked to this task.",
		}

	if is_sea_payment_task(task) and task_fields.has_field("custom_purchase_invoice"):
		pi_name = _resolve_purchase_invoice_for_task(task, payment_entry)
		if not pi_name:
			frappe.throw(
				"Create and submit a Purchase Invoice from this task first, then pay from that invoice."
			)
		if task.get("custom_purchase_invoice") != pi_name:
			_set_task_fields(task.name, {"custom_purchase_invoice": pi_name})
		if not payment_entry_allocates_purchase_invoice(payment_entry, pi_name):
			frappe.throw(
				f"Payment Entry must allocate against Purchase Invoice <b>{pi_name}</b>. "
				"Use <b>Payment</b> on the Purchase Invoice (Create menu)."
			)

	pe_meta = frappe.get_meta("Payment Entry")
	pe_updates = {}
	if pe_meta.has_field("project") and task.project:
		pe_updates["project"] = task.project
	if pe_meta.has_field("custom_cgm_source_task"):
		pe_updates["custom_cgm_source_task"] = task.name
	if pe_updates:
		frappe.db.set_value("Payment Entry", payment_entry, pe_updates, update_modified=True)


	seq = int(task.get("custom_sequence_no") or 0)

	# UCR / permit finance: record PE only - complete after receipts verified.
	if is_ucr_finance_payment_task(seq) or is_permit_finance_payment_task(seq):
		if task_fields.has_field("custom_payment_entry"):
			_set_task_fields(task.name, {"custom_payment_entry": payment_entry})
		task = frappe.get_doc("Task", task.name)

		frappe.flags.cgm_skip_task_project_sync = True
		try:
			if is_permit_finance_payment_task(seq):
				apply_finance_payment_to_project_permits(task)
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
					notify_declarant_upload_permit_receipts,
					seed_finance_task_permits_from_project,
				)

				seed_finance_task_permits_from_project(task)
				sync_task_permits_to_project(task)
				notify_declarant_upload_permit_receipts(task)
				message = (
					"Payment recorded. Declarant must upload payment receipts and permit "
					"certificates on Apply for Pre-Clearance Permits; Finance must verify "
					"receipts before completing this task."
				)
			else:
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
					notify_operations_upload_ucr_receipt,
					sync_ucr_payment_to_idf_record,
				)

				sync_ucr_payment_to_idf_record(task)
				notify_operations_upload_ucr_receipt(task)
				message = (
					"Payment recorded. Declarant must upload the UCR payment receipt on "
					"<b>Create UCR (IDF)</b>; Finance verifies the receipt before completing this task."
				)
		finally:
			frappe.flags.cgm_skip_task_project_sync = False

		return {
			"task": task.name,
			"status": task.status,
			"payment_entry": payment_entry,
			"auto_completed": False,
			"message": message,
		}

	task.completed_by = frappe.session.user
	task.completed_on = now_datetime()
	task.status = "Completed"
	frappe.flags.cgm_skip_task_project_sync = True
	try:
		task.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_skip_task_project_sync = False
	apply_finance_payment_to_project_permits(task)

	return {
		"task": task.name,
		"status": task.status,
		"payment_entry": payment_entry,
		"auto_completed": True,
	}


# ==================== Journal Entry payment → task completion ====================
def journal_entry_on_submit(doc, method=None) -> None:
	"""Complete the source finance Task when its payment Journal Entry is submitted.

	The Journal Entry (created from the task's Make Payment dialog) replaces the
	old Purchase Invoice + Payment Entry completion flow.
	"""
	task_name = doc.get("custom_cgm_source_task")
	if not task_name or not frappe.db.exists("Task", task_name):
		return
	try:
		complete_task_with_journal_entry(task_name, doc.name)
	except Exception:
		frappe.log_error(
			title="CGM complete task from Journal Entry failed",
			message=f"JE {doc.name} -> task {task_name}",
		)


def journal_entry_on_cancel(doc, method=None) -> None:
	"""Unlink a cancelled payment Journal Entry from its Task and reopen the task
	if that Journal Entry had completed it."""
	task_name = doc.get("custom_cgm_source_task") or frappe.db.get_value(
		"Task", {"custom_journal_entry": doc.name}, "name"
	)
	if not task_name or not frappe.db.exists("Task", task_name):
		return
	task = frappe.get_doc("Task", task_name)
	if task.get("custom_journal_entry") != doc.name:
		return
	updates = {"custom_journal_entry": None}
	if task.status == "Completed":
		updates.update({"status": "Open", "completed_by": None, "completed_on": None})
	frappe.flags.cgm_skip_task_project_sync = True
	try:
		_set_task_fields(task.name, updates)
	finally:
		frappe.flags.cgm_skip_task_project_sync = False


@frappe.whitelist()
def complete_task_with_journal_entry(task_name: str, journal_entry: str) -> dict:
	"""Link a submitted payment Journal Entry to its finance Task and complete it.

	Mirrors complete_task_with_payment_enhanced for the Journal-Entry payment flow:
	plain finance-payment tasks complete immediately; UCR / permit finance tasks
	record the payment and wait for the declarant receipts before completing.
	"""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw(f"Task {task_name} not found")
	if not journal_entry or not frappe.db.exists("Journal Entry", journal_entry):
		frappe.throw(f"Journal Entry {journal_entry} not found")
	if int(frappe.db.get_value("Journal Entry", journal_entry, "docstatus") or 0) != 1:
		frappe.throw("Journal Entry must be submitted before completing the task.")

	task = frappe.get_doc("Task", task_name)
	task_fields = frappe.get_meta("Task")
	if task_fields.has_field("custom_journal_entry") and task.get("custom_journal_entry") != journal_entry:
		_set_task_fields(task.name, {"custom_journal_entry": journal_entry})
		task = frappe.get_doc("Task", task.name)

	seq = int(task.get("custom_sequence_no") or 0)

	# UCR / permit finance: record payment only - complete after receipts verified.
	if is_ucr_finance_payment_task(seq) or is_permit_finance_payment_task(seq):
		frappe.flags.cgm_skip_task_project_sync = True
		try:
			if is_permit_finance_payment_task(seq):
				apply_finance_payment_to_project_permits(task)
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
					notify_declarant_upload_permit_receipts,
					seed_finance_task_permits_from_project,
				)

				seed_finance_task_permits_from_project(task)
				sync_task_permits_to_project(task)
				notify_declarant_upload_permit_receipts(task)
				message = (
					"Payment recorded. Declarant must upload payment receipts and permit "
					"certificates on Apply for Pre-Clearance Permits; Finance must verify "
					"receipts before completing this task."
				)
			else:
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
					notify_operations_upload_ucr_receipt,
					sync_ucr_payment_to_idf_record,
				)

				sync_ucr_payment_to_idf_record(task)
				notify_operations_upload_ucr_receipt(task)
				message = (
					"Payment recorded. Declarant must upload the UCR payment receipt on "
					"<b>Create UCR (IDF)</b>; Finance verifies the receipt before completing this task."
				)
		finally:
			frappe.flags.cgm_skip_task_project_sync = False
		return {
			"task": task.name,
			"status": task.status,
			"journal_entry": journal_entry,
			"auto_completed": False,
			"message": message,
		}

	if task.status == "Completed":
		return {
			"task": task.name,
			"status": "Completed",
			"journal_entry": journal_entry,
			"auto_completed": True,
			"message": "Task already completed.",
		}

	task.completed_by = frappe.session.user
	task.completed_on = now_datetime()
	task.status = "Completed"
	frappe.flags.cgm_skip_task_project_sync = True
	try:
		task.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_skip_task_project_sync = False
	apply_finance_payment_to_project_permits(task)

	return {
		"task": task.name,
		"status": task.status,
		"journal_entry": journal_entry,
		"auto_completed": True,
	}


# ==================== Permit item mapping ====================

"""Map Permit Type → ERPNext Item for Purchase Invoice lines."""
from frappe.utils import cint

# Common Item name/code variants in CGM item master (longest / most specific first).
PERMIT_TYPE_ITEM_CANDIDATES: dict[str, tuple[str, ...]] = {
	"ACA": ("Aca Permit", "ACA Permit", "ACA", "Aca"),
	"DVS": ("Dvs Permit", "DVS Permit", "Dvs", "DVS"),
	"KEBS": ("Kebs Permit", "KEBS Permit", "Kebs", "KEBS"),
	"NBA": ("N.b.a", "NBA", "Nba", "N.b.a."),
	"VMD": ("Vmd Permit", "VMD Permit", "Vmd", "VMD"),
	"SCA": ("Sca Permit", "SCA Permit", "SCA", "Sca"),
	"KRPB": ("Krbp", "KRPB"),
	"Port Health": ("Port Health", "Port Healt"),
}


def _item_is_usable(item_code: str | None) -> bool:
	if not item_code or not frappe.db.exists("Item", item_code):
		return False
	disabled, is_purchase = frappe.db.get_value(
		"Item", item_code, ("disabled", "is_purchase_item")
	) or (1, 0)
	# Coerce NULL columns so a NULL `disabled` isn't read as "enabled".
	return not cint(disabled) and bool(cint(is_purchase))


def _resolve_item_code(candidates: list[str]) -> str | None:
	seen: set[str] = set()
	for raw in candidates:
		code = (raw or "").strip()
		if not code or code in seen:
			continue
		seen.add(code)

		if _item_is_usable(code):
			return code

		rows = frappe.db.sql(
			"""
			SELECT name
			FROM `tabItem`
			WHERE disabled = 0
			  AND is_purchase_item = 1
			  AND (
				LOWER(name) = LOWER(%s)
				OR LOWER(item_name) = LOWER(%s)
			  )
			ORDER BY modified DESC
			LIMIT 1
			""",
			(code, code),
			pluck=True,
		)
		if rows:
			return rows[0]

		rows = frappe.db.sql(
			"""
			SELECT name
			FROM `tabItem`
			WHERE disabled = 0
			  AND is_purchase_item = 1
			  AND LOWER(item_name) LIKE LOWER(%s)
			ORDER BY LENGTH(item_name) ASC, modified DESC
			LIMIT 1
			""",
			(f"%{code}%",),
			pluck=True,
		)
		if rows:
			return rows[0]
	return None


def _permit_type_purchase_item_field_ready() -> bool:
	"""True when purchase_item exists in meta and database (after migrate)."""
	if not frappe.db.exists("DocType", "Permit Type"):
		return False
	meta = frappe.get_meta("Permit Type")
	if not meta.has_field("purchase_item"):
		return False
	return bool(frappe.db.has_column("Permit Type", "purchase_item"))


def candidates_for_permit_type(permit_type: str) -> list[str]:
	pt = (permit_type or "").strip()
	if not pt:
		return []

	out: list[str] = []
	for value in PERMIT_TYPE_ITEM_CANDIDATES.get(pt, ()):
		out.append(value)
	out.extend((f"{pt} Permit", pt, pt.upper(), pt.title()))
	return out


def resolve_purchase_item_for_permit_type(permit_type: str) -> str | None:
	"""Return Item code for a permit type, or None if no match."""
	if not permit_type:
		return None

	if _permit_type_purchase_item_field_ready() and frappe.db.exists("Permit Type", permit_type):
		linked = frappe.db.get_value("Permit Type", permit_type, "purchase_item")
		if _item_is_usable(linked):
			return linked

	return _resolve_item_code(candidates_for_permit_type(permit_type))


def get_purchase_item_for_permit_type(permit_type: str, company: str | None = None) -> str:
	"""Item for PI line - Permit Type master, then name match, then global default."""

	item = resolve_purchase_item_for_permit_type(permit_type)
	if item:
		return item
	return get_default_purchase_item_code(company)


def seed_permit_type_purchase_items() -> list[str]:
	"""Link Permit Type records to Items where a match exists."""
	if not frappe.db.exists("DocType", "Permit Type"):
		return []

	if not _permit_type_purchase_item_field_ready():
		return []

	updated: list[str] = []
	for name in frappe.get_all("Permit Type", pluck="name"):
		if frappe.db.get_value("Permit Type", name, "purchase_item"):
			continue
		item = resolve_purchase_item_for_permit_type(name)
		if not item:
			continue
		frappe.db.set_value("Permit Type", name, "purchase_item", item, update_modified=False)
		updated.append(f"{name} → {item}")
	return updated


# ==================== Task hooks ====================


def _sea_task_seq(doc) -> int:
	return int(doc.get("custom_sequence_no") or 0)


def _is_sea_task(doc) -> bool:
	return doc.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY


def on_task_onload(doc, _method=None):
	"""Remove orphan UCR Invoice rows from DB before the form is shown (link validation runs before before_save)."""

	if doc.is_new():
		return
	if purge_invoice_rows_from_task_documents_db(doc.name):
		doc.reload()
		if _is_sea_task(doc):
			prepare_ucr_task_tables(doc)
	if _is_sea_task(doc) and is_ucr_workflow_task(_sea_task_seq(doc)):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			ensure_ucr_finance_lines_saved,
			sync_ucr_status_from_finance_to_application,
		)

		changed = ensure_ucr_finance_lines_saved(doc)
		seq = _sea_task_seq(doc)
		if is_ucr_application_task(seq):
			changed = sync_ucr_status_from_finance_to_application(doc) or changed
			if doc.status not in ("Completed", "Cancelled"):
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
					try_auto_complete_ucr_application_task,
				)

				if try_auto_complete_ucr_application_task(doc):
					changed = True
		elif is_ucr_finance_payment_task(seq) and doc.status not in ("Completed", "Cancelled"):
			if doc.project:
				from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
					copy_ucr_receipt_to_finance_task,
				)
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
					get_ucr_application_task,
					try_auto_complete_ucr_finance_task,
				)

				app_name = get_ucr_application_task(doc.project)
				if app_name:
					copy_ucr_receipt_to_finance_task(frappe.get_doc("Task", app_name))
					doc.reload()
				if try_auto_complete_ucr_finance_task(doc):
					changed = True
		if changed:
			doc.reload()

	if _is_sea_task(doc) and is_permit_finance_payment_task(_sea_task_seq(doc)):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			ensure_finance_permit_rows_saved,
		)

		if ensure_finance_permit_rows_saved(doc):
			doc.reload()

	if _is_sea_task(doc) and is_permit_application_task(_sea_task_seq(doc)):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			merge_project_permits_into_application_task,
		)

		if merge_project_permits_into_application_task(doc):
			doc.reload()

	if _is_sea_task(doc) and is_document_checkpoint_task(_sea_task_seq(doc)):
		if strip_task_documents_for_checkpoint(doc):
			frappe.flags.cgm_strip_checkpoint_documents = True
			try:
				doc.save(ignore_permissions=True)
			finally:
				frappe.flags.cgm_strip_checkpoint_documents = False
			doc.reload()

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_container_updates import (
		on_task_onload_container_updates,
	)

	on_task_onload_container_updates(doc)


def before_task_save(doc, _method=None):
	"""Pre-fill required document rows while the task is still open."""
	if not _is_sea_task(doc):
		return
	if doc.status in ("Completed", "Cancelled"):
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		enforce_receipt_verified_permission,
		seed_finance_task_permits_from_project,
	)

	migrate_invoice_attachments_from_documents(doc)
	prepare_ucr_task_tables(doc)
	seed_required_task_document_rows(doc)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		enforce_ucr_finance_field_permissions,
		sync_ucr_payment_to_idf_record,
	)

	seed_finance_task_permits_from_project(doc)
	normalize_finance_line_verification(doc)
	enforce_receipt_verified_permission(doc)
	enforce_ucr_finance_field_permissions(doc)
	if doc.status != "Cancelled":
		sync_ucr_payment_to_idf_record(doc)


def on_task_update(doc, _method=None):
	seq = _sea_task_seq(doc)

	if _is_sea_task(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_container_updates import (
			apply_container_updates_from_task,
		)

		apply_container_updates_from_task(doc)

	if _is_sea_task(doc) and is_ucr_application_task(seq) and doc.status not in (
		"Completed",
		"Cancelled",
	):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			auto_submit_ucr_invoice_to_finance_if_needed,
			handle_ucr_application_receipt_upload,
		)

		auto_submit_ucr_invoice_to_finance_if_needed(doc)
		handle_ucr_application_receipt_upload(doc)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			try_auto_complete_ucr_application_task,
		)

		try_auto_complete_ucr_application_task(doc)

	if (
		_is_sea_task(doc)
		and is_ucr_finance_payment_task(seq)
		and doc.status not in ("Completed", "Cancelled")
	):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			try_auto_complete_ucr_finance_task,
		)

		try_auto_complete_ucr_finance_task(doc)

	if (
		_is_sea_task(doc)
		and is_permit_finance_payment_task(seq)
		and doc.status not in ("Completed", "Cancelled")
		and not frappe.flags.get("cgm_permit_finance_completing")
	):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			try_auto_complete_permit_finance_task,
		)

		try_auto_complete_permit_finance_task(doc)

	if (
		_is_sea_task(doc)
		and is_permit_application_task(seq)
		and doc.status not in ("Completed", "Cancelled")
	):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			auto_submit_permit_invoices_to_finance_if_needed,
		)

		auto_submit_permit_invoices_to_finance_if_needed(doc)

	if frappe.flags.get("cgm_skip_task_project_sync"):
		return
	if doc.get("project"):
		refresh_project_documents(doc.project)
		sync_task_permits_to_project(doc)
		if _is_sea_task(doc):
			if is_permit_application_task(seq):
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
					get_permit_finance_task,
					sync_permit_invoices_to_finance_task,
				)

				fin_name = get_permit_finance_task(doc.project, seq)
				if fin_name and not frappe.flags.get("cgm_permit_finance_completing"):
					sync_permit_invoices_to_finance_task(
						frappe.get_doc("Task", fin_name), save=True
					)
			from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
				sync_project_shipment_status_from_tasks,
			)

			sync_project_shipment_status_from_tasks(doc.project)
	prev = doc.get_doc_before_save()
	if (
		_is_sea_task(doc)
		and doc.status == "Completed"
		and (not prev or prev.status != "Completed")
		and doc.project
	):
		from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
			handle_sea_task_container_event,
		)

		handle_sea_task_container_event(doc.project, seq, task_doc=doc)

	if doc.status == "Completed" and (not prev or prev.status != "Completed"):
		apply_finance_payment_to_project_permits(doc)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			close_permit_application_when_finance_done,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			close_ucr_application_when_finance_done,
		)

		close_permit_application_when_finance_done(doc)
		close_ucr_application_when_finance_done(doc)


def validate_task_completion_requirements(doc, _method=None):
	"""Task → Completed only when documents, permits, and payments are satisfied."""
	prev = doc.get_doc_before_save()
	if doc.status != "Completed":
		return
	if prev and prev.status == "Completed":
		return

	seq = _sea_task_seq(doc)
	if (
		_is_sea_task(doc)
		and frappe.flags.get("cgm_auto_completing_sea_task")
		and (
			is_auto_complete_task(seq)
			or is_ucr_application_task(seq)
			or is_ucr_finance_payment_task(seq)
		)
	):
		return

	if _is_sea_task(doc) and is_auto_complete_task(seq):
		return

	if _is_sea_task(doc):
		if seq > 1:
			from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
				get_incomplete_sea_tasks,
			)

			# Finance payment steps don't block downstream tasks — Finance pays in
			# parallel; finance steps are still enforced at final project closure.
			incomplete = get_incomplete_sea_tasks(doc.project, seq, exclude_finance=True)
			if incomplete:
				prev_task = incomplete[0]
				frappe.throw(
					f"Complete prior sea tasks in order first. Next open: "
					f"<b>Task {prev_task.seq}: {prev_task.subject}</b> ({prev_task.status or 'Open'})."
				)
		validate_sea_task_can_complete(doc)

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_container_updates import (
		validate_task_19_container_updates,
	)

	validate_task_19_container_updates(doc)


# ==================== CGMTask override ====================

from erpnext.projects.doctype.task.task import Task


class CGMTask(Task):
	def _save(self, ignore_permissions=None, ignore_version=None):
		self._strip_legacy_invoice_clearance_documents()
		return super()._save(
			ignore_permissions=ignore_permissions,
			ignore_version=ignore_version,
		)

	def insert(
		self,
		ignore_permissions=None,
		ignore_links=None,
		ignore_if_duplicate=False,
		ignore_mandatory=None,
		set_name=None,
		set_child_names=True,
	):
		self._strip_legacy_invoice_clearance_documents()
		return super().insert(
			ignore_permissions=ignore_permissions,
			ignore_links=ignore_links,
			ignore_if_duplicate=ignore_if_duplicate,
			ignore_mandatory=ignore_mandatory,
			set_name=set_name,
			set_child_names=set_child_names,
		)

	def _strip_legacy_invoice_clearance_documents(self) -> None:
		if self.name and not self.get("__islocal"):
			purge_invoice_rows_from_task_documents_db(self.name)
		migrate_invoice_attachments_from_documents(self)
		remove_invoice_rows_from_task_documents(self)
