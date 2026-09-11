"""Task hooks, requirements, finance, and completion rules."""
from __future__ import annotations

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	PERMIT_REGISTER_FIELD,
	PRE_CLEARANCE_STAGE,
	TASK_DOCUMENTS_FIELD,
	TASK_FINANCE_FIELD,
	TASK_PERMITS_FIELD,
	TRANSPORT_CONTAINER_STEPS,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.documents import refresh_project_documents


def task_sequence(task) -> int:
	return int(task.get("custom_sequence_no") or 0)


def get_task_name_by_sequence(project: str, sequence_no: int) -> str | None:
	if not project or not sequence_no:
		return None
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		sea_import_flow_keys,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks import (
		get_project_workflow_flow_keys,
	)

	keys: list[str] = []
	seen: set[str] = set()
	for flow_key in (*sea_import_flow_keys(), *get_project_workflow_flow_keys(project)):
		value = (flow_key or "").strip()
		if value and value not in seen:
			seen.add(value)
			keys.append(value)

	for flow_key in keys:
		name = frappe.db.get_value(
			"Task",
			{
				"project": project,
				"custom_task_flow_key": flow_key,
				"custom_sequence_no": sequence_no,
			},
			"name",
		)
		if name:
			return name

	# Last resort: sequence alone on this project (single-plan projects).
	return frappe.db.get_value(
		"Task",
		{"project": project, "custom_sequence_no": sequence_no},
		"name",
	)


SUPPLIER_INVOICE_CODE = "SUP_INV"


def is_sea_finance_payment_task(task) -> bool:
	"""Task is a finance payment step, by its Task Role stamp."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		get_task_behaviour,
	)
	behaviour = get_task_behaviour(task)
	return behaviour.is_finance_payment or behaviour.is_permit_finance


def enforce_client_paid_confirmation(task) -> None:
	"""Only the configured role group may confirm a client-paid fee; stamp who confirmed it."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CLIENT_PAID_BY_FIELD,
		CLIENT_PAID_FIELD,
		CLIENT_PAID_ON_FIELD,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		ACTION_CONFIRM_CLIENT_PAID,
		flow_for_task,
		throw_unless_responsibility,
	)

	if not task.meta.has_field(CLIENT_PAID_FIELD):
		return
	prev = task.get_doc_before_save()
	was_set = bool(prev.get(CLIENT_PAID_FIELD)) if prev else False
	is_set = bool(task.get(CLIENT_PAID_FIELD))
	if was_set == is_set:
		return

	if is_set and not is_sea_finance_payment_task(task):
		frappe.throw(
			"<b>Client will pay</b> applies only to finance payment tasks."
		)
	flow = flow_for_task(task) or "Permit"
	throw_unless_responsibility(
		flow, ACTION_CONFIRM_CLIENT_PAID, label="select Client will pay"
	)

	if is_set:
		if task.meta.has_field(CLIENT_PAID_BY_FIELD):
			task.set(CLIENT_PAID_BY_FIELD, frappe.session.user)
		if task.meta.has_field(CLIENT_PAID_ON_FIELD):
			task.set(CLIENT_PAID_ON_FIELD, now_datetime())
		return
	for field in (CLIENT_PAID_BY_FIELD, CLIENT_PAID_ON_FIELD):
		if task.meta.has_field(field):
			task.set(field, None)


def paired_application_task_for_finance_task(task) -> str | None:
	"""Application/declarant task that pairs with a finance payment task."""
	if not task.project:
		return None
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		get_application_task,
		profile_for_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_permit_finance,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		get_permit_application_task_for_finance,
	)

	if task_is_permit_finance(task):
		return get_permit_application_task_for_finance(task)
	profile = profile_for_task(task)
	if profile:
		return get_application_task(task.project, profile)
	return None


def sync_client_paid_to_application_task(task) -> str | None:
	"""Mirror Finance's Client will pay flag onto the paired application task.

	Read-only there — it tells the declarant that Finance chose the client-pays
	path (no company Journal Entry); verify + client receipt still happen on Finance.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CLIENT_PAID_BY_FIELD,
		CLIENT_PAID_FIELD,
		CLIENT_PAID_ON_FIELD,
	)

	if not task.meta.has_field(CLIENT_PAID_FIELD):
		return None
	if not is_sea_finance_payment_task(task):
		return None
	app_name = paired_application_task_for_finance_task(task)
	if not app_name:
		return None

	# Prefer task-level flag; also treat any invoice-line Client will pay as set.
	client_paid = bool(task.get(CLIENT_PAID_FIELD))
	if not client_paid:
		try:
			from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
				finance_has_client_paid_invoice_line,
				profile_for_task,
			)

			profile = profile_for_task(task)
			if profile and finance_has_client_paid_invoice_line(task, profile):
				client_paid = True
		except Exception:
			pass

	values = {CLIENT_PAID_FIELD: 1 if client_paid else 0}
	meta = frappe.get_meta("Task")
	for field in (CLIENT_PAID_BY_FIELD, CLIENT_PAID_ON_FIELD):
		if meta.has_field(field):
			values[field] = task.get(field) if values[CLIENT_PAID_FIELD] else None
	current = frappe.db.get_value("Task", app_name, list(values), as_dict=True) or {}

	def _same(a, b) -> bool:
		# Datetime stamps come back typed from the DB but as strings off the form.
		return (str(a) if a is not None else None) == (str(b) if b is not None else None)

	if all(_same(current.get(field), value) for field, value in values.items()):
		return None

	frappe.db.set_value("Task", app_name, values, update_modified=False)
	frappe.clear_document_cache("Task", app_name)
	frappe.publish_realtime(
		"cgm_task_status_changed",
		{"task": app_name, "project": task.project},
	)
	return app_name


@frappe.whitelist()
def get_sea_task_ui_sequences() -> dict:
	"""Task form config: the user's permissions and the Finance department.

	It used to carry Sea Import step-number lists too; the form now reads each
	task's Task Role stamps instead.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
		get_task_form_permissions,
	)

	return {
		"permissions": get_task_form_permissions(),
		"finance_department": frappe.db.get_single_value(
			"CGM Shipping Settings", "custom_finance_department"
		)
		if frappe.db.exists("DocType", "CGM Shipping Settings")
		else None,
	}


# ==================== Task finance lines ====================

"""Task Finance Lines - invoices and receipts (separate from clearance documents)."""
from frappe.utils import cint, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_DOCUMENTS_FIELD

LINE_INVOICE = "Invoice"
LINE_RECEIPT = "Receipt"
PAYMENT_UCR = "UCR"
PAYMENT_ENTRY_SLIP = "ENTRY_SLIP"

UCR_INVOICE_LABEL = "UCR Invoice"
UCR_RECEIPT_LABEL = "UCR Receipt"
ENTRY_SLIP_INVOICE_LABEL = "Entry Slip Invoice"
ENTRY_SLIP_RECEIPT_LABEL = "Entry Slip Receipt"

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
	if not frappe.db.table_exists("Task Finance Line"):
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
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_application,
	)

	if not task_is_ucr_application(task):
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
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
		prepare_application_task_tables,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_workflow,
	)

	if not task_is_ucr_workflow(task):
		return
	prepare_application_task_tables(task, APPLICATION_FINANCE_PROFILES["UCR Application"])


def prepare_entry_task_tables(task) -> None:
	"""Entry tasks: finance lines for Entry Slip invoice/receipt; ENTRY cert on clearance docs."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
		prepare_application_task_tables,
	)

	prepare_application_task_tables(task, APPLICATION_FINANCE_PROFILES["Entry Application"])


def prepare_application_finance_task_tables(task) -> None:
	"""Seed finance lines for this task's application/finance profile only."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		prepare_application_task_tables,
		profile_for_task,
	)

	profile = profile_for_task(task)
	if profile:
		prepare_application_task_tables(task, profile)


def _find_line(task, line_type: str, payment_item: str = PAYMENT_UCR):
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if row.line_type == line_type and (row.payment_item or PAYMENT_UCR) == payment_item:
			return row
	return None


def _ensure_line(task, line_type: str, label: str, payment_item: str = PAYMENT_UCR):
	from cgm_shipping.cgm_worldwide_shipping.customizations.clearance_charge_item import (
		build_finance_line_payload,
		get_clearance_charge_item,
		task_finance_line_has_charge_item,
	)

	row = _find_line(task, line_type, payment_item)
	if row:
		if not row.line_label:
			row.line_label = label
		if not row.get("charge_item") and task_finance_line_has_charge_item():
			charge_item = get_clearance_charge_item(
				payment_item, line_type, fallback_label=label
			)
			if charge_item:
				row.charge_item = charge_item
		if (
			line_type == LINE_INVOICE
			and task_finance_line_has_item_code()
			and not row.get("item_code")
		):
			row.item_code = get_purchase_item_for_payment_item(payment_item, task.company)
		return row
	task.append(
		TASK_FINANCE_FIELD,
		build_finance_line_payload(
			line_type,
			payment_item,
			fallback_label=label,
			company=task.company,
		),
	)
	return task.get(TASK_FINANCE_FIELD)[-1]


def seed_ucr_finance_lines(task) -> None:
	"""Pre-fill UCR Invoice + UCR Receipt rows on UCR tasks."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_finance,
		task_is_ucr_workflow,
	)

	if not task_has_finance_table(task):
		return
	if not task_is_ucr_workflow(task):
		return

	_ensure_line(task, LINE_INVOICE, UCR_INVOICE_LABEL)
	_ensure_line(task, LINE_RECEIPT, UCR_RECEIPT_LABEL)
	if task_is_ucr_finance(task):
		copy_ucr_invoice_to_finance_task(task)


def ensure_ucr_finance_lines_saved(task) -> bool:
	"""Persist missing UCR Invoice / UCR Receipt rows on Create UCR and Finance pays UCR."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_workflow,
	)

	if not task_has_finance_table(task):
		return False
	if not task_is_ucr_workflow(task):
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
			preserve_completed_status_against_stale_save(task)
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_ensuring_ucr_finance_lines = False
		return True
	return False


