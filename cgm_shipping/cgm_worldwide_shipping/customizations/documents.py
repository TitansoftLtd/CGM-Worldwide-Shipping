"""Document extraction, synchronization, and validation for shipment files."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	APPROVED_WORKFLOW_STATE,
	CUSTOMER_ATTACH_TO_DOCUMENT_CODE,
	OPPORTUNITY_DOCUMENTS_FIELD,
	SHIPMENT_DOCUMENTS_FIELD,
	TASK_DOCUMENTS_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import get_field_from_meta



def get_project_documents_fieldname():
	"""Return the Project child-table fieldname for shipment documents, or None if absent."""
	project_fields = frappe.get_meta("Project")
	if project_fields.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return SHIPMENT_DOCUMENTS_FIELD
	return None


def ensure_project_documents_field():
	"""Create the Shipment Documents table on Project when it is missing."""
	# 1. Return early when the field already exists.
	if get_project_documents_fieldname():
		return SHIPMENT_DOCUMENTS_FIELD

	fieldname = SHIPMENT_DOCUMENTS_FIELD
	cf_name = f"Project-{fieldname}"

	# 2. Reload cache and return when the Custom Field record already exists.
	if frappe.db.exists("Custom Field", cf_name):
		frappe.clear_cache(doctype="Project")
		return fieldname

	# 3. Choose the best anchor field for insert_after.
	project_fields = frappe.get_meta("Project")
	insert_after = "custom_shipment_status"
	if not project_fields.has_field(insert_after):
		insert_after = "custom_shipment_type"
	if not project_fields.has_field(insert_after):
		insert_after = "customer"

	# 4. Create and insert the Custom Field.
	doc = frappe.new_doc("Custom Field")
	doc.update(
		{
			"dt": "Project",
			"fieldname": fieldname,
			"label": "Shipment Documents",
			"fieldtype": "Table",
			"options": "Shipment Document",
			"insert_after": insert_after,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.clear_cache(doctype="Project")
	return fieldname


# ─── Pre-shipment Attachment Helpers ─────────────────────────────────────────


def get_preshipment_attachments(source_doc):
	# 1. Read explicit CI/PKL attachment fields when available.
	attachments = {"CI": None, "PKL": None}
	source_fields = source_doc.meta
	for code in ("CI", "PKL"):
		fieldname = f"custom_{code.lower()}_attachment"
		if source_fields.has_field(fieldname):
			attachments[code] = source_doc.get(fieldname)

	# 2. Return early when both attachments were resolved from fields.
	if attachments["CI"] and attachments["PKL"]:
		return attachments

	# 3. Fall back to timeline file attachments for older records.
	files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": source_doc.doctype,
			"attached_to_name": source_doc.name,
			"is_folder": 0,
		},
		fields=["file_name", "file_url"],
		order_by="creation desc",
	)

	for file_row in files:
		filename = (file_row.file_name or "").lower()
		if not attachments["CI"] and (
			"commercial invoice" in filename
			or filename.startswith("ci")
			or "_ci" in filename
			or "-ci" in filename
		):
			attachments["CI"] = file_row.file_url
		if not attachments["PKL"] and (
			"packing list" in filename
			or filename.startswith("pkl")
			or "_pkl" in filename
			or "-pkl" in filename
		):
			attachments["PKL"] = file_row.file_url
		if attachments["CI"] and attachments["PKL"]:
			break

	return attachments


def resolve_document_row_status(row) -> str:
	"""Derive row status from explicit status or verification/upload metadata."""
	status = row.get("status")
	if status in ("Verified", "Rejected", "Uploaded", "Missing"):
		return status
	if row.get("verified_on"):
		return "Verified"
	if primary_attachment(row):
		return "Uploaded"
	return "Missing"


def _shipment_document_meta():
	return frappe.get_meta("Shipment Document")


def draft_document_field(meta=None) -> str | None:
	meta = meta or _shipment_document_meta()
	if meta.has_field("draft_documents"):
		return "draft_documents"
	return None


def get_draft_attachment(row) -> str:
	if not row:
		return ""
	field = draft_document_field(row.meta if hasattr(row, "meta") else None)
	if field:
		return (row.get(field) or "").strip()
	return ""


def set_draft_attachment(row, url: str) -> None:
	field = draft_document_field(row.meta if hasattr(row, "meta") else None)
	if field and url:
		setattr(row, field, url)


def has_document_versioning() -> bool:
	meta = _shipment_document_meta()
	return meta.has_field("final_attachment") or meta.has_field("draft_documents")


def _ensure_row_attachment_metadata(
	row, attach_field: str, on_field: str, by_field: str
) -> None:
	if not row.meta.has_field(on_field) or not row.meta.has_field(by_field):
		return
	if not (row.get(attach_field) or "").strip():
		return
	if row.get(on_field):
		return
	setattr(row, on_field, now_datetime())
	setattr(row, by_field, frappe.session.user)


def shipment_document_metadata_dict(row) -> dict:
	"""Serialize attachment upload audit fields when present on the row."""
	data = {}
	meta = row.meta if hasattr(row, "meta") else _shipment_document_meta()
	for attach_field, on_field, by_field in (
		("draft_documents", "draft_documents_uploaded_on", "draft_documents_uploaded_by"),
		("final_attachment", "final_document_uploaded_on", "final_document_uploaded_by"),
	):
		if not meta.has_field(attach_field):
			continue
		if row.get(attach_field):
			data[attach_field] = row.get(attach_field)
		if meta.has_field(on_field):
			data[on_field] = row.get(on_field)
		if meta.has_field(by_field):
			data[by_field] = row.get(by_field)
	if meta.has_field("uploaded_by"):
		data["uploaded_by"] = row.get("uploaded_by")
	if meta.has_field("uploaded_on"):
		data["uploaded_on"] = row.get("uploaded_on")
	for fieldname in (
		"final_document_status",
		"final_document_approved_by",
		"final_document_approved_on",
	):
		if meta.has_field(fieldname):
			data[fieldname] = row.get(fieldname)
	return data


def primary_attachment(row) -> str:
	"""Best file for portal downloads and legacy consumers."""
	if not row:
		return ""
	if has_document_versioning():
		return (
			(row.get("final_attachment") or "").strip()
			or get_draft_attachment(row)
			or (row.get("attachment") or "").strip()
		)
	return (row.get("attachment") or "").strip()


def derive_version_status(row) -> str:
	if not has_document_versioning():
		return (row.get("version_status") or "").strip()
	draft = get_draft_attachment(row)
	final = (row.get("final_attachment") or "").strip()
	legacy = (row.get("attachment") or "").strip()
	if final:
		return "Final Received"
	if draft:
		return "Awaiting Final"
	if legacy:
		return "Only Version"
	return ""


def normalize_shipment_document_row(row, *, prefer_draft_for_legacy: bool = True) -> None:
	"""Keep version_status and primary attachment in sync with draft/final slots."""
	if not row or not has_document_versioning():
		return

	legacy = (row.get("attachment") or "").strip()
	draft = get_draft_attachment(row)
	final = (row.get("final_attachment") or "").strip()

	if legacy and not draft and not final and prefer_draft_for_legacy:
		set_draft_attachment(row, legacy)
		draft = legacy

	if row.meta.has_field("version_status"):
		row.version_status = derive_version_status(row)

	row.attachment = primary_attachment(row)

	if row.attachment and row.meta.has_field("status"):
		if row.get("status") in (None, "", "Missing"):
			row.status = "Uploaded"


def resolve_document_row_slots(row) -> tuple[str, str]:
	"""Return (draft_url, final_url) from a Shipment Document row."""
	if not row:
		return "", ""
	normalize_shipment_document_row(row)
	draft = get_draft_attachment(row)
	final = (row.get("final_attachment") or "").strip()
	legacy = (row.get("attachment") or "").strip()
	version = (row.get("version_status") or "").strip()

	if not final and legacy:
		if draft and legacy != draft:
			final = legacy
		elif version == "Final Received":
			final = legacy or draft
		elif not draft:
			set_draft_attachment(row, legacy)
			draft = legacy

	if version == "Final Received" and draft and not final:
		final = draft

	return draft, final


def promote_checkpoint_task_final_uploads(task) -> None:
	"""When ops attach via Primary, move the file into Final Document on checkpoint tasks."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_document_checkpoint_task,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	if not is_document_checkpoint_task(seq):
		return
	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return

	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		draft = get_draft_attachment(row)
		final = (row.get("final_attachment") or "").strip()
		legacy = (row.get("attachment") or "").strip()
		version = (row.get("version_status") or "").strip()

		if not final and legacy and draft and legacy != draft:
			row.final_attachment = legacy
		elif not final and version == "Final Received" and legacy:
			row.final_attachment = legacy
		elif not final and version == "Final Received" and draft:
			row.final_attachment = draft
		elif not final and legacy and not draft:
			set_draft_attachment(row, legacy)

		normalize_shipment_document_row(row)


