"""Task Finance Lines - invoices and receipts (separate from clearance documents)."""
from __future__ import annotations

import frappe
from frappe.utils import cint, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_documents import (
	TASK_DOCUMENTS_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements_service import (
	is_ucr_application_task,
	is_ucr_finance_payment_task,
	is_ucr_workflow_task,
)

TASK_FINANCE_FIELD = "custom_task_finance_lines"

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
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import TASK_DOCUMENTS_FIELD

	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return
	for row in list(task.get(TASK_DOCUMENTS_FIELD) or []):
		if is_invoice_clearance_document_row(row.document_type):
			task.remove(row)


def ensure_idf_certificate_document_row(task) -> None:
	"""Task 3: only IDF/UCR certificate on Clearance Documents (optional until issued)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		TASK_DOCUMENTS_FIELD,
		get_document_type_link_name,
	)

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
		return row
	task.append(
		TASK_FINANCE_FIELD,
		{
			"line_label": label,
			"line_type": line_type,
			"payment_item": payment_item,
		},
	)
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

	from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
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


def ucr_payment_made_for_project(project: str) -> bool:
	"""True when Finance pays UCR has a submitted Payment Entry."""
	if not project:
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
		get_ucr_finance_task,
	)

	finance_name = get_ucr_finance_task(project)
	if not finance_name:
		return False
	pe_name = frappe.db.get_value("Task", finance_name, "custom_payment_entry")
	if not pe_name:
		return False
	return int(frappe.db.get_value("Payment Entry", pe_name, "docstatus") or 0) == 1


def copy_ucr_receipt_to_finance_task(application_task) -> str | None:
	"""Copy declarant UCR receipt onto Finance pays UCR. Returns finance task name."""
	if not is_ucr_application_task(_task_seq(application_task)) or not application_task.project:
		return None

	app_rec = _find_line(application_task, LINE_RECEIPT)
	if not app_rec or not app_rec.attachment:
		return None

	from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
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
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions_service import (
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
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
		get_document_type_code,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		SHIPMENT_DOCUMENTS_FIELD,
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

	from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
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
		from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
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

	from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
		get_ucr_finance_task,
	)

	finance_name = get_ucr_finance_task(application_task.project)
	if not finance_name:
		return False

	finance_task = frappe.get_doc("Task", finance_name)
	changed = sync_ucr_verification_to_application_task(finance_task)
	changed = sync_ucr_receipt_verification_to_application_task(finance_task) or changed
	return changed