def migrate_invoice_attachments_from_documents(task) -> None:
	"""Move legacy invoice attachments from Clearance Documents → finance lines."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_workflow,
	)

	if not task_has_finance_table(task):
		return
	if not task_is_ucr_workflow(task):
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
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_finance,
	)

	if not task_is_ucr_finance(finance_task) or not finance_task.project:
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
	if task_finance_line_has_item_code():
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			_sync_purchase_item_from_application_line,
		)

		_sync_purchase_item_from_application_line(
			fin_line, app_line, finance_task, PAYMENT_UCR
		)


def ucr_payment_made_for_project(project: str) -> bool:
	"""True when Finance pays UCR has recorded payment (Journal Entry or submitted PE)."""
	if not project:
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		get_ucr_finance_task,
		task_has_recorded_payment,
	)

	finance_name = get_ucr_finance_task(project)
	if not finance_name:
		return False
	return task_has_recorded_payment(frappe.get_doc("Task", finance_name))


def copy_ucr_receipt_to_finance_task(application_task) -> str | None:
	"""Copy declarant UCR receipt onto Finance pays UCR. Returns finance task name."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_application,
	)

	if not task_is_ucr_application(application_task) or not application_task.project:
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

	# Do not overwrite a receipt Finance already uploaded on the finance task.
	if fin_rec.attachment:
		return finance_name

	updates = {"attachment": app_rec.attachment}
	frappe.db.set_value("Task Finance Line", fin_rec.name, updates, update_modified=False)

	return finance_name


def copy_ucr_receipt_to_application_task(finance_task) -> str | None:
	"""Mirror Finance-uploaded UCR receipt onto Create UCR for visibility."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_finance,
	)

	if not task_is_ucr_finance(finance_task) or not finance_task.project:
		return None

	fin_rec = _find_line(finance_task, LINE_RECEIPT)
	if not fin_rec or not fin_rec.attachment:
		return None

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		get_ucr_create_task,
	)

	app_name = get_ucr_create_task(finance_task.project)
	if not app_name:
		return None

	app = frappe.get_doc("Task", app_name)
	seed_ucr_finance_lines(app)
	app_rec = _find_line(app, LINE_RECEIPT)
	if not app_rec:
		return None

	if not app_rec.name:
		frappe.flags.cgm_syncing_ucr_receipt = True
		try:
			app.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_ucr_receipt = False
		app_rec = _find_line(frappe.get_doc("Task", app_name), LINE_RECEIPT)
		if not app_rec:
			return None

	if app_rec.attachment == fin_rec.attachment and cint(app_rec.verified) == cint(fin_rec.verified):
		return app_name

	updates = {"attachment": fin_rec.attachment}
	if cint(fin_rec.verified):
		updates["verified"] = 1
		if fin_rec.verified_by:
			updates["verified_by"] = fin_rec.verified_by
		if fin_rec.verified_on:
			updates["verified_on"] = fin_rec.verified_on
	frappe.db.set_value("Task Finance Line", app_rec.name, updates, update_modified=False)
	if cint(fin_rec.verified) and frappe.get_meta("Task").has_field("custom_ucr_receipt_verified"):
		frappe.db.set_value("Task", app_name, "custom_ucr_receipt_verified", 1, update_modified=False)
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
	return bool(line and line.attachment and line.verified)


def clear_verification_without_attachment(task) -> bool:
	"""Verified-by-Finance is meaningless once the file is gone. Persist the fix."""
	if not task_has_finance_table(task):
		return False
	changed = False
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if row.line_type != LINE_RECEIPT:
			continue
		if row.attachment or not (cint(row.verified) or row.verified_by or row.verified_on):
			continue
		row.verified = 0
		row.verified_by = None
		row.verified_on = None
		if row.name:
			frappe.db.set_value(
				"Task Finance Line",
				row.name,
				{"verified": 0, "verified_by": None, "verified_on": None},
				update_modified=False,
			)
		changed = True
	if changed and task.meta.has_field("custom_ucr_receipt_verified") and task.get(
		"custom_ucr_receipt_verified"
	):
		task.custom_ucr_receipt_verified = 0
		if task.name:
			frappe.db.set_value(
				"Task", task.name, "custom_ucr_receipt_verified", 0, update_modified=False
			)
	return changed


def normalize_finance_line_verification(task) -> None:
	"""Set verified_by / verified_on when Finance ticks Verified."""
	if not task_has_finance_table(task):
		return
	clear_verification_without_attachment(task)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_finance,
	)

	is_ucr_finance = task_is_ucr_finance(task)
	# Finance upload of the UCR receipt is confirmation - auto-stamp verified.
	if is_ucr_finance:
		rec = get_ucr_receipt_line(task)
		if rec and rec.attachment and not cint(rec.verified):
			rec.verified = 1
			rec.verified_by = rec.verified_by or frappe.session.user
			rec.verified_on = rec.verified_on or now_datetime()
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if row.verified and row.attachment:
			if not row.verified_by:
				row.verified_by = frappe.session.user
			if not row.verified_on:
				row.verified_on = now_datetime()
		elif not row.attachment or not row.verified:
			row.verified = 0 if not row.attachment else row.verified
			if not row.verified:
				row.verified_by = None
				row.verified_on = None

	if is_ucr_finance:
		inv = get_ucr_invoice_line(task)
		rec = get_ucr_receipt_line(task)
		if inv and inv.verified and task.meta.has_field("custom_ucr_invoice_verified"):
			task.custom_ucr_invoice_verified = 1
		if rec and rec.attachment and rec.verified and task.meta.has_field("custom_ucr_receipt_verified"):
			task.custom_ucr_receipt_verified = 1
		elif task.meta.has_field("custom_ucr_receipt_verified"):
			task.custom_ucr_receipt_verified = 0


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
	"""Only the configured role group may verify / attach UCR finance lines."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		ACTION_UPLOAD_RECEIPT,
		ACTION_VERIFY_INVOICE,
		FLOW_UCR,
		user_has_responsibility,
	)

	if frappe.session.user == "Administrator":
		return
	if frappe.flags.get("cgm_syncing_ucr_receipt") or frappe.flags.get("cgm_ensuring_ucr_finance_lines"):
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_workflow,
	)

	if not task_is_ucr_workflow(task) or not task_has_finance_table(task):
		return

	can_verify = user_has_responsibility(FLOW_UCR, ACTION_VERIFY_INVOICE)
	can_receipt = user_has_responsibility(FLOW_UCR, ACTION_UPLOAD_RECEIPT)

	for row in task.get(TASK_FINANCE_FIELD) or []:
		if row.verified and not can_verify and _finance_line_verified_changed(task, row):
			frappe.throw(
				f"Only the configured <b>Verify Invoice</b> role group can verify "
				f"<b>{row.line_label or 'finance line'}</b> "
				"(CGM Shipping Settings → Document responsibilities)."
			)
		if not row.verified and not can_verify and _finance_line_verified_changed(task, row):
			# Declarant must not uncheck Finance verification synced from Finance pays UCR.
			prev = task.get_doc_before_save()
			prev_row = _find_line_in_task(prev, row.line_type, row.payment_item or PAYMENT_UCR)
			if prev_row and cint(prev_row.verified):
				frappe.throw(
					f"<b>{row.line_label or 'Finance line'}</b> is verified and cannot be changed here."
				)
		if row.line_type != LINE_RECEIPT or not row.attachment:
			continue
		if frappe.flags.get("cgm_syncing_ucr_receipt"):
			continue
		prev = task.get_doc_before_save()
		prev_rec = get_ucr_receipt_line(prev) if prev else None
		prev_attachment = prev_rec.attachment if prev_rec else None
		# Keep existing attachments (open projects that used the old handoff).
		if row.attachment == prev_attachment:
			continue
		if task_is_ucr_workflow(task):
			if not can_receipt:
				frappe.throw(
					"Only the configured <b>Upload Receipt</b> role group can attach the "
					"<b>UCR Receipt</b> (CGM Shipping Settings → Document responsibilities)."
				)
			if task.project and not ucr_payment_made_for_project(task.project):
				frappe.throw(
					"Record payment before uploading the <b>UCR Receipt</b>."
				)


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
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_finance,
	)

	if task.status == "Completed" and task_is_ucr_finance(task):
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

	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		IDF_CERTIFICATE_CODES,
	)

	cert_url = None
	for row in task.get("custom_task_documents") or []:
		code = get_document_type_code(row.document_type)
		if code in IDF_CERTIFICATE_CODES and row.attachment:
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
	"""Mirror one UCR finance line's verification from the UCR finance task onto the
	matching line + flag on the UCR application task. Shared by invoice/receipt."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_finance,
	)

	if (
		not task_is_ucr_finance(finance_task)
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
	if not fin_line or not fin_line.verified or not fin_line.attachment:
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
	if (fin_line.attachment or "") != (
		frappe.db.get_value("Task Finance Line", app_line_name, "attachment") or ""
	):
		frappe.db.set_value(
			"Task Finance Line",
			app_line_name,
			"attachment",
			fin_line.attachment,
			update_modified=False,
		)
		changed = True
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
	"""Mirror invoice verification (primary + amendments) from Finance pays UCR → Create UCR."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
		sync_invoice_verification_to_application_task,
	)

	changed = sync_invoice_verification_to_application_task(
		finance_task, APPLICATION_FINANCE_PROFILES["UCR Application"]
	)
	if changed and finance_task.project:
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			auto_complete_ucr_application_for_project,
		)

		auto_complete_ucr_application_for_project(finance_task.project)
	return changed


def sync_ucr_receipt_verification_to_application_task(finance_task) -> bool:
	"""Mirror receipt verification from the UCR finance task to the UCR application task."""
	return _sync_ucr_line_verification_to_application(
		finance_task, get_ucr_receipt_line, LINE_RECEIPT, "custom_ucr_receipt_verified"
	)