def hide_computed_shipment_document_columns() -> None:
	"""Keep Primary Attachment / Version Status off editable grids."""
	if not frappe.db.exists("DocType", "Shipment Document"):
		return
	for fieldname in ("attachment", "version_status"):
		frappe.db.set_value(
			"DocField",
			{"parent": "Shipment Document", "fieldname": fieldname},
			{"hidden": 1, "in_list_view": 0},
			update_modified=False,
		)
	frappe.clear_cache(doctype="Shipment Document")


def ensure_shipment_document_version_fields() -> None:
	"""Idempotent Custom Field installer when JSON migrate has not run yet."""
	meta = _shipment_document_meta()
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _create_cf

	if not meta.has_field("final_attachment"):
		_create_cf(
			"Shipment Document",
			{
				"fieldname": "final_attachment",
				"label": "Final Document",
				"fieldtype": "Attach",
				"insert_after": draft_document_field(meta) or "required",
				"in_list_view": 1,
			},
		)
	if not meta.has_field("version_status"):
		_create_cf(
			"Shipment Document",
			{
				"fieldname": "version_status",
				"label": "Version Status",
				"fieldtype": "Select",
				"options": "Proforma\nAwaiting Final\nFinal Received\nOnly Version",
				"insert_after": "attachment",
				"read_only": 1,
			},
		)

	if meta.has_field("attachment") or frappe.db.exists(
		"DocField", {"parent": "Shipment Document", "fieldname": "attachment"}
	):
		frappe.db.set_value(
			"DocField",
			{"parent": "Shipment Document", "fieldname": "attachment"},
			{
				"label": "Primary Attachment",
				"read_only": 1,
				"hidden": 1,
				"in_list_view": 0,
				"description": "Synced from Final Document when present, otherwise Draft Document.",
			},
			update_modified=False,
		)

	hide_computed_shipment_document_columns()
	frappe.clear_cache(doctype="Shipment Document")