def sync_ucr_status_from_finance_to_application(application_task) -> bool:
	"""Pull invoice + receipt verification from Finance pays UCR when opening Create UCR."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_application,
	)

	if not task_is_ucr_application(application_task) or not application_task.project:
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
	"DELIVERY_NOTE": {
		"category": "Transport",
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


def normalize_document_type_key(value: str | None) -> str:
	"""Alphanumeric-only key so 'IDF CERT' and 'IDF_CERT' match."""
	if not value:
		return ""
	return "".join(ch for ch in str(value).upper() if ch.isalnum())


def document_type_match_tokens(document_type_link: str | None) -> set[str]:
	"""Normalized identifiers for a Document Type (link name + code).

	Settings often store short codes like DO while the master may use a longer
	code (e.g. Delivery Order) with name DO — both must count as the same type.
	Template stamps may also use spaces ('IDF CERT') while the master uses
	underscores ('IDF_CERT').
	"""
	tokens: set[str] = set()
	if not document_type_link:
		return tokens
	link = str(document_type_link).strip()
	if not link:
		return tokens
	tokens.add(link.upper())
	compact = normalize_document_type_key(link)
	if compact:
		tokens.add(compact)
	code = get_document_type_code(link)
	if code and str(code).strip():
		tokens.add(str(code).strip().upper())
		compact_code = normalize_document_type_key(code)
		if compact_code:
			tokens.add(compact_code)
	return tokens


def attached_document_codes(task) -> set[str]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import primary_attachment

	codes: set[str] = set()
	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		if not primary_attachment(row):
			continue
		# Include name and code so settings "DO" matches Document Type code "Delivery Order".
		codes |= document_type_match_tokens(row.document_type)
	return codes


def required_document_code_is_attached(required_code: str, attached: set[str]) -> bool:
	"""True when an attached Task Document satisfies a settings Document requirement."""
	req = (required_code or "").strip().upper()
	if not req:
		return True
	if req in attached:
		return True
	compact = normalize_document_type_key(req)
	if compact and compact in attached:
		return True
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		get_document_type_link_name,
	)

	dt_name = get_document_type_link_name(required_code)
	if not dt_name:
		return False
	return bool(document_type_match_tokens(dt_name) & attached)


def strip_task_documents_for_checkpoint(task) -> bool:
	"""Legacy no-op — checkpoint tasks now carry versioned document rows."""
	return False


def seed_checkpoint_task_documents(task) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		seed_checkpoint_task_documents_from_project,
	)

	return seed_checkpoint_task_documents_from_project(task)


def parse_required_document_types(value: str | None) -> list[str]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
		parse_required_document_types as _parse,
	)

	return _parse(value)


def get_stamped_required_document_types(task) -> list[str]:
	if not task or not getattr(task, "meta", None) or not task.meta.has_field(
		"custom_required_document_types"
	):
		return []
	return parse_required_document_types(task.get("custom_required_document_types"))


def get_template_task_item(task) -> dict | None:
	"""CGM Task Template row for this task (flow_key + sequence), including extends_template."""
	flow_key = (task.get("custom_task_flow_key") or "").strip()
	seq = int(task.get("custom_sequence_no") or 0)
	if not flow_key or not seq or not frappe.db.exists("CGM Task Template", flow_key):
		return None
	from cgm_shipping.cgm_worldwide_shipping.task_engine import _collect_items

	template = frappe.get_doc("CGM Task Template", flow_key)
	by_seq = {int(i["sequence_no"]): i for i in _collect_items(template)}
	return by_seq.get(seq)


def get_template_required_document_types(task) -> list[str]:
	item = get_template_task_item(task)
	if not item:
		return []
	return item.get("required_document_type_names") or []


def get_template_required_document_types_raw(task) -> str:
	from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
		serialize_required_document_types,
	)

	return serialize_required_document_types(get_template_required_document_types(task))


def get_effective_required_document_types(task) -> list[str]:
	"""Stamp on Task first; otherwise live CGM Task Template row."""
	stamped = get_stamped_required_document_types(task)
	if stamped:
		return stamped
	return get_template_required_document_types(task)


def resolve_required_document_type_name(token: str) -> str | None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
		resolve_required_document_type_name as _resolve,
	)

	return _resolve(token)


def sync_task_required_document_stamp(task) -> bool:
	"""Copy Required Document Types from template onto Task when stamp is still empty."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
		normalize_required_document_type_stamp,
	)

	if not task.meta.has_field("custom_required_document_types"):
		return False
	stamp = (task.get("custom_required_document_types") or "").strip()
	if stamp:
		normalized = normalize_required_document_type_stamp(stamp)
		if normalized and normalized != stamp:
			if not task.is_new() and task.name:
				frappe.db.set_value(
					"Task",
					task.name,
					"custom_required_document_types",
					normalized,
					update_modified=False,
				)
			task.custom_required_document_types = normalized
			return True
		return False
	raw = get_template_required_document_types_raw(task)
	if not raw:
		return False
	raw = normalize_required_document_type_stamp(raw) or raw
	if not task.is_new() and task.name:
		frappe.db.set_value(
			"Task",
			task.name,
			"custom_required_document_types",
			raw,
			update_modified=False,
		)
	task.custom_required_document_types = raw
	return True


def _required_document_type_names(task, required: list[str] | None = None) -> list[str]:
	tokens = required if required is not None else get_effective_required_document_types(task)
	names = []
	for token in tokens:
		dt_name = resolve_required_document_type_name(token)
		if dt_name:
			names.append(dt_name)
	return names


def seed_stamped_required_document_rows(task, required: list[str] | None = None) -> bool:
	"""Prefill Task Documents from template Required Document Types. Returns True if rows added."""
	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return False
	tokens = required if required is not None else get_effective_required_document_types(task)
	if not tokens:
		return False
	existing_types = {
		row.document_type for row in task.get(TASK_DOCUMENTS_FIELD) or [] if row.document_type
	}
	added = False
	for token in tokens:
		dt_name = resolve_required_document_type_name(token)
		if not dt_name or dt_name in existing_types:
			continue
		task.append(
			TASK_DOCUMENTS_FIELD,
			{"document_type": dt_name, "status": "Missing"},
		)
		existing_types.add(dt_name)
		added = True
	return added


def ensure_stamped_required_documents_saved(task) -> bool:
	"""Persist required Task Document rows on form open without a full Task.save().

	Returns True when the in-memory task should be reloaded for Desk.
	"""
	if task.is_new() or not task.name or not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return False
	sync_task_required_document_stamp(task)
	required = get_effective_required_document_types(task)
	if not required:
		return False

	# DB may already have the rows even if this form session is stale.
	existing_db = {
		r.document_type
		for r in frappe.get_all(
			"Shipment Document",
			filters={"parent": task.name, "parenttype": "Task", "parentfield": TASK_DOCUMENTS_FIELD},
			fields=["document_type"],
		)
		if r.document_type
	}
	required_names = _required_document_type_names(task, required)
	missing = [n for n in required_names if n not in existing_db]
	if not missing:
		# Still hydrate in-memory if form has no typed rows yet.
		return seed_stamped_required_document_rows(task, required)

	seed_stamped_required_document_rows(task, required)
	max_idx = cint(
		frappe.db.sql(
			"""
			select max(idx) from `tabShipment Document`
			where parent=%s and parenttype='Task' and parentfield=%s
			""",
			(task.name, TASK_DOCUMENTS_FIELD),
		)[0][0]
		or 0
	)
	for dt_name in missing:
		max_idx += 1
		child = frappe.get_doc(
			{
				"doctype": "Shipment Document",
				"parent": task.name,
				"parenttype": "Task",
				"parentfield": TASK_DOCUMENTS_FIELD,
				"document_type": dt_name,
				"status": "Missing",
				"idx": max_idx,
			}
		)
		child.insert(ignore_permissions=True)
	frappe.clear_document_cache("Task", task.name)
	return True


def stamped_required_document_types_attached(task) -> bool:
	"""True when every required Document Type has a primary attachment."""
	required = get_effective_required_document_types(task)
	if not required:
		return True
	attached = attached_document_codes(task)
	for token in required:
		if required_document_code_is_attached(token, attached):
			continue
		dt_name = resolve_required_document_type_name(token)
		if dt_name and required_document_code_is_attached(dt_name, attached):
			continue
		return False
	return True


def purge_stray_task_document_rows(task) -> bool:
	"""Remove project intake rows wrongly copied onto non-Document tasks (legacy seq seeding).

	Does not remove user-selected clearance documents (Entry, exit, c2, etc.) — those stay
	on Task Documents; Required Document Types only gate completion.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		DOCUMENT_ROLES,
		get_task_behaviour,
	)

	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return False
	if get_task_behaviour(task).role in DOCUMENT_ROLES:
		return False

	changed = False
	for row in list(task.get(TASK_DOCUMENTS_FIELD) or []):
		if not _is_stray_intake_document_row(row.document_type):
			continue
		task.remove(row)
		changed = True
	return changed


def _is_stray_intake_document_row(document_type: str | None) -> bool:
	"""True for checkpoint/intake docs (BL, COO, …) that must not sit on finance/app tasks."""
	if not document_type:
		return False
	token = (document_type or "").strip().upper()
	stray = {"BL", "COO", "COA", "CI", "PKL", "COC"}
	if token in stray:
		return True
	code = (get_document_type_code(document_type) or "").strip().upper()
	return code in stray


def purge_unrequired_task_document_rows(task) -> bool:
	"""Strip invoice rows and legacy intake copies from Task Documents.

	User-added document rows are kept. Template Required Document Types only gate
	completion via validate_required_documents — they do not restrict the table.
	"""
	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return False
	before = len(task.get(TASK_DOCUMENTS_FIELD) or [])
	remove_invoice_rows_from_task_documents(task)
	purge_stray_task_document_rows(task)
	return len(task.get(TASK_DOCUMENTS_FIELD) or []) != before


def seed_required_task_document_rows(task) -> None:
	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_document_checkpoint,
	)

	if task_is_document_checkpoint(task):
		seed_checkpoint_task_documents(task)
	else:
		seed_stamped_required_document_rows(task)


def validate_sea_task_can_complete(task) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_auto_complete,
		task_is_document_checkpoint,
		task_is_entry_application,
		task_is_entry_finance,
		task_is_kpa_application,
		task_is_kpa_finance,
		task_is_permit_application,
		task_is_permit_finance,
		task_is_shipping_line_application,
		task_is_shipping_line_finance,
		task_is_ucr_application,
		task_is_ucr_finance,
		uses_clearance_behaviour,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		is_sea_import_task,
	)

	has_stamp = bool(get_stamped_required_document_types(task))
	if not is_sea_import_task(task) and not uses_clearance_behaviour(task) and not has_stamp:
		return
	if frappe.flags.get("cgm_auto_completing_sea_task"):
		return

	seq = int(task.get("custom_sequence_no") or 0)
	if task_is_auto_complete(task):
		return

	seed_required_task_document_rows(task)
	# Template-stamped Document Types always gate Complete (any mode). The Settings
	# evidence codes, Light Proof and field clearance are keyed by Sea Import step
	# numbers, so only Sea Import tasks use them.
	sea_import = is_sea_import_task(task)
	validate_required_documents(task, seq if sea_import else 0)
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CONTAINER_STEP_FIELD_CLEARANCE,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
		container_step_for_task,
	)

	if task_is_permit_application(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			validate_permit_application_can_complete,
		)

		validate_permit_application_task(task)
		validate_permit_application_can_complete(task)
	elif task_is_ucr_application(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			validate_ucr_application_not_manually_completed,
		)

		validate_ucr_application_not_manually_completed(task)
	elif task_is_entry_application(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			APPLICATION_FINANCE_PROFILES,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
			validate_application_not_manually_completed,
		)

		validate_application_not_manually_completed(
			task, APPLICATION_FINANCE_PROFILES["Entry Application"]
		)
	elif task_is_shipping_line_application(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			APPLICATION_FINANCE_PROFILES,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_container_updates import (
			validate_shipping_line_deposit_declarations,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
			validate_application_not_manually_completed,
		)

		validate_shipping_line_deposit_declarations(task)
		validate_application_not_manually_completed(
			task, APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
		)
	elif task_is_kpa_application(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			APPLICATION_FINANCE_PROFILES,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
			validate_application_not_manually_completed,
		)

		validate_application_not_manually_completed(
			task, APPLICATION_FINANCE_PROFILES["KPA Application"]
		)
	elif task_is_document_checkpoint(task):
		validate_document_checkpoint_task(task)
	elif sea_import and container_step_for_task(task) in TRANSPORT_CONTAINER_STEPS:
		# Transport steps (Book Trucks to Interchange) need only light proof.
		validate_light_proof_task(task)
	elif container_step_for_task(task) == CONTAINER_STEP_FIELD_CLEARANCE:
		validate_field_clearance_task(task)

	if is_sea_finance_payment_task(task) or any(
		(
			task_is_ucr_finance(task),
			task_is_entry_finance(task),
			task_is_shipping_line_finance(task),
			task_is_kpa_finance(task),
			task_is_permit_finance(task),
		)
	):
		if task_is_ucr_finance(task):
			from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
				validate_finance_ucr_payment_task,
			)

			validate_finance_ucr_payment_task(task)
		elif task_is_entry_finance(task):
			from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
				APPLICATION_FINANCE_PROFILES,
			)
			from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
				validate_finance_application_payment_task,
			)

			validate_finance_application_payment_task(
				task, APPLICATION_FINANCE_PROFILES["Entry Application"]
			)
		elif task_is_shipping_line_finance(task):
			from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
				APPLICATION_FINANCE_PROFILES,
			)
			from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
				validate_shipping_line_deposit_payments,
			)
			from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
				validate_finance_application_payment_task,
			)

			validate_finance_application_payment_task(
				task, APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
			)
			validate_shipping_line_deposit_payments(task)
		elif task_is_kpa_finance(task):
			from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
				APPLICATION_FINANCE_PROFILES,
			)
			from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
				validate_finance_application_payment_task,
			)

			validate_finance_application_payment_task(
				task, APPLICATION_FINANCE_PROFILES["KPA Application"]
			)
		elif task_is_permit_finance(task):
			from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
				validate_finance_permit_payment_task,
				validate_permit_finance_task_completion,
			)

			validate_finance_permit_payment_task(task)
			validate_permit_finance_task_completion(task)
		else:
			validate_finance_task(task)


def validate_required_documents(task, seq: int) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import primary_attachment
	required = get_effective_required_document_types(task)
	# A task with no required documents does not gate completion on Task Documents.
	if not required:
		return

	attached = attached_document_codes(task)
	missing = []
	for token in required:
		if required_document_code_is_attached(token, attached):
			continue
		dt_name = resolve_required_document_type_name(token)
		if dt_name and required_document_code_is_attached(dt_name, attached):
			continue
		missing.append(dt_name or token)

	if missing:
		frappe.throw(
			"Attach required documents on <b>Task Documents</b> before completing this task: "
			f"<b>{', '.join(missing)}</b>."
		)

	# Only enforce empty-row cleanup for required rows.
	required_names = set(_required_document_type_names(task, required))
	empty_rows = [
		row.document_type or "Document"
		for row in task.get(TASK_DOCUMENTS_FIELD) or []
		if row.document_type
		and (not required_names or row.document_type in required_names)
		and not primary_attachment(row)
	]
	if empty_rows:
		frappe.throw(
			"Remove empty document rows or upload attachments for: "
			f"<b>{', '.join(empty_rows)}</b>."
		)


def validate_document_checkpoint_task(task) -> None:
	"""Final clearance docs: upload finals on Task Documents or add a confirmation note."""
	rows = task.get(TASK_DOCUMENTS_FIELD) or []
	has_final = any((row.get("final_attachment") or "").strip() for row in rows)
	has_note = bool((task.description or "").strip())
	if has_final or has_note:
		return
	frappe.throw(
		_(
			"Upload at least one <b>Final Document</b> on Task Documents, or add a brief "
			"confirmation note in <b>Description</b> (e.g. <i>Final BL and COC confirmed received</i>)."
		)
	)


def validate_light_proof_task(task) -> None:
	has_doc = bool(attached_document_codes(task))
	has_text = bool((task.description or "").strip())
	has_ref = bool((task.get("custom_external_ref_no") or "").strip())
	if not (has_doc or has_text or has_ref):
		frappe.throw(
			"Add a task document, <b>Description</b>, or <b>External Ref No</b> before completing this step."
		)


def validate_field_clearance_task(task) -> None:
	"""Field clearance completes when ops attach a document or record CRO release."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CONTAINER_STEP_FIELD_CLEARANCE,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
		container_step_for_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		primary_attachment,
	)

	if container_step_for_task(task) != CONTAINER_STEP_FIELD_CLEARANCE:
		return

	released = (task.get("custom_verification_status") or "") == "Released by CRO"
	report_attached = frappe.utils.cint(task.get("custom_verification_report_attached"))
	has_clearance_doc = any(
		primary_attachment(row)
		for row in task.get(TASK_DOCUMENTS_FIELD) or []
		if row.document_type
	)
	if released or report_attached or has_clearance_doc:
		return

	frappe.throw(
		_(
			"Attach a clearance document on <b>Task Documents</b> (any document type), "
			"or mark <b>Verification Status</b> as <i>Released by CRO</i>, "
			"or attach the <b>Verification Report</b>."
		)
	)


def _permit_type_examples(limit: int = 5) -> str:
	"""Example permit codes from the Permit Type master (no hardcoded list)."""
	if not frappe.db.exists("DocType", "Permit Type"):
		return ""
	names = frappe.get_all("Permit Type", pluck="name", order_by="name asc", limit=limit)
	return ", ".join(names)


def validate_permit_application_task(task) -> None:
	if not task.meta.has_field(TASK_PERMITS_FIELD):
		frappe.throw("Task Permits table is not available on this site. Run <b>bench migrate</b>.")

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		permit_application_client_paid,
	)
	from cgm_shipping.cgm_worldwide_shipping.doctype.permit_register.permit_register import (
		permit_requires_payment,
	)

	rows = task.get(TASK_PERMITS_FIELD) or []
	examples = _permit_type_examples()
	eg = f" (e.g. {examples})" if examples else ""

	# Client-pays still needs invoices/certificates on rows; empty rows are fine
	# (nothing to attach). Settlement (verify + client receipt) is enforced elsewhere.
	if permit_application_client_paid(task):
		missing = []
		for row in rows:
			label = row.permit_type or "Permit"
			if not row.permit_type:
				continue
			if permit_requires_payment(row):
				if not row.get("payment_invoice"):
					missing.append(f"{label} - supplier/permit invoice (Local)")
				if not row.get("permit_document"):
					missing.append(f"{label} - permit certificate")
			elif not row.get("permit_document"):
				missing.append(f"{label} - permit certificate (Foreign)")
		if missing:
			frappe.throw(
				"Complete <b>Task Permits</b> before finishing this task:<ul>"
				+ "".join(f"<li>{m}</li>" for m in missing)
				+ "</ul>",
				title="Permit documents required",
			)
		return

	if not rows:
		frappe.throw(
			f"Add at least one permit on <b>Task Permits</b>{eg} "
			"and attach the required documents before completing this task."
		)

	missing = []
	for row in rows:
		label = row.permit_type or "Permit"
		if not row.permit_type:
			missing.append(f"Permit type{eg}")
			continue
		if permit_requires_payment(row):
			if not row.get("payment_invoice"):
				missing.append(f"{label} - supplier/permit invoice (Local)")
		elif not row.get("permit_document"):
			missing.append(f"{label} - permit certificate (Foreign)")

	if missing:
		frappe.throw(
			"Complete <b>Task Permits</b> before finishing this task:<ul>"
			+ "".join(f"<li>{m}</li>" for m in missing)
			+ "</ul>",
			title="Permit documents required",
		)


def validate_finance_task(task) -> None:
	attached = attached_document_codes(task)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_permit_finance,
	)

	if not task_is_permit_finance(task) and SUPPLIER_INVOICE_CODE not in attached:
		frappe.throw(
			"Attach the <b>Supplier Invoice</b> on <b>Task Documents</b> for Accounts to verify "
			"before completing this finance task."
		)

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		task_client_paid_directly,
		task_has_recorded_payment,
	)

	# Sea finance payments use Make Payment → Journal Entry (not Purchase Invoice).
	if not task_client_paid_directly(task) and not task_has_recorded_payment(task):
		frappe.throw(
			"Record payment via <b>Make Payment</b> (Journal Entry) before completion, "
			"or tick <b>Client will pay</b> if the client settles it."
		)
	if task.get("custom_payment_entry"):
		pe_status = frappe.db.get_value("Payment Entry", task.custom_payment_entry, "docstatus")
		if int(pe_status or 0) != 1:
			frappe.throw("Payment Entry must be <b>submitted</b> before completing this finance task.")


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

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_permit_finance,
		task_permit_stage,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	default_stage = task_permit_stage(task, PRE_CLEARANCE_STAGE)
	is_finance_permit_payment = task_is_permit_finance(task)

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
		prow.origin = trow.get("origin") or "Local"
		prow.stage = trow.stage or default_stage
		if trow.get("payment_invoice"):
			prow.payment_invoice = trow.payment_invoice
			prow.invoice_uploaded_on = trow.get("invoice_uploaded_on")
			prow.invoice_uploaded_by = trow.get("invoice_uploaded_by")
			prow.status = "Invoice Submitted"
			if trow.get("invoice_amount"):
				prow.invoice_amount = trow.invoice_amount
		if trow.get("permit_document"):
			prow.permit_document = trow.permit_document
			prow.certificate_uploaded_on = trow.get("certificate_uploaded_on")
			prow.certificate_uploaded_by = trow.get("certificate_uploaded_by")
			if (trow.get("origin") or "Local") == "Foreign":
				prow.status = prow.status or "Approved"
		if trow.get("payment_receipt"):
			prow.payment_receipt = trow.payment_receipt
			prow.status = prow.status or "Receipt Submitted"

		if is_finance_permit_payment and trow.get("invoice_verified"):
			prow.invoice_verified = 1
			if prow.status in (None, "", "Invoice Submitted"):
				prow.status = "Invoice Verified"
		if is_finance_permit_payment and task.get("custom_purchase_invoice"):
			prow.purchase_invoice = task.custom_purchase_invoice
			prow.invoice_verified = 1
			prow.status = "Invoice Verified"
		if is_finance_permit_payment and trow.get("journal_entry"):
			prow.journal_entry = trow.journal_entry
			prow.payment_date = frappe.db.get_value(
				"Journal Entry", trow.journal_entry, "posting_date"
			)
			prow.status = "Paid"
		elif is_finance_permit_payment and task.get("custom_payment_entry"):
			prow.payment_entry = task.custom_payment_entry
			prow.payment_date = frappe.db.get_value(
				"Payment Entry", task.custom_payment_entry, "posting_date"
			)
			prow.status = "Paid"
		if is_finance_permit_payment and trow.get("receipt_verified"):
			prow.receipt_verified = trow.receipt_verified
		if trow.get("shared_with_client") and hasattr(prow, "shared_with_client"):
			prow.shared_with_client = 1
			prow.shared_by = trow.get("shared_by")
			prow.shared_on = trow.get("shared_on")

		if hasattr(prow, "custom_source_task"):
			prow.custom_source_task = task.name
		prow.clearance_phase = derive_permit_clearance_phase(prow)

	frappe.flags.cgm_syncing_permits = True
	try:
		project.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_syncing_permits = False