def migrate_initial_attachment_to_draft_documents() -> int:
	"""Copy initial_attachment → draft_documents before the legacy field is removed."""
	meta = _shipment_document_meta()
	if not meta.has_field("initial_attachment") or not meta.has_field("draft_documents"):
		return 0
	count = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabShipment Document`
		WHERE IFNULL(initial_attachment, '') != ''
		  AND IFNULL(draft_documents, '') = ''
		"""
	)[0][0]
	if count:
		frappe.db.sql(
			"""
			UPDATE `tabShipment Document`
			SET draft_documents = initial_attachment
			WHERE IFNULL(initial_attachment, '') != ''
			  AND IFNULL(draft_documents, '') = ''
			"""
		)
	return count


def remove_initial_attachment_field() -> None:
	"""Delete the legacy Initial Document field definition and database column."""
	meta = _shipment_document_meta()
	cf_name = "Shipment Document-initial_attachment"
	if frappe.db.exists("Custom Field", cf_name):
		frappe.delete_doc("Custom Field", cf_name, force=1, ignore_permissions=True)
	for docfield in frappe.get_all(
		"DocField",
		filters={"parent": "Shipment Document", "fieldname": "initial_attachment"},
		pluck="name",
	):
		frappe.delete_doc("DocField", docfield, force=1, ignore_permissions=True)
	if meta.has_field("initial_attachment") or frappe.db.has_column(
		"Shipment Document", "initial_attachment"
	):
		frappe.db.sql_ddl("ALTER TABLE `tabShipment Document` DROP COLUMN `initial_attachment`")
	frappe.clear_cache(doctype="Shipment Document")


def migrate_legacy_shipment_document_attachments() -> None:
	"""One-time: move lone attachment values into draft_documents."""
	if not has_document_versioning():
		return
	for parenttype in ("Project", "Task", "Opportunity"):
		parentfield_map = {
			"Project": SHIPMENT_DOCUMENTS_FIELD,
			"Task": TASK_DOCUMENTS_FIELD,
			"Opportunity": OPPORTUNITY_DOCUMENTS_FIELD,
		}
		parentfield = parentfield_map.get(parenttype)
		if not parentfield:
			continue
		if parenttype == "Project" and not frappe.get_meta("Project").has_field(parentfield):
			continue
		if parenttype == "Task" and not frappe.get_meta("Task").has_field(parentfield):
			continue
		if parenttype == "Opportunity" and not frappe.get_meta("Opportunity").has_field(
			parentfield
		):
			continue

		rows = frappe.get_all(
			"Shipment Document",
			filters={
				"parenttype": parenttype,
				"parentfield": parentfield,
				"attachment": ["is", "set"],
				"draft_documents": ["is", "not set"],
				"final_attachment": ["is", "not set"],
			},
			fields=["name", "attachment"],
		)
		for row in rows:
			frappe.db.set_value(
				"Shipment Document",
				row.name,
				{
					"draft_documents": row.attachment,
					"version_status": "Only Version",
				},
				update_modified=False,
			)


def normalize_shipment_documents_table(rows) -> None:
	for row in rows or []:
		normalize_shipment_document_row(row)


def prepare_shipment_documents_for_form(doc, table_field: str) -> None:
	"""Hydrate legacy attachment into draft/final slots for form display (in-memory)."""
	if not doc.meta.has_field(table_field):
		return
	normalize_shipment_documents_table(doc.get(table_field))


def _copy_version_slots_to_row(target_row, source_row) -> bool:
	"""Copy normalized initial/final slots from source → target. Returns True if changed."""
	if not target_row or not source_row:
		return False
	normalize_shipment_document_row(source_row)
	normalize_shipment_document_row(target_row)
	changed = False
	draft_url = get_draft_attachment(source_row) or primary_attachment(source_row)
	final_url = (source_row.get("final_attachment") or "").strip()
	draft_field = draft_document_field(target_row.meta)
	if draft_url and draft_field and target_row.get(draft_field) != draft_url:
		setattr(target_row, draft_field, draft_url)
		_ensure_row_attachment_metadata(
			target_row,
			draft_field,
			"draft_documents_uploaded_on",
			"draft_documents_uploaded_by",
		)
		changed = True
	if final_url and target_row.get("final_attachment") != final_url:
		target_row.final_attachment = final_url
		_ensure_row_attachment_metadata(
			target_row,
			"final_attachment",
			"final_document_uploaded_on",
			"final_document_uploaded_by",
		)
		changed = True
	for field in ("remarks",):
		val = source_row.get(field)
		if val and target_row.get(field) != val:
			target_row.set(field, val)
			changed = True
	if changed:
		normalize_shipment_document_row(target_row)
	return changed


def _find_matching_document_row(rows, document_type):
	for row in rows or []:
		if document_types_match(row.document_type, document_type):
			return row
	return None


def upsert_shipment_document_row(
	parent_doc,
	table_field: str,
	document_type: str,
	*,
	initial_url: str | None = None,
	final_url: str | None = None,
	status: str | None = None,
	remarks: str | None = None,
	verify: bool = False,
) -> None:
	"""Append or update one Shipment Document row on any parent (Project / Task)."""
	if not document_type or not parent_doc.meta.has_field(table_field):
		return
	if not frappe.db.exists("Document Type", document_type):
		return

	rows = parent_doc.get(table_field) or []
	row = _find_matching_document_row(rows, document_type)
	if not row:
		row = parent_doc.append(
			table_field,
			{"document_type": document_type, "status": "Missing", "required": 1 if verify else 0},
		)

	file_url = (final_url or initial_url or "").strip()
	draft_field = draft_document_field(row.meta)
	if has_document_versioning():
		if initial_url and draft_field:
			setattr(row, draft_field, initial_url)
			_ensure_row_attachment_metadata(
				row,
				draft_field,
				"draft_documents_uploaded_on",
				"draft_documents_uploaded_by",
			)
		if final_url:
			row.final_attachment = final_url
			_ensure_row_attachment_metadata(
				row,
				"final_attachment",
				"final_document_uploaded_on",
				"final_document_uploaded_by",
			)
		normalize_shipment_document_row(row)
	elif file_url:
		row.attachment = file_url

	# Mirror primary file into attachment for legacy consumers / DB persistence.
	if file_url and row.meta.has_field("attachment") and not (row.get("attachment") or "").strip():
		row.attachment = file_url
	if remarks:
		row.remarks = remarks
	if has_document_versioning():
		normalize_shipment_document_row(row)

	if verify:
		row.required = 1
	if status:
		row.status = status
	elif verify:
		row.status = "Verified"
	elif primary_attachment(row) and row.get("status") == "Missing":
		row.status = "Uploaded"

	if verify and primary_attachment(row):
		row.verified_by = row.get("verified_by") or frappe.session.user
		row.verified_on = row.get("verified_on") or now_datetime()


def serialize_clients_document_row(row) -> dict:
	"""Dict for re-appending a Clients Documents / Shipment Document child row."""
	normalize_shipment_document_row(row)
	data = {
		"document_type": row.document_type,
		"status": row.status,
		"verified_by": row.get("verified_by"),
		"verified_on": row.get("verified_on"),
		"remarks": row.remarks,
	}
	data.update(shipment_document_metadata_dict(row))
	if has_document_versioning():
		data["attachment"] = primary_attachment(row)
		if row.meta.has_field("version_status"):
			data["version_status"] = row.get("version_status")
	else:
		data["attachment"] = primary_attachment(row) or row.get("attachment")
	return data


def prepend_clients_document_row(
	parent_doc,
	table_field: str,
	document_type: str,
	attachment_url: str,
	*,
	status: str = "Uploaded",
	remarks: str | None = None,
) -> bool:
	"""Insert one document row first, preserving other rows (Opportunity Clients Documents)."""
	if not attachment_url or not document_type or not parent_doc.meta.has_field(table_field):
		return False
	if not frappe.db.exists("Document Type", document_type):
		return False

	existing = list(parent_doc.get(table_field) or [])
	other_rows = [
		row for row in existing if not document_types_match(row.document_type, document_type)
	]

	parent_doc.set(table_field, [])
	upsert_shipment_document_row(
		parent_doc,
		table_field,
		document_type,
		initial_url=attachment_url,
		status=status,
		remarks=remarks,
	)

	rows = parent_doc.get(table_field) or []
	if rows and rows[0].meta.has_field("draft_documents_uploaded_by"):
		_ensure_row_attachment_metadata(
			rows[0],
			draft_document_field(rows[0].meta) or "draft_documents",
			"draft_documents_uploaded_on",
			"draft_documents_uploaded_by",
		)
	elif rows and rows[0].meta.has_field("uploaded_by"):
		if not rows[0].get("uploaded_by"):
			rows[0].uploaded_by = frappe.session.user
		if not rows[0].get("uploaded_on"):
			rows[0].uploaded_on = now_datetime()

	for row in other_rows:
		parent_doc.append(table_field, serialize_clients_document_row(row))
	return True


def normalize_opportunity_clients_documents(doc, _method=None) -> None:
	"""Hydrate initial/final slots on Opportunity Clients Documents before save."""
	if doc.doctype != "Opportunity":
		return
	field = get_opportunity_documents_field()
	if not field or not doc.meta.has_field(field):
		return
	from cgm_shipping.cgm_worldwide_shipping.doctype.shipment_document.shipment_document import (
		stamp_shipment_document_upload_metadata,
	)

	stamp_shipment_document_upload_metadata(doc, field)
	normalize_shipment_documents_table(doc.get(field))


def seed_checkpoint_task_documents_from_project(task) -> bool:
	"""Document-checkpoint tasks mirror Project rows (initial + any existing final)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_document_checkpoint_task,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	if not is_document_checkpoint_task(seq) or not task.project:
		return False
	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return False
	if not frappe.db.exists("Project", task.project):
		return False

	project = frappe.get_doc("Project", task.project)
	if not project.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return False

	source_rows = [
		r
		for r in project.get(SHIPMENT_DOCUMENTS_FIELD) or []
		if r.document_type and (primary_attachment(r) or get_draft_attachment(r) or r.get("final_attachment"))
	]
	if not source_rows:
		return False

	changed = False
	task_rows = list(task.get(TASK_DOCUMENTS_FIELD) or [])
	if task_rows:
		return False
	for prow in source_rows:
		normalize_shipment_document_row(prow)
		trow = _find_matching_document_row(task_rows, prow.document_type)
		if not trow:
			trow = task.append(
				TASK_DOCUMENTS_FIELD,
				{"document_type": prow.document_type, "status": "Missing"},
			)
			task_rows.append(trow)
			changed = True

		if _copy_version_slots_to_row(trow, prow):
			changed = True
		if trow.get("status") == "Missing" and primary_attachment(trow):
			trow.status = prow.get("status") or "Uploaded"
			changed = True

	return changed


def backfill_checkpoint_task_documents_from_project(task) -> bool:
	"""Fill missing initial/final slots on existing checkpoint rows from Project."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_document_checkpoint_task,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	if not is_document_checkpoint_task(seq) or not task.project:
		return False
	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return False
	if not frappe.db.exists("Project", task.project):
		return False

	project = frappe.get_doc("Project", task.project)
	if not project.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return False

	changed = False
	project_rows = list(project.get(SHIPMENT_DOCUMENTS_FIELD) or [])
	for trow in task.get(TASK_DOCUMENTS_FIELD) or []:
		if not trow.document_type:
			continue
		normalize_shipment_document_row(trow)
		prow = _find_matching_document_row(project_rows, trow.document_type)
		if not prow:
			continue
		needs_draft = not get_draft_attachment(trow)
		needs_final = not (trow.get("final_attachment") or "").strip()
		if not needs_draft and not needs_final:
			continue
		if _copy_version_slots_to_row(trow, prow):
			changed = True
	return changed


@frappe.whitelist()
def ensure_checkpoint_task_documents(task_name: str) -> dict:
	"""Seed document-checkpoint task rows from Project (client reloads after)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_document_checkpoint_task,
	)

	task = frappe.get_doc("Task", task_name)
	frappe.has_permission("Task", ptype="write", doc=task, throw=True)
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_document_checkpoint_task(seq):
		return {"seeded": False}

	if task.get(TASK_DOCUMENTS_FIELD):
		if backfill_checkpoint_task_documents_from_project(task):
			frappe.flags.cgm_syncing_checkpoint_documents = True
			try:
				task.save(ignore_permissions=True)
			finally:
				frappe.flags.cgm_syncing_checkpoint_documents = False
			return {"seeded": False, "backfilled": True}
		return {"seeded": False}

	if not seed_checkpoint_task_documents_from_project(task):
		return {"seeded": False}

	frappe.flags.cgm_syncing_checkpoint_documents = True
	try:
		task.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_syncing_checkpoint_documents = False
	return {"seeded": True}


def apply_checkpoint_task_documents_to_project(project_doc, task) -> bool:
	"""Merge document-checkpoint task rows onto Project (in-memory only)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_document_checkpoint_task,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	if not is_document_checkpoint_task(seq):
		return False
	if not project_doc.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return False
	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return False

	changed = False
	for trow in task.get(TASK_DOCUMENTS_FIELD) or []:
		if not trow.document_type:
			continue
		initial_url, final_url = resolve_document_row_slots(trow)
		if not final_url and not initial_url:
			continue

		prow = _find_matching_document_row(
			project_doc.get(SHIPMENT_DOCUMENTS_FIELD) or [], trow.document_type
		)
		if not prow:
			prow = project_doc.append(
				SHIPMENT_DOCUMENTS_FIELD,
				{"document_type": trow.document_type, "status": "Missing"},
			)
			changed = True

		draft_field = draft_document_field(prow.meta)
		if initial_url and draft_field and prow.get(draft_field) != initial_url:
			setattr(prow, draft_field, initial_url)
			_ensure_row_attachment_metadata(
				prow,
				draft_field,
				"draft_documents_uploaded_on",
				"draft_documents_uploaded_by",
			)
			changed = True
		if final_url and prow.get("final_attachment") != final_url:
			prow.final_attachment = final_url
			_ensure_row_attachment_metadata(
				prow,
				"final_attachment",
				"final_document_uploaded_on",
				"final_document_uploaded_by",
			)
			changed = True
		if initial_url or final_url:
			normalize_shipment_document_row(prow)
			changed = True

	return changed


def merge_checkpoint_task_documents_into_project(project_doc) -> bool:
	"""Pull initial/final slots from all document-checkpoint tasks on this Project."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		document_checkpoint_sequences,
		get_task_name_by_sequence,
	)

	if not project_doc.name:
		return False

	changed = False
	for seq in document_checkpoint_sequences():
		task_name = get_task_name_by_sequence(project_doc.name, seq)
		if not task_name:
			continue
		task = frappe.get_doc("Task", task_name)
		if apply_checkpoint_task_documents_to_project(project_doc, task):
			changed = True
	return changed


def sync_checkpoint_finals_to_project(task) -> bool:
	"""Push final (and new initial) document slots from checkpoint task → Project."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_document_checkpoint_task,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	if not is_document_checkpoint_task(seq) or not task.project:
		return False
	if frappe.flags.get("cgm_syncing_shipment_documents"):
		return False

	project = frappe.get_doc("Project", task.project)
	if not apply_checkpoint_task_documents_to_project(project, task):
		return False

	frappe.flags.cgm_syncing_shipment_documents = True
	try:
		project.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_syncing_shipment_documents = False
	return True


def document_types_match(existing_type, incoming_type):
	"""Match Document Type rows by link name or shared code (e.g. CI vs Commercial Invoice)."""
	if not existing_type or not incoming_type:
		return False
	if existing_type == incoming_type:
		return True
	existing_code = frappe.db.get_value("Document Type", existing_type, "code")
	incoming_code = frappe.db.get_value("Document Type", incoming_type, "code")
	return bool(existing_code and incoming_code and existing_code == incoming_code)


def is_shipment_document_verified(row) -> bool:
	"""True when a Shipment Document row is verified."""
	if row.meta.has_field("status") and row.get("status") == "Verified":
		return True
	return bool(row.get("verified_on"))


def append_verified_doc_row(project_doc, document_type, attachment_url, *, slot: str = "initial"):
	"""Add or update a verified Project shipment document (defaults to initial/pre-shipment slot)."""
	if not attachment_url or not document_type:
		return
	if not frappe.db.exists("Document Type", document_type):
		return
	if not project_doc.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return

	kwargs = {"verify": True}
	if slot == "final":
		kwargs["final_url"] = attachment_url
	else:
		kwargs["initial_url"] = attachment_url
	upsert_shipment_document_row(
		project_doc,
		SHIPMENT_DOCUMENTS_FIELD,
		document_type,
		**kwargs,
	)


DOCUMENT_TYPE_DEFAULTS = {
	"CI": {
		"category": "Commercial",
		"default_required": 1,
		"required_stage": "Pre-IDF",
	},
	"PKL": {
		"category": "Commercial",
		"default_required": 1,
		"required_stage": "Pre-IDF",
	},
	"KRA_PIN": {
		"category": "Compliance",
		"default_required": 1,
		"required_stage": "Pre-IDF",
	},
	"BL": {
		"category": "Transport",
		"default_required": 0,
		"required_stage": "Pre-IDF",
	},
	"AWB": {
		"category": "Transport",
		"default_required": 0,
		"required_stage": "Arrival & manifest",
	},
	"BOOKING": {
		"category": "Transport",
		"default_required": 0,
		"required_stage": "Pre-IDF",
	},
}

def ensure_document_types():
	"""Ensure Document Type master rows exist for synced shipment files."""
	for code, defaults in DOCUMENT_TYPE_DEFAULTS.items():
		if get_document_type_link_name(code):
			continue

		# 1. Create and submit the Document Type when it does not yet exist.
		doc = frappe.new_doc("Document Type")
		doc.code = code
		for key, value in defaults.items():
			setattr(doc, key, value)
		doc.insert(ignore_permissions=True)
		if doc.meta.is_submittable and doc.docstatus == 0:
			doc.submit()


def carry_preshipment_docs_to_project(project_doc, source_doc):
	"""Copy CI and PKL attachments from a Lead/Opportunity into Project shipment document rows."""
	ensure_document_types()
	attachments = get_preshipment_attachments(source_doc)
	for code in ("CI", "PKL"):
		attachment_url = attachments.get(code)
		if not attachment_url:
			continue
		document_type = get_document_type_link_name(code)
		if document_type:
			append_verified_doc_row(project_doc, document_type, attachment_url)


def carry_clients_documents_to_project(project_doc, source_doc) -> None:
	"""Copy all Clients Documents rows from Opportunity onto Project shipment documents."""
	if not source_doc or not source_doc.meta.has_field(OPPORTUNITY_DOCUMENTS_FIELD):
		return
	if not project_doc.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return

	ensure_document_types()
	source_is_approved_opp = (
		source_doc.doctype == "Opportunity"
		and source_doc.get("workflow_state") == APPROVED_WORKFLOW_STATE
	)
	for row in source_doc.get(OPPORTUNITY_DOCUMENTS_FIELD) or []:
		if not row.document_type:
			continue
		if not (primary_attachment(row) or row.get("attachment")):
			continue
		if not frappe.db.exists("Document Type", row.document_type):
			continue
		_append_or_update_shipment_document_row(
			project_doc,
			row,
			verify_from_approved_opportunity=source_is_approved_opp,
		)


def _append_or_update_shipment_document_row(
	project_doc, source_row, *, verify_from_approved_opportunity: bool = False
) -> None:
	draft = get_draft_attachment(source_row)
	final = source_row.get("final_attachment")
	legacy = source_row.get("attachment")
	status = resolve_document_row_status(source_row)
	verify = status == "Verified" or verify_from_approved_opportunity
	if has_document_versioning():
		upsert_shipment_document_row(
			project_doc,
			SHIPMENT_DOCUMENTS_FIELD,
			source_row.document_type,
			initial_url=draft or legacy,
			final_url=final,
			status="Verified" if verify else status,
			remarks=source_row.get("remarks"),
			verify=verify,
		)
		return

	rows = project_doc.get(SHIPMENT_DOCUMENTS_FIELD) or []
	for existing in rows:
		if not document_types_match(existing.document_type, source_row.document_type):
			continue
		if not existing.attachment:
			existing.attachment = legacy
		if verify:
			if existing.meta.has_field("status"):
				existing.status = "Verified"
			existing.verified_by = existing.verified_by or source_row.verified_by or frappe.session.user
			existing.verified_on = existing.verified_on or source_row.verified_on or now_datetime()
		elif existing.meta.has_field("status") and status != "Missing":
			existing.status = status
		for field in (
			"draft_documents_uploaded_on",
			"draft_documents_uploaded_by",
			"final_document_uploaded_on",
			"final_document_uploaded_by",
			"uploaded_by",
			"uploaded_on",
			"verified_by",
			"verified_on",
			"remarks",
		):
			if not existing.meta.has_field(field):
				continue
			value = source_row.get(field)
			if value and not existing.get(field):
				existing.set(field, value)
		return

	row_data = {
		"document_type": source_row.document_type,
		"attachment": legacy,
		"verified_by": source_row.get("verified_by"),
		"verified_on": source_row.get("verified_on"),
		"remarks": source_row.remarks,
	}
	row_data.update(shipment_document_metadata_dict(source_row))
	if frappe.get_meta("Shipment Document").has_field("status"):
		row_data["status"] = "Verified" if verify else status
	if verify:
		row_data["verified_by"] = row_data["verified_by"] or frappe.session.user
		row_data["verified_on"] = row_data["verified_on"] or now_datetime()
	project_doc.append(SHIPMENT_DOCUMENTS_FIELD, row_data)


def get_bill_of_lading_attachment_url(
	bl_name: str | None = None, source_doc=None
) -> str | None:
	"""Resolve BL file URL from the Bill of Lading record or source Clients Documents."""
	if bl_name and frappe.db.exists("Bill of Lading", bl_name):
		from cgm_shipping.cgm_worldwide_shipping.customizations.utils import get_bl_config

		attachment_field = get_bl_config().get("attachment_field")
		if attachment_field and frappe.get_meta("Bill of Lading").has_field(attachment_field):
			attachment_url = frappe.db.get_value("Bill of Lading", bl_name, attachment_field)
			if attachment_url:
				return attachment_url

	if not source_doc:
		return None

	clients_field = OPPORTUNITY_DOCUMENTS_FIELD
	if not source_doc.meta.has_field(clients_field):
		return None

	bl_type = get_document_type_link_name("BL")
	if not bl_type:
		return None

	for row in source_doc.get(clients_field) or []:
		if document_types_match(row.document_type, bl_type) and primary_attachment(row):
			return primary_attachment(row)
	return None


def carry_bill_of_lading_attachment_to_project(
	project_doc, bl_name: str | None = None, source_doc=None
) -> None:
	"""Add the Bill of Lading file to Project shipment documents (type BL)."""
	ensure_document_types()
	bl_name = bl_name or project_doc.get("custom_bill_of_lading")
	attachment_url = get_bill_of_lading_attachment_url(bl_name, source_doc)
	if not attachment_url:
		return

	document_type = get_document_type_link_name("BL")
	if document_type:
		append_verified_doc_row(project_doc, document_type, attachment_url)


def carry_customer_attachments_to_project(project_doc, customer_ref):
	"""Copy Customer attach fields (e.g. KRA PIN) into Project shipment document rows."""
	if not customer_ref:
		return
	if getattr(customer_ref, "doctype", None) == "Customer":
		customer_doc = customer_ref
	else:
		if not frappe.db.exists("Customer", customer_ref):
			return
		customer_doc = frappe.get_doc("Customer", customer_ref)

	customer_fields = frappe.get_meta("Customer")
	for fieldname, code in CUSTOMER_ATTACH_TO_DOCUMENT_CODE.items():
		if not customer_fields.has_field(fieldname):
			continue
		attachment_url = customer_doc.get(fieldname)
		if not attachment_url:
			continue
		document_type = get_document_type_link_name(code)
		if document_type:
			append_verified_doc_row(project_doc, document_type, attachment_url)


def append_task_document_row(task_doc, document_type, attachment_url, status=None, remarks=None):
	"""Append or update a Shipment Document row on a Task."""
	if not attachment_url or not document_type:
		return
	if not task_doc.meta.has_field(TASK_DOCUMENTS_FIELD):
		return

	upsert_shipment_document_row(
		task_doc,
		TASK_DOCUMENTS_FIELD,
		document_type,
		initial_url=attachment_url,
		status=status or "Verified",
		remarks=remarks or "Carried from Project (approved on Lead/Opportunity/Customer)",
		verify=(status or "Verified") == "Verified",
	)


def carry_project_documents_to_sea_tasks(project_name, task_sequences=None):
	"""
	Copy Project shipment document rows onto sea clearance tasks (audit trail on Task 1–2).
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		auto_complete_sequences,
		get_task_name_by_sequence,
	)

	if not project_name or not frappe.db.exists("Project", project_name):
		return []
	if not frappe.get_meta("Task").has_field(TASK_DOCUMENTS_FIELD):
		return []

	task_sequences = task_sequences or sorted(auto_complete_sequences())
	project = frappe.get_doc("Project", project_name)
	source_rows = [
		r
		for r in project.get(SHIPMENT_DOCUMENTS_FIELD) or []
		if r.document_type and primary_attachment(r)
	]
	if not source_rows:
		return []

	updated_tasks = []
	for seq in task_sequences:
		task_name = get_task_name_by_sequence(project_name, seq)
		if not task_name:
			continue
		task = frappe.get_doc("Task", task_name)
		for row in source_rows:
			append_task_document_row(
				task,
				row.document_type,
				primary_attachment(row),
				status=row.status or "Verified",
				remarks=row.remarks
				or "Carried from Project (approved on Lead/Opportunity/Customer)",
			)
		frappe.flags.cgm_syncing_shipment_documents = True
		try:
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_shipment_documents = False
		updated_tasks.append(task_name)
	return updated_tasks


def carry_task_documents_to_project(project_doc, project_name=None):
	"""Copy Task Documents child rows from all tasks on this project."""
	project_name = project_name or project_doc.name
	if not project_name:
		return False

	task_fields = frappe.get_meta("Task")
	if not task_fields.has_field("custom_task_documents"):
		return False

	changed = False
	for task_name in frappe.get_all("Task", filters={"project": project_name}, pluck="name"):
		task_doc = frappe.get_doc("Task", task_name)
		for row in task_doc.get("custom_task_documents") or []:
			if not row.document_type:
				continue
			initial_url, final_url = resolve_document_row_slots(row)
			if not initial_url and not final_url:
				continue
			if has_document_versioning():
				before = _find_matching_document_row(
					project_doc.get(SHIPMENT_DOCUMENTS_FIELD) or [], row.document_type
				)
				upsert_shipment_document_row(
					project_doc,
					SHIPMENT_DOCUMENTS_FIELD,
					row.document_type,
					initial_url=initial_url,
					final_url=final_url or None,
					status=row.get("status"),
					remarks=row.get("remarks"),
				)
				after = _find_matching_document_row(
					project_doc.get(SHIPMENT_DOCUMENTS_FIELD) or [], row.document_type
				)
				if not before and after:
					changed = True
				elif before and after and (
					get_draft_attachment(before) != get_draft_attachment(after)
					or before.get("final_attachment") != after.get("final_attachment")
				):
					changed = True
			elif row.attachment:
				append_verified_doc_row(project_doc, row.document_type, row.attachment)
				changed = True
	return changed


def sync_single_task_documents_to_project(task) -> bool:
	"""Push this task's document rows onto the Project (manifest, DO, etc.)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_document_checkpoint_task,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	if is_document_checkpoint_task(seq):
		return False
	if not task.project or not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return False
	if frappe.flags.get("cgm_syncing_shipment_documents"):
		return False

	project = frappe.get_doc("Project", task.project)
	if not project.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return False

	changed = False
	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		if not row.document_type:
			continue
		initial_url, final_url = resolve_document_row_slots(row)
		if not initial_url and not final_url:
			continue
		prow = _find_matching_document_row(
			project.get(SHIPMENT_DOCUMENTS_FIELD) or [], row.document_type
		)
		upsert_shipment_document_row(
			project,
			SHIPMENT_DOCUMENTS_FIELD,
			row.document_type,
			initial_url=initial_url,
			final_url=final_url or None,
			status=row.get("status"),
			remarks=row.get("remarks"),
		)
		changed = True

	if changed:
		frappe.flags.cgm_syncing_shipment_documents = True
		try:
			project.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_shipment_documents = False
	return changed


def sync_project_documents_from_opportunity(
	project_doc, opportunity_doc, *, replace=False
) -> None:
	"""Copy Opportunity Clients Documents exactly, plus Customer KRA PIN only."""
	if not project_doc.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return

	ensure_document_types()
	if replace:
		project_doc.set(SHIPMENT_DOCUMENTS_FIELD, [])

	if opportunity_doc:
		carry_clients_documents_to_project(project_doc, opportunity_doc)

	customer = project_doc.get("customer") or (
		opportunity_doc.get("party_name") if opportunity_doc else None
	)
	if customer:
		carry_customer_attachments_to_project(project_doc, customer)


def sync_linked_attachments_to_project(project_doc):
	"""Pull shipment files from linked Lead, Customer, and Project tasks into custom_shipment_documents."""
	if not project_doc.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return

	ensure_document_types()

	# Opportunity-sourced projects inherit only Clients Documents + Customer KRA PIN.
	opp_name = project_doc.get("custom_source_opportunity")
	if opp_name and frappe.db.exists("Opportunity", opp_name):
		opp_doc = frappe.get_doc("Opportunity", opp_name)
		sync_project_documents_from_opportunity(project_doc, opp_doc)
		return

	# 1. Lead (explicit source or via customer).
	lead_name = project_doc.get("custom_source_lead")
	if not lead_name and project_doc.get("customer"):
		lead_name = frappe.db.get_value("Customer", project_doc.customer, "lead_name")
	if lead_name and frappe.db.exists("Lead", lead_name):
		lead_doc = frappe.get_doc("Lead", lead_name)
		carry_preshipment_docs_to_project(project_doc, lead_doc)
		carry_bill_of_lading_attachment_to_project(
			project_doc,
			bl_name=project_doc.get("custom_bill_of_lading") or lead_doc.get("custom_bill_of_lading"),
			source_doc=lead_doc,
		)

	# 2. Customer attach fields (KRA PIN, etc.).
	if project_doc.get("customer"):
		carry_customer_attachments_to_project(project_doc, project_doc.customer)

	# 3. Task Documents on tasks linked to this project.
	if project_doc.name:
		carry_task_documents_to_project(project_doc)


def refresh_project_documents(project_name):
	"""Re-sync shipment document rows from linked Customer / Tasks and save the Project."""
	if not project_name or not frappe.db.exists("Project", project_name):
		return
	if frappe.flags.cgm_syncing_shipment_documents:
		return

	frappe.flags.cgm_syncing_shipment_documents = True
	try:
		from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
			normalize_shipment_fields_on_doc,
		)

		project = frappe.get_doc("Project", project_name)
		normalize_shipment_fields_on_doc(project)
		opp_name = project.get("custom_source_opportunity")
		if opp_name and frappe.db.exists("Opportunity", opp_name):
			opp_doc = frappe.get_doc("Opportunity", opp_name)
			sync_project_documents_from_opportunity(project, opp_doc, replace=True)
		else:
			sync_linked_attachments_to_project(project)
		merge_checkpoint_task_documents_into_project(project)
		carry_task_documents_to_project(project)
		project.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_syncing_shipment_documents = False


def refresh_projects_for_customer(customer):
	"""Update shipment documents on every Project for this Customer."""
	if not customer:
		return
	for project_name in frappe.get_all("Project", filters={"customer": customer}, pluck="name"):
		refresh_project_documents(project_name)


@frappe.whitelist()
def sync_project_documents_from_tasks(project_name: str) -> dict:
	"""Backfill Project shipment documents from all linked Task document rows."""
	frappe.has_permission("Project", ptype="write", throw=True)
	if not project_name or not frappe.db.exists("Project", project_name):
		frappe.throw(_("Project not found"))

	project = frappe.get_doc("Project", project_name)
	merge_checkpoint_task_documents_into_project(project)
	carry_task_documents_to_project(project)
	frappe.flags.cgm_syncing_shipment_documents = True
	try:
		project.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_syncing_shipment_documents = False
	return {"updated": True, "project": project_name}


@frappe.whitelist()
def sync_project_finals_from_checkpoint(project_name: str) -> dict:
	"""Backfill Project Final Document from Task 9 checkpoint rows."""
	frappe.has_permission("Project", ptype="write", throw=True)
	if not project_name or not frappe.db.exists("Project", project_name):
		frappe.throw(_("Project not found"))

	project = frappe.get_doc("Project", project_name)
	changed = merge_checkpoint_task_documents_into_project(project)
	if changed:
		frappe.flags.cgm_syncing_shipment_documents = True
		try:
			project.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_shipment_documents = False
	return {"updated": changed, "project": project_name}


@frappe.whitelist()
def sync_project_documents(project):
	"""Re-pull Lead / Customer / Task files into Project shipment documents (for support / backfill)."""
	frappe.has_permission("Project", ptype="write", throw=True)
	refresh_project_documents(project)
	return project


def get_document_type_link_name(code):
	"""Resolve the Document Type name for child table links."""
	if not code:
		return None

	# 1. Prefer a match on the code field.
	name = frappe.db.get_value("Document Type", {"code": code}, "name")
	if name:
		return name

	# 2. Fall back to using the code directly as the document name.
	if frappe.db.exists("Document Type", code):
		return code

	return None

@frappe.request_cache
def get_opportunity_documents_field() -> str | None:
	"""Clients Documents table fieldname on Opportunity."""
	return get_field_from_meta("Opportunity", "clients_documents") or next(
		(
			field.fieldname
			for field in frappe.get_meta("Opportunity").fields
			if field.fieldtype == "Table" and "clients_documents" in field.fieldname
		),
		None,
	)


@frappe.request_cache
def get_project_shipment_documents_field() -> str | None:
	"""Shipment Documents table fieldname on Project."""
	if frappe.get_meta("Project").has_field(SHIPMENT_DOCUMENTS_FIELD):
		return SHIPMENT_DOCUMENTS_FIELD
	return get_field_from_meta("Project", "shipment_documents")


# Backward-compatible alias
get_project_documents_field = get_project_shipment_documents_field


# Backward-compatible aliases
refresh_project_shipment_documents = refresh_project_documents
sync_documents = sync_linked_attachments_to_project