def apply_finance_payment_to_project_permits(task) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_permit_finance,
	)

	if not task_is_permit_finance(task):
		return
	sync_task_permits_to_project(task)


@frappe.whitelist()
def reopen_completed_task(task_name: str, reason: str | None = None) -> dict:
	"""Re-open any completed sea clearance task so documents can be corrected mid-project.

	Finance-paired tasks keep their existing verify → pay → receipt flow when new
	invoices are attached after reopen. This endpoint only reopens the selected task.
	"""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if task.status == "Cancelled":
		frappe.throw("Cancelled tasks cannot be reopened.")
	if task.status != "Completed":
		return {
			"task": task.name,
			"status": task.status,
			"reopened": False,
			"message": "Task is already open.",
		}

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		is_sea_import_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import _reopen_sea_task

	if not is_sea_import_task(task) and not task.get("custom_task_flow_key"):
		# Still allow Project workflow tasks that carry CGM custom fields.
		if not task.meta.has_field("custom_sequence_no"):
			frappe.throw("This reopen action is only for clearance workflow tasks.")

	frappe.flags.cgm_reopening_task = True
	try:
		opened = _reopen_sea_task(
			task,
			reason=(reason or "").strip() or "Reopened to correct or replace attachments",
		)
	finally:
		frappe.flags.cgm_reopening_task = False

	return {
		"task": task.name,
		"status": frappe.db.get_value("Task", task.name, "status") or "Open",
		"reopened": bool(opened),
		"message": (
			"Task reopened. Attach or replace documents, then mark complete again when ready."
			if opened
			else "Task was not reopened."
		),
	}


@frappe.whitelist()
def reopen_task_for_permit_attachments(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_permit_application,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	if not task_is_permit_application(task):
		frappe.throw("This action is only for pre-/post-clearance permit application tasks.")

	missing = [
		r.permit_type
		for r in task.get(TASK_PERMITS_FIELD) or []
		if r.permit_type
		and (
			((r.get("origin") or "Local").strip() == "Foreign" and not r.get("permit_document"))
			or ((r.get("origin") or "Local").strip() != "Foreign" and not r.get("payment_invoice"))
		)
	]
	if not missing and task.status != "Completed":
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			handle_additional_permit_work_on_application,
		)

		result = handle_additional_permit_work_on_application(task)
		if result and result.get("reopened"):
			return {
				"task": task.name,
				"status": frappe.db.get_value("Task", task.name, "status"),
				"missing_invoices": missing,
				**result,
			}
		frappe.throw(
			"Task is already open, or all permit rows already have the required attachments."
		)

	task.status = "Open"
	task.progress = 0
	task.completed_by = None
	task.completed_on = None
	frappe.flags.cgm_reopening_task = True
	try:
		task.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_reopening_task = False
	sync_task_permits_to_project(task)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		handle_additional_permit_work_on_application,
	)

	extra = handle_additional_permit_work_on_application(frappe.get_doc("Task", task.name)) or {}
	return {
		"task": task.name,
		"status": frappe.db.get_value("Task", task.name, "status"),
		"missing_invoices": missing,
		**extra,
	}


# ==================== Finance document linking ====================

"""Link Purchase Invoice / Payment Entry to sea finance Tasks and Project."""
from frappe.utils import cint, flt, now_datetime

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
	permit_row_name: str | None = None,
	finance_line_name: str | None = None,
) -> str:
	"""Create a *draft* Journal Entry to pay a finance Task.

	Accounts are chosen in the dialog: ``pay_to_account`` is debited (the expense
	or payable being settled) and ``pay_from_account`` (Bank/Cash) is credited.
	A Party is attached to whichever account is a Payable/Receivable account.

	Optional ``permit_row_name`` / ``finance_line_name`` link the JE to a specific
	permit or Task Finance Line (amendment invoices).
	"""
	from frappe.utils import cint, flt, getdate, today

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
			"A selected account is a <b>Party</b> account - choose a Party Type and Party."
		)

	permit_row = None
	if permit_row_name:
		for row in task.get(TASK_PERMITS_FIELD) or []:
			if row.name == permit_row_name:
				permit_row = row
				break
		if not permit_row:
			frappe.throw("Permit row not found on this task.")
		if permit_row.get("journal_entry"):
			frappe.throw(
				f"A Journal Entry is already linked for <b>{permit_row.permit_type}</b>."
			)
		if permit_row.get("payment_invoice") and not cint(permit_row.get("invoice_verified")):
			frappe.throw(
				f"Verify the <b>{permit_row.permit_type}</b> invoice first "
				"(tick <b>Invoice Verified</b> or use <b>Verify Invoices</b>) before Make Payment."
			)

	finance_line = None
	if finance_line_name:
		from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
			TASK_FINANCE_FIELD,
		)

		for row in task.get(TASK_FINANCE_FIELD) or []:
			if row.name == finance_line_name:
				finance_line = row
				break
		if not finance_line:
			frappe.throw("Finance invoice line not found on this task.")
		if finance_line.get("journal_entry"):
			frappe.throw(
				f"A Journal Entry is already linked for <b>{finance_line.line_label or 'invoice'}</b>."
			)
		if finance_line.get("attachment") and not cint(finance_line.get("verified")):
			frappe.throw(
				f"Verify <b>{finance_line.line_label or 'the invoice'}</b> before Make Payment."
			)

	remark = user_remark or f"{task.subject} ({task.name})"
	if permit_row and permit_row.get("permit_type"):
		remark = user_remark or f"{task.subject} - {permit_row.permit_type} ({task.name})"
	elif finance_line and finance_line.get("line_label"):
		remark = user_remark or f"{task.subject} - {finance_line.line_label} ({task.name})"

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

	if permit_row:
		frappe.db.set_value(
			"Permit Register",
			permit_row.name,
			"journal_entry",
			je.name,
			update_modified=False,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			notify_declarant_upload_permit_receipts,
			task_has_recorded_payment,
		)

		task.reload()
		if task_has_recorded_payment(task):
			notify_declarant_upload_permit_receipts(task)
	elif finance_line:
		frappe.db.set_value(
			"Task Finance Line",
			finance_line.name,
			"journal_entry",
			je.name,
			update_modified=False,
		)
		# Task-level JE is a legacy mirror of the primary invoice only (hidden in UI).
		# Amendments keep JE on their row so Reference No does not show the wrong payment.
		if task.meta.has_field("custom_journal_entry") and not cint(
			finance_line.get("is_amendment")
		):
			frappe.db.set_value(
				"Task", task.name, "custom_journal_entry", je.name, update_modified=False
			)
	elif task.meta.has_field("custom_journal_entry"):
		frappe.db.set_value(
			"Task", task.name, "custom_journal_entry", je.name, update_modified=False
		)
		# Also stamp the primary Invoice row when payment was not scoped to a line.
		try:
			from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
				get_invoice_line,
				profile_for_task,
			)

			profile = profile_for_task(task)
			primary = get_invoice_line(task, profile) if profile else None
			if primary and primary.name and not primary.get("journal_entry"):
				frappe.db.set_value(
					"Task Finance Line",
					primary.name,
					"journal_entry",
					je.name,
					update_modified=False,
				)
		except Exception:
			pass

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_entry_finance,
		task_is_ucr_finance,
	)

	if task_is_ucr_finance(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			notify_operations_upload_ucr_receipt,
			sync_ucr_payment_to_idf_record,
			task_has_recorded_payment,
		)

		task.reload()
		sync_ucr_payment_to_idf_record(task)
		# Wait until every invoice line (incl. amendments) is settled.
		if task_has_recorded_payment(task):
			notify_operations_upload_ucr_receipt(task)
	elif task_is_entry_finance(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			APPLICATION_FINANCE_PROFILES,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			task_has_recorded_payment,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
			notify_declarant_upload_application_receipt,
			sync_application_payment_hooks,
		)

		task.reload()
		entry_profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
		sync_application_payment_hooks(task, entry_profile)
		if task_has_recorded_payment(task):
			notify_declarant_upload_application_receipt(task, entry_profile)

	return je.name


PAYMENT_ITEM_ITEM_CANDIDATES: dict[str, tuple[str, ...]] = {
	"UCR": ("UCR Fee", "UCR", "CGM-UCR", "Import UCR"),
	# Prefer the live Item "Customs Entry" / "Entry" used on sea import.
	"ENTRY_SLIP": (
		"Customs Entry",
		"Entry",
		"Entry Slip",
		"Entry Slip Fee",
		"Customs Entry Slip",
		"ENTRY_SLIP",
	),
	"Shipping Line": ("Shipping Line Charge", "Shipping Line", "Line Charges"),
	"Customs Entry": ("Customs Entry", "Entry", "Entry Payment", "Customs Entry Charge"),
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
	"""Fallback Item when a payment line has no mapped item (legacy PI helpers)."""
	settings_item = None
	if frappe.db.exists("DocType", "CGM Shipping Settings"):
		meta = frappe.get_meta("CGM Shipping Settings")
		# Field removed from Settings UI; keep reading if an old column still exists.
		if meta.has_field("custom_default_purchase_item"):
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

	return ""


def get_permit_rows_for_purchase_invoice(task) -> list[dict]:
	"""Permit rows with invoice + amount for PI line pre-fill (permit finance steps)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_permit_finance,
		task_permit_stage,
	)

	if not task_is_permit_finance(task):
		return []

	if task.meta.has_field(TASK_PERMITS_FIELD) and not task.get(TASK_PERMITS_FIELD):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			ensure_finance_permit_rows_saved,
		)

		ensure_finance_permit_rows_saved(task)
		task.reload()

	rows: list = list(task.get(TASK_PERMITS_FIELD) or [])

	if not rows and task.project:
		stage = task_permit_stage(task, PRE_CLEARANCE_STAGE)
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
	"""Purchase Invoice Item rows from the UCR invoice finance line on Finance pays UCR.

	Amount is entered on Make Payment (Journal Entry), not on the finance line.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_finance,
	)

	if not task_is_ucr_finance(task):
		return []

	inv = get_ucr_invoice_line(task)
	if not inv or not inv.attachment:
		return []

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
			"rate": 0,
			"amount": 0,
			"project": task.project,
			"payment_item": payment_item,
		}
	]


def build_entry_purchase_invoice_lines(task) -> list[dict]:
	"""Purchase Invoice Item rows from the Entry Slip invoice finance line."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
		build_application_purchase_invoice_lines,
	)

	return build_application_purchase_invoice_lines(
		task, APPLICATION_FINANCE_PROFILES["Entry Application"]
	)


def build_shipping_line_purchase_invoice_lines(task) -> list[dict]:
	"""Purchase Invoice Item rows from the Shipping Line invoice finance line."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
		build_application_purchase_invoice_lines,
	)

	return build_application_purchase_invoice_lines(
		task, APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
	)


def build_kpa_purchase_invoice_lines(task) -> list[dict]:
	"""Purchase Invoice Item rows from the KPA invoice finance line."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
		build_application_purchase_invoice_lines,
	)

	return build_application_purchase_invoice_lines(
		task, APPLICATION_FINANCE_PROFILES["KPA Application"]
	)


@frappe.whitelist()
def get_task_defaults(task_name: str) -> dict:
	"""Defaults for Purchase Invoice / Payment Entry opened from a finance Task."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	ctx = _task_context(task)
	seq = int(task.get("custom_sequence_no") or 0)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_entry_finance,
		task_is_kpa_finance,
		task_is_permit_finance,
		task_is_shipping_line_finance,
		task_is_ucr_finance,
	)

	if task_is_permit_finance(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			ensure_finance_permit_rows_saved,
		)

		ensure_finance_permit_rows_saved(task)
		task.reload()
	if task_is_ucr_finance(task):
		ensure_ucr_finance_lines_saved(task)
		task.reload()
	if task_is_entry_finance(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			APPLICATION_FINANCE_PROFILES,
			ensure_application_finance_lines_saved,
		)

		ensure_application_finance_lines_saved(
			task, APPLICATION_FINANCE_PROFILES["Entry Application"]
		)
		task.reload()
	if task_is_shipping_line_finance(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			APPLICATION_FINANCE_PROFILES,
			ensure_application_finance_lines_saved,
		)

		ensure_application_finance_lines_saved(
			task, APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
		)
		task.reload()
	if task_is_kpa_finance(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			APPLICATION_FINANCE_PROFILES,
			ensure_application_finance_lines_saved,
		)

		ensure_application_finance_lines_saved(
			task, APPLICATION_FINANCE_PROFILES["KPA Application"]
		)
		task.reload()
	permit_rows = get_permit_rows_for_purchase_invoice(task)
	permit_lines = build_permit_purchase_invoice_lines(task)
	ucr_lines = build_ucr_purchase_invoice_lines(task)
	entry_lines = build_entry_purchase_invoice_lines(task)
	shipping_line_lines = build_shipping_line_purchase_invoice_lines(task)
	kpa_lines = build_kpa_purchase_invoice_lines(task)
	finance_line_items = permit_lines + ucr_lines + entry_lines + shipping_line_lines + kpa_lines
	remarks = f"{task.subject} ({task.name}) - {ctx['project']}"
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_finance,
	)

	if task_is_ucr_finance(task):
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


def journal_entry_on_submit(doc, method=None):
	"""Act on the finance task a submitted Journal Entry pays for.

	UCR and Entry finance notify the declarant; Permit Finance completes once its
	last entry is posted. That entry is usually submitted after the task's last
	save, and nothing else saves the task then - a form-load heal runs in a GET
	request and is never committed - so the task stayed Open in the list while the
	form showed Completed.
	"""
	task_name = doc.get("custom_cgm_source_task")
	if not task_name or not frappe.db.exists("Task", task_name):
		return
	task = frappe.get_doc("Task", task_name)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_entry_finance,
		task_is_permit_finance,
		task_is_ucr_finance,
	)

	if task_is_permit_finance(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			auto_complete_finance_permit_task,
		)

		auto_complete_finance_permit_task(task)
		return

	if task_is_ucr_finance(task):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			notify_operations_upload_ucr_receipt,
			sync_ucr_payment_to_idf_record,
		)

		sync_ucr_payment_to_idf_record(task)
		notify_operations_upload_ucr_receipt(task)
		return
	if not task_is_entry_finance(task):
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
		notify_declarant_upload_application_receipt,
		sync_application_payment_hooks,
	)

	entry_profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
	sync_application_payment_hooks(task, entry_profile)
	notify_declarant_upload_application_receipt(task, entry_profile)


def journal_entry_on_cancel(doc, method=None):
	"""Journal Entry cancel — finance cost ledger refresh handled in finance_cost_ledger hook."""
	return


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


	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_entry_finance,
		task_is_permit_finance,
		task_is_ucr_finance,
	)

	# UCR / Entry Slip / permit finance: record PE only - complete after receipts verified.
	if task_is_ucr_finance(task) or task_is_entry_finance(task) or task_is_permit_finance(task):
		if task_fields.has_field("custom_payment_entry"):
			_set_task_fields(task.name, {"custom_payment_entry": payment_entry})
		task = frappe.get_doc("Task", task.name)

		frappe.flags.cgm_skip_task_project_sync = True
		try:
			if task_is_permit_finance(task):
				apply_finance_payment_to_project_permits(task)
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
					notify_declarant_upload_permit_receipts,
					seed_finance_task_permits_from_project,
				)

				seed_finance_task_permits_from_project(task)
				sync_task_permits_to_project(task)
				notify_declarant_upload_permit_receipts(task)
				message = (
					"Payment recorded. You may optionally attach payment receipts on each Local "
					"permit row on this finance task when available."
				)
			elif task_is_entry_finance(task):
				from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
					APPLICATION_FINANCE_PROFILES,
				)
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
					notify_declarant_upload_application_receipt,
					sync_application_payment_hooks,
				)

				entry_profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
				sync_application_payment_hooks(task, entry_profile)
				notify_declarant_upload_application_receipt(task, entry_profile)
				message = (
					"Payment recorded. You may optionally attach the <b>Entry Slip Receipt</b> "
					"on this finance task when available."
				)
			else:
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
					notify_operations_upload_ucr_receipt,
					sync_ucr_payment_to_idf_record,
				)

				sync_ucr_payment_to_idf_record(task)
				notify_operations_upload_ucr_receipt(task)
				message = (
					"Payment recorded. You may optionally attach the <b>UCR Receipt</b> "
					"on this finance task when available."
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
	"""True for Sea Import OR any task with stamped clearance behaviour."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		uses_clearance_behaviour,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		is_sea_import_task,
	)

	return is_sea_import_task(doc) or uses_clearance_behaviour(doc)


def on_task_onload(doc, _method=None):
	"""Reconcile the task, then prepare it for the form.

	Reconciliation writes (it seeds finance lines and permit rows, and can
	auto-complete or reopen the task), so it is gated on write permission: a
	read-only viewer must not mutate a task, bump its ``modified`` - which hands
	whoever has it open a "Document has been modified" conflict - or write around
	the department permission layer via ``ignore_permissions``.

	Form presentation below the gate is read-only and always runs, so viewers
	still get the correct status and documents grid.
	"""
	if doc.is_new():
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_status import (
		get_persisted_task_completion_fields,
	)

	persisted = get_persisted_task_completion_fields(doc.name)
	can_write = frappe.has_permission("Task", ptype="write", doc=doc.name)
	if can_write:
		_reconcile_task_on_load(doc)
	_prepare_task_for_form(doc)
	_settle_status_worked_out_on_load(doc, persisted, can_write)


def _settle_status_worked_out_on_load(doc, persisted: dict, can_write: bool) -> None:
	"""Keep form and list on one status when opening the form changed it.

	The form is fetched with a GET, and Frappe rolls back a GET's writes - so a
	status the load healed or reopened showed on the form while tabTask, and the
	list, kept the old one (TASK-2026-01209). For someone who can edit the task the
	request is committed, which keeps that status and the load's other writes with
	it; a viewer's form shows the stored status instead.
	"""
	from frappe.auth import UNSAFE_HTTP_METHODS

	request = getattr(frappe.local, "request", None)
	if not persisted or not request or request.method in UNSAFE_HTTP_METHODS:
		return
	if frappe.db.get_value("Task", doc.name, "status") == persisted.get("status"):
		return
	if can_write:
		frappe.local.flags.commit = True
		return
	for field in ("status", "progress", "completed_by", "completed_on"):
		doc.set(field, persisted.get(field))


def _reconcile_task_on_load(doc) -> None:
	"""Writes performed when a task form is opened by someone who can edit it."""
	if purge_invoice_rows_from_task_documents_db(doc.name):
		doc.reload()
	if _is_sea_task(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			purge_foreign_finance_lines,
		)

		purged_finance = purge_foreign_finance_lines(doc)
		purged_docs = purge_unrequired_task_document_rows(doc)
		prepare_ucr_task_tables(doc)
		prepare_application_finance_task_tables(doc)
		if purged_finance or purged_docs:
			preserve_completed_status_against_stale_save(doc)
			doc.save(ignore_permissions=True)
			doc.reload()
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_configured_application_workflow,
		task_is_permit_application,
		task_is_permit_finance,
		task_is_ucr_application,
		task_is_ucr_finance,
		task_is_ucr_workflow,
	)

	if _is_sea_task(doc) and task_is_ucr_workflow(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			ensure_ucr_finance_lines_saved,
			sync_ucr_status_from_finance_to_application,
		)

		changed = ensure_ucr_finance_lines_saved(doc)
		changed = clear_verification_without_attachment(doc) or changed
		if task_is_ucr_application(doc):
			changed = sync_ucr_status_from_finance_to_application(doc) or changed
			if doc.status not in ("Completed", "Cancelled"):
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
					try_auto_complete_ucr_application_task,
				)

				if try_auto_complete_ucr_application_task(doc):
					changed = True
		elif task_is_ucr_finance(doc) and doc.status not in ("Completed", "Cancelled"):
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

	if _is_sea_task(doc) and task_is_configured_application_workflow(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
			process_application_workflow_onload,
		)

		if process_application_workflow_onload(doc):
			doc.reload()

	if _is_sea_task(doc) and task_is_permit_finance(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			application_missing_finance_permit_receipts,
			ensure_finance_permit_rows_saved,
			get_permit_application_task_for_finance,
			handle_finance_permit_receipt_upload,
			reopen_permit_finance_if_pending_work,
		)

		if ensure_finance_permit_rows_saved(doc):
			doc.reload()
		# Completed + unpaid additional permits → reopen so Make Payment shows.
		result = reopen_permit_finance_if_pending_work(doc)
		if result and result.get("reopened"):
			doc.reload()
		# Sync receipts only when Declarant is missing them (cheap SQL gate).
		app_name = get_permit_application_task_for_finance(doc)
		if app_name and application_missing_finance_permit_receipts(app_name, doc.name):
			handle_finance_permit_receipt_upload(doc)

	if _is_sea_task(doc) and task_is_permit_application(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			ensure_finance_permit_receipts_visible_on_application,
			merge_project_permits_into_application_task,
		)

		changed = merge_project_permits_into_application_task(doc)
		# Always pull Finance-uploaded receipts onto Declarant form.
		if ensure_finance_permit_receipts_visible_on_application(doc):
			changed = True
		if changed:
			doc.reload()

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_container_updates import (
		on_task_onload_container_updates,
	)

	on_task_onload_container_updates(doc)

	if doc.meta.has_field(TASK_DOCUMENTS_FIELD):
		# Prefill Task Documents from CGM Task Template Required Document Types.
		if ensure_stamped_required_documents_saved(doc):
			doc.reload()
		else:
			purged_docs = purge_unrequired_task_document_rows(doc)
			seeded = seed_stamped_required_document_rows(doc)
			if purged_docs or seeded:
				preserve_completed_status_against_stale_save(doc)
				doc.save(ignore_permissions=True)
				doc.reload()


def _prepare_task_for_form(doc) -> None:
	"""Read-only form presentation. Safe for viewers without write access."""
	if doc.meta.has_field(TASK_DOCUMENTS_FIELD):
		from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
			prepare_shipment_documents_for_form,
		)

		prepare_shipment_documents_for_form(doc, TASK_DOCUMENTS_FIELD)

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_status import (
		finalize_task_status_for_form,
	)

	finalize_task_status_for_form(doc)


def preserve_completed_status_against_stale_save(doc) -> None:
	"""Keep Completed when an incidental save still carries status=Open in memory.

	Finance auto-complete writes Completed via db.set_value. Seeding finance lines
	or receipt sync can then save the older in-memory Open doc and make List View
	show Open while the form (after a reload) still shows Completed.

	Also force Completed when this save's own finance lines already satisfy the
	completion gate — so a late Open save cannot win the race after verify/pay.
	"""
	if doc.is_new() or doc.status in ("Completed", "Cancelled"):
		return
	if frappe.flags.get("cgm_reopening_task"):
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_application_finance_for_profile,
		task_is_application_for_profile,
		task_is_permit_application,
		task_is_permit_finance,
		task_is_ucr_application,
	)

	if not is_sea_finance_payment_task(doc) and not task_is_permit_finance(doc):
		# Also protect paired application finance profiles and UCR create when
		# they were completed by set_value and a later sync save is stale.
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			can_complete_application_task,
			profile_for_task,
		)

		profile = profile_for_task(doc)
		if not (
			task_is_ucr_application(doc)
			or (
				profile
				and (
					task_is_application_for_profile(doc, profile)
					or task_is_application_finance_for_profile(doc, profile)
				)
			)
			or task_is_permit_application(doc)
		):
			return
		# Shipping Line (and other POP flows): never force Completed back when
		# receipt verify is still outstanding — that reopened↔Completed flicker.
		if (
			profile
			and profile.requires_pop
			and task_is_application_for_profile(doc, profile)
			and not can_complete_application_task(doc, profile)
		):
			return

	db_status = frappe.db.get_value("Task", doc.name, "status")
	ready = finance_payment_task_ready_to_complete(doc)
	if db_status != "Completed" and not ready:
		return
	doc.status = "Completed"
	if not doc.progress or float(doc.progress or 0) < 100:
		doc.progress = 100
	if not doc.completed_by:
		doc.completed_by = frappe.session.user
	if not doc.completed_on:
		doc.completed_on = now_datetime()
	if ready:
		frappe.flags.cgm_auto_completing_sea_task = True


def block_premature_shipping_line_completion(doc) -> None:
	"""Stale Desk forms can still submit status=Completed after onload heal to Open.

	Force those saves back to Open when POP receipt verify is not done yet.
	"""
	if doc.is_new() or doc.status != "Completed":
		return
	if frappe.flags.get("cgm_auto_completing_sea_task") or frappe.flags.get("cgm_reopening_task"):
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		can_complete_application_task,
		profile_for_task,
	)

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_application_for_profile,
	)

	profile = profile_for_task(doc)
	if not profile or not profile.requires_pop or not task_is_application_for_profile(doc, profile):
		return
	if can_complete_application_task(doc, profile):
		return
	_revert_premature_task_completion(doc)


def _revert_premature_task_completion(doc) -> None:
	doc.status = "Open"
	doc.progress = 0
	doc.completed_by = None
	doc.completed_on = None


def block_premature_finance_completion(doc) -> None:
	"""Force Open when a stale form still carries Completed but finance gates fail."""
	if doc.is_new() or doc.status != "Completed":
		return
	if frappe.flags.get("cgm_auto_completing_sea_task") or frappe.flags.get("cgm_reopening_task"):
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		can_complete_application_finance_task,
		profile_for_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_application_finance_for_profile,
		task_is_permit_finance,
		task_is_ucr_finance,
	)

	if task_is_ucr_finance(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			can_complete_ucr_payment_task,
		)

		if not can_complete_ucr_payment_task(doc):
			_revert_premature_task_completion(doc)
		return

	if task_is_permit_finance(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			can_complete_finance_permit_task,
		)

		if not can_complete_finance_permit_task(doc):
			_revert_premature_task_completion(doc)
		return

	profile = profile_for_task(doc)
	if profile and task_is_application_finance_for_profile(doc, profile):
		if not can_complete_application_finance_task(doc, profile):
			_revert_premature_task_completion(doc)


def finance_payment_task_ready_to_complete(doc) -> bool:
	"""True when a clearance finance payment task has met its completion gate."""
	if not _is_sea_task(doc) or doc.status == "Cancelled":
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_application_finance_for_profile,
		task_is_permit_finance,
		task_is_ucr_finance,
	)

	if task_is_ucr_finance(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			can_complete_ucr_payment_task,
		)

		return can_complete_ucr_payment_task(doc)
	if task_is_permit_finance(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			can_complete_finance_permit_task,
		)

		return can_complete_finance_permit_task(doc)

	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		can_complete_application_finance_task,
		profile_for_task,
	)

	profile = profile_for_task(doc)
	if profile and task_is_application_finance_for_profile(doc, profile):
		return can_complete_application_finance_task(doc, profile)
	return False


def promote_ready_finance_task_before_save(doc) -> None:
	"""Write Completed on the same save that finishes payment verification.

	Avoids the set_value-then-stale-save race that desyncs form vs list status.
	"""
	if doc.status in ("Completed", "Cancelled") or not _is_sea_task(doc):
		return
	if not finance_payment_task_ready_to_complete(doc):
		return
	doc.status = "Completed"
	doc.completed_by = doc.completed_by or frappe.session.user
	doc.completed_on = doc.completed_on or now_datetime()
	doc.progress = 100
	frappe.flags.cgm_auto_completing_sea_task = True


def heal_ready_finance_task_status(doc) -> bool:
	"""If a finance task is Open but payment/receipt gates are met, force Completed.

	Covers the race where auto-complete wrote Completed via set_value, then a
	concurrent stale save still carrying status=Open overwrote the DB. List View
	then showed Open while the form (after reload/auto-complete) looked Completed.
	"""
	if frappe.flags.get("cgm_reopening_task") or frappe.flags.get("cgm_healing_finance_status"):
		return False
	if doc.is_new() or doc.status in ("Completed", "Cancelled") or not _is_sea_task(doc):
		return False
	if not finance_payment_task_ready_to_complete(doc):
		return False

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		mark_task_completed,
	)

	frappe.flags.cgm_healing_finance_status = True
	frappe.flags.cgm_auto_completing_sea_task = True
	try:
		mark_task_completed(doc)
	finally:
		frappe.flags.cgm_auto_completing_sea_task = False
		frappe.flags.cgm_healing_finance_status = False
	return True


def before_task_save(doc, _method=None):
	"""Pre-fill required document rows while the task is still open."""
	from cgm_shipping.cgm_worldwide_shipping.doctype.permit_register.permit_register import (
		stamp_permit_register_upload_metadata,
	)
	from cgm_shipping.cgm_worldwide_shipping.doctype.shipment_document.shipment_document import (
		stamp_shipment_document_upload_metadata,
	)

	stamp_permit_register_upload_metadata(doc, TASK_PERMITS_FIELD)
	stamp_shipment_document_upload_metadata(doc, TASK_DOCUMENTS_FIELD)
	if not _is_sea_task(doc):
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_application_for_profile,
		task_is_document_checkpoint,
	)

	preserve_completed_status_against_stale_save(doc)
	block_premature_shipping_line_completion(doc)
	block_premature_finance_completion(doc)
	enforce_client_paid_confirmation(doc)
	# Always keep Shipping Line POP/Receipt rows present — a stale Completed save
	# used to wipe the POP child row and re-flicker the form on next open.
	if doc.status != "Cancelled":
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			APPLICATION_FINANCE_PROFILES,
			seed_application_finance_lines,
		)

		for profile in APPLICATION_FINANCE_PROFILES.values():
			if profile.requires_pop and task_is_application_for_profile(doc, profile):
				seed_application_finance_lines(doc, profile)
	if doc.status not in ("Completed", "Cancelled"):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			enforce_receipt_verified_permission,
			seed_finance_task_permits_from_project,
		)

		migrate_invoice_attachments_from_documents(doc)
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			purge_foreign_finance_lines,
		)

		purge_foreign_finance_lines(doc)
		purge_unrequired_task_document_rows(doc)
		prepare_ucr_task_tables(doc)
		prepare_application_finance_task_tables(doc)
		seed_required_task_document_rows(doc)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			enforce_ucr_finance_field_permissions,
			sync_ucr_payment_to_idf_record,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			APPLICATION_FINANCE_PROFILES,
			enforce_application_finance_line_permissions,
			normalize_application_finance_verification,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
			sync_application_payment_hooks,
		)

		seed_finance_task_permits_from_project(doc)
		normalize_finance_line_verification(doc)
		enforce_receipt_verified_permission(doc)
		enforce_ucr_finance_field_permissions(doc)
		for profile in APPLICATION_FINANCE_PROFILES.values():
			normalize_application_finance_verification(doc, profile)
			enforce_application_finance_line_permissions(doc, profile)
		sync_ucr_payment_to_idf_record(doc)
		for profile in APPLICATION_FINANCE_PROFILES.values():
			sync_application_payment_hooks(doc, profile)

		if task_is_document_checkpoint(doc):
			from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
				normalize_shipment_documents_table,
				promote_checkpoint_task_final_uploads,
				sync_checkpoint_finals_to_project,
			)

			promote_checkpoint_task_final_uploads(doc)
			normalize_shipment_documents_table(doc.get(TASK_DOCUMENTS_FIELD))
			sync_checkpoint_finals_to_project(doc)
		elif doc.get(TASK_DOCUMENTS_FIELD):
			from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
				sync_single_task_documents_to_project,
			)

			sync_single_task_documents_to_project(doc)

		from cgm_shipping.cgm_worldwide_shipping.customizations.task_container_updates import (
			apply_container_updates_from_task,
			validate_shipping_line_deposit_declarations,
		)

		apply_container_updates_from_task(doc)
		validate_shipping_line_deposit_declarations(doc)

	# After line verification is normalized so this save can write Completed once.
	promote_ready_finance_task_before_save(doc)


def notify_sea_task_your_turn(task) -> dict | None:
	"""When a sea Task becomes Open again, notify the department that owns it.

	Skips initial plan creation (tasks inserted already Open) to avoid spam.
	Specific handoffs (invoice → Finance pay, etc.) use dedicated Notifications.
	"""
	if frappe.flags.get("cgm_reopening_task") or frappe.flags.get("cgm_auto_completing_sea_task"):
		return None
	if not _is_sea_task(task) or task.status != "Open":
		return None
	prev = task.get_doc_before_save()
	if not prev or (prev.status or "") == "Open":
		return None
	from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
		send_notification,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
		your_turn_notification_for_department,
	)

	notification = your_turn_notification_for_department(task.get("department"))
	if not notification:
		return None
	flag_key = f"cgm_your_turn_notified:{task.name}"
	if frappe.flags.get(flag_key):
		return None
	frappe.flags[flag_key] = True
	return send_notification(notification, task, audience=task.get("department") or "users")


def on_task_update(doc, _method=None):
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_application_finance_for_profile,
		task_is_configured_application_workflow,
		task_is_permit_application,
		task_is_permit_finance,
		task_is_ucr_application,
		task_is_ucr_finance,
	)

	if _is_sea_task(doc):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_container_updates import (
			check_task_container_completion,
		)

		check_task_container_completion(doc)
		sync_client_paid_to_application_task(doc)
		try:
			notify_sea_task_your_turn(doc)
		except Exception:
			frappe.log_error(title=f"CGM your-turn notify failed for {doc.name}")

	if _is_sea_task(doc) and task_is_ucr_application(doc) and doc.status not in (
		"Completed",
		"Cancelled",
	):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			auto_submit_ucr_invoice_to_finance_if_needed,
			handle_ucr_application_receipt_upload,
			try_auto_complete_ucr_application_task,
		)

		auto_submit_ucr_invoice_to_finance_if_needed(doc)
		# Keep Finance Purchase Item in sync after the first submit (item edits).
		if doc.project:
			from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
				sync_ucr_invoice_to_finance_task,
			)

			sync_ucr_invoice_to_finance_task(doc.project)
		handle_ucr_application_receipt_upload(doc)
		try_auto_complete_ucr_application_task(doc)

	if (
		_is_sea_task(doc)
		and task_is_ucr_finance(doc)
		and doc.status not in ("Completed", "Cancelled")
	):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			handle_ucr_finance_receipt_upload,
			try_auto_complete_ucr_finance_task,
		)

		handle_ucr_finance_receipt_upload(doc)
		try_auto_complete_ucr_finance_task(doc)

	if (
		_is_sea_task(doc)
		and task_is_configured_application_workflow(doc)
		and doc.status != "Cancelled"
	):
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
			process_application_workflow_on_update,
		)

		# Shared path for UCR / Entry / Shipping Line / KPA — including Completed reopen.
		process_application_workflow_on_update(doc)

	if _is_sea_task(doc) and task_is_permit_finance(doc) and doc.status != "Cancelled":
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			handle_finance_permit_receipt_upload,
			permit_work_changed,
			reopen_permit_finance_if_pending_work,
			sync_permit_invoice_verification_to_application,
			try_auto_complete_permit_finance_task,
		)

		work_changed = permit_work_changed(doc)
		if work_changed or doc.status == "Completed":
			reopen_permit_finance_if_pending_work(doc)
		# Mirror receipts only when permit rows changed (or first save).
		if work_changed and not frappe.flags.get("cgm_permit_finance_completing"):
			handle_finance_permit_receipt_upload(doc)
			sync_permit_invoice_verification_to_application(doc)
		if doc.status not in ("Completed", "Cancelled") and not frappe.flags.get(
			"cgm_permit_finance_completing"
		):
			try_auto_complete_permit_finance_task(doc)

	if _is_sea_task(doc) and task_is_permit_application(doc) and doc.status != "Cancelled":
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			auto_submit_permit_invoices_to_finance_if_needed,
			handle_additional_permit_work_on_application,
			permit_work_changed,
		)

		# Change-gated: skip reopen/sync when permit table untouched.
		if permit_work_changed(doc) or doc.status == "Completed":
			handle_additional_permit_work_on_application(doc)
		if doc.status not in ("Completed", "Cancelled"):
			auto_submit_permit_invoices_to_finance_if_needed(doc)

	if frappe.flags.get("cgm_skip_task_project_sync"):
		return
	if doc.get("project"):
		# Only rebuild Project documents when this task's document table changed.
		from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
			refresh_project_documents,
		)

		prev = doc.get_doc_before_save()
		docs_changed = False
		if doc.meta.has_field(TASK_DOCUMENTS_FIELD):
			if not prev:
				docs_changed = bool(doc.get(TASK_DOCUMENTS_FIELD))
			else:
				prev_fp = tuple(
					sorted(
						(
							(r.get("document_type") or ""),
							(r.get("attachment") or ""),
							(r.get("draft_attachment") or ""),
						)
						for r in (prev.get(TASK_DOCUMENTS_FIELD) or [])
					)
				)
				cur_fp = tuple(
					sorted(
						(
							(r.get("document_type") or ""),
							(r.get("attachment") or ""),
							(r.get("draft_attachment") or ""),
						)
						for r in (doc.get(TASK_DOCUMENTS_FIELD) or [])
					)
				)
				docs_changed = prev_fp != cur_fp
		if docs_changed:
			refresh_project_documents(doc.project)

		# Permit project register sync only for permit tasks when rows changed.
		if task_is_permit_application(doc) or task_is_permit_finance(doc):
			from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
				permit_work_changed,
			)

			if permit_work_changed(doc) or not prev:
				sync_task_permits_to_project(doc)
		if _is_sea_task(doc):
			if task_is_permit_application(doc):
				from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
					finance_permit_task_for_application,
					permit_work_changed as _permit_rows_changed,
					sync_permit_invoices_to_finance_task,
				)

				if _permit_rows_changed(doc):
					fin_name = finance_permit_task_for_application(doc)
					if fin_name and not frappe.flags.get("cgm_permit_finance_completing"):
						sync_permit_invoices_to_finance_task(
							frappe.get_doc("Task", fin_name), save=True
						)
			from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
				sync_project_shipment_status_from_tasks,
			)

			# Shipment status only when task status itself changed.
			if not prev or prev.status != doc.status:
				sync_project_shipment_status_from_tasks(doc.project)
	prev = doc.get_doc_before_save()
	if doc.status == "Completed" and (not prev or prev.status != "Completed"):
		apply_finance_payment_to_project_permits(doc)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			close_permit_application_when_finance_done,
			close_ucr_application_when_finance_done,
			complete_permit_finance_when_application_done,
		)

		close_permit_application_when_finance_done(doc)
		close_ucr_application_when_finance_done(doc)
		# And the reverse for permits: the declarant closing the application
		# closes its Finance task too (pre- and post-clearance).
		complete_permit_finance_when_application_done(doc)
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			APPLICATION_FINANCE_PROFILES,
			profile_for_task,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
			close_application_when_finance_done,
		)

		profile = profile_for_task(doc)
		if profile and task_is_application_finance_for_profile(doc, profile):
			close_application_when_finance_done(doc, profile)

	# Last: if this save left a ready finance task Open (stale race), force Completed.
	if heal_ready_finance_task_status(doc):
		doc.reload()


def validate_task_completion_requirements(doc, _method=None):
	"""Task → Completed only when documents, permits, and payments are satisfied."""
	prev = doc.get_doc_before_save()
	if doc.status != "Completed":
		return
	if prev and prev.status == "Completed":
		return

	seq = _sea_task_seq(doc)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_auto_complete,
		task_is_configured_application_workflow,
		task_is_ucr_application,
		task_is_ucr_finance,
	)

	if (
		_is_sea_task(doc)
		and frappe.flags.get("cgm_auto_completing_sea_task")
		and (
			task_is_auto_complete(doc)
			or task_is_ucr_application(doc)
			or task_is_ucr_finance(doc)
			or task_is_configured_application_workflow(doc)
		)
	):
		return

	if _is_sea_task(doc) and task_is_auto_complete(doc):
		return

	if _is_sea_task(doc):
		# Sea steps are independent except application ↔ finance pairs (depends_on +
		# invoice-ready rules). Do not force full chart order on task completion.
		from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
			get_incomplete_finance_pair_blockers,
		)

		incomplete = get_incomplete_finance_pair_blockers(doc)
		if incomplete:
			prev_task = incomplete[0]
			frappe.throw(
				f"Complete the linked application task first. Waiting on: "
				f"<b>Task {prev_task.seq}: {prev_task.subject}</b> ({prev_task.status or 'Open'})."
			)
		validate_sea_task_can_complete(doc)

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_container_updates import (
		validate_container_step_task_completion,
		validate_book_trucks_container_updates,
	)

	validate_container_step_task_completion(doc)
	validate_book_trucks_container_updates(doc)


# ==================== CGMTask override ====================

from erpnext.projects.doctype.task.task import Task


class CGMTask(Task):
	def validate_status(self):
		"""ERPNext blocks Completed when depends_on parents are open.

		Clearance finance payment tasks intentionally stay linked to their
		application task while that application remains Open (invoice submitted).
		Allow completion in that case for every CGM clearance flow (sea, road,
		air, transit); other depends_on rules stay strict.
		"""
		from frappe import _
		from frappe.desk.form.assign_to import close_all_assignments

		if self.is_template and self.status != "Template":
			self.status = "Template"
		if self.status == "Template" and not self.is_template:
			self.status = "Open"
		if self.status != self.get_db_value("status") and self.status == "Completed":
			from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
				application_ready_for_finance,
			)

			for d in self.depends_on:
				parent_status = frappe.db.get_value("Task", d.task, "status")
				if parent_status in ("Completed", "Cancelled"):
					continue
				if _is_sea_task(self) and application_ready_for_finance(d.task):
					continue
				frappe.throw(
					_(
						"Cannot complete task {0} as its dependant task {1} are not completed / cancelled."
					).format(frappe.bold(self.name), frappe.bold(d.task))
				)

			close_all_assignments(self.doctype, self.name)

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
