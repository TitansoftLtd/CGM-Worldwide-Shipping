"""One-time: move Container Tracker deposit data onto Bill of Lading + Container child.

Runs after ensure_container_deposit_fields. Idempotent when tracker deposit columns
are already gone. Drops legacy tracker columns after data is copied.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt

_TRACKER_DEPOSIT_COLUMNS = (
	"has_deposit",
	"deposit_amount",
	"deposit_payment_status",
	"deposit_payment_journal_entry",
	"deposit_refund_journal_entry",
	"deposit_refund_status",
	"deposit_refund_applied_on",
	"deposit_return_date",
	"deposit_refund_last_reminded_on",
)


def execute() -> None:
	existing = _existing_tracker_deposit_columns()
	if not existing:
		return

	_migrate_tracker_deposits_to_bl(existing)
	_drop_tracker_deposit_columns(existing)
	frappe.db.commit()


def _existing_tracker_deposit_columns() -> list[str]:
	if not frappe.db.table_exists("Container Tracker"):
		return []
	present = []
	for col in _TRACKER_DEPOSIT_COLUMNS:
		if frappe.db.has_column("Container Tracker", col):
			present.append(col)
	return present


def _migrate_tracker_deposits_to_bl(columns: list[str]) -> None:
	if "has_deposit" not in columns:
		return

	select_cols = ["name", "project", "bl_number", "container_number"] + [
		c for c in columns if c not in ("name", "project", "bl_number", "container_number")
	]
	where_parts = ["IFNULL(`has_deposit`, 0) = 1"]
	if "deposit_amount" in columns:
		where_parts.append("IFNULL(`deposit_amount`, 0) > 0")
	rows = frappe.db.sql(
		f"""
		SELECT {", ".join(f"`{c}`" for c in select_cols)}
		FROM `tabContainer Tracker`
		WHERE {" OR ".join(where_parts)}
		""",
		as_dict=True,
	)
	if not rows:
		return

	bl_meta = frappe.get_meta("Bill of Lading")
	if not bl_meta.has_field("has_deposit"):
		return

	# Group trackers by resolved BL
	by_bl: dict[str, list] = {}
	for row in rows:
		bl_name = _resolve_bl_for_tracker(row)
		if not bl_name:
			continue
		by_bl.setdefault(bl_name, []).append(row)

	for bl_name, trackers in by_bl.items():
		_apply_trackers_to_bl(bl_name, trackers, bl_meta)


def _resolve_bl_for_tracker(row) -> str | None:
	project = (row.get("project") or "").strip()
	if project and frappe.db.exists("Project", project):
		bl = frappe.db.get_value("Project", project, "custom_bill_of_lading")
		if bl and frappe.db.exists("Bill of Lading", bl):
			return bl
	bl_number = (row.get("bl_number") or "").strip()
	if bl_number and frappe.db.exists("Bill of Lading", bl_number):
		return bl_number
	return None


def _apply_trackers_to_bl(bl_name: str, trackers: list, bl_meta) -> None:
	# Per-container child flags/amounts (db update — avoid BL validate on incomplete docs)
	by_number = {
		(t.get("container_number") or "").strip().upper(): t
		for t in trackers
		if (t.get("container_number") or "").strip()
	}
	by_tracker = {t.name: t for t in trackers}

	for child in frappe.get_all(
		"Container",
		filters={"parent": bl_name, "parenttype": "Bill of Lading"},
		fields=["name", "container_number", "container_tracker", "has_deposit", "deposit_amount"],
	):
		src = None
		key = (child.get("container_number") or "").strip().upper()
		if key and key in by_number:
			src = by_number[key]
		elif child.get("container_tracker") and child.container_tracker in by_tracker:
			src = by_tracker[child.container_tracker]
		if not src:
			continue
		if cint(src.get("has_deposit")) or flt(src.get("deposit_amount")) > 0:
			updates = {"has_deposit": 1}
			amt = flt(src.get("deposit_amount"))
			if amt:
				updates["deposit_amount"] = amt
			frappe.db.set_value("Container", child.name, updates, update_modified=False)

	header: dict = {}
	if bl_meta.has_field("has_deposit") and not cint(
		frappe.db.get_value("Bill of Lading", bl_name, "has_deposit")
	):
		header["has_deposit"] = 1

	payment_src = next((t for t in trackers if t.get("deposit_payment_journal_entry")), None)
	refund_src = next((t for t in trackers if t.get("deposit_refund_journal_entry")), None)
	status_src = next(
		(t for t in trackers if (t.get("deposit_payment_status") or "") in ("Paid", "Unpaid")),
		trackers[0],
	)

	def _set_if_empty(field: str, value) -> None:
		if not bl_meta.has_field(field) or value in (None, ""):
			return
		current = frappe.db.get_value("Bill of Lading", bl_name, field)
		if current:
			return
		header[field] = value

	if payment_src:
		_set_if_empty(
			"deposit_payment_journal_entry",
			payment_src.get("deposit_payment_journal_entry"),
		)
	if refund_src:
		_set_if_empty(
			"deposit_refund_journal_entry",
			refund_src.get("deposit_refund_journal_entry"),
		)
		_set_if_empty(
			"deposit_refund_status",
			refund_src.get("deposit_refund_status") or "Received",
		)
		_set_if_empty(
			"deposit_refund_applied_on",
			refund_src.get("deposit_refund_applied_on"),
		)

	if status_src:
		_set_if_empty("deposit_refund_status", status_src.get("deposit_refund_status"))
		_set_if_empty("deposit_return_date", status_src.get("deposit_return_date"))
		_set_if_empty(
			"deposit_refund_last_reminded_on",
			status_src.get("deposit_refund_last_reminded_on"),
		)

	if bl_meta.has_field("deposit_return_date"):
		dates = [t.get("deposit_return_date") for t in trackers if t.get("deposit_return_date")]
		if dates and not frappe.db.get_value("Bill of Lading", bl_name, "deposit_return_date"):
			header["deposit_return_date"] = min(dates)

	# Roll up amount + payment status without full document validate
	total = flt(
		frappe.db.sql(
			"""
			SELECT SUM(IFNULL(deposit_amount, 0))
			FROM `tabContainer`
			WHERE parent=%s AND parenttype='Bill of Lading' AND IFNULL(has_deposit, 0)=1
			""",
			bl_name,
		)[0][0]
	)
	if bl_meta.has_field("deposit_amount"):
		header["deposit_amount"] = total

	je = None
	if payment_src:
		je = payment_src.get("deposit_payment_journal_entry")
	if not je and bl_meta.has_field("deposit_payment_journal_entry"):
		je = header.get("deposit_payment_journal_entry") or frappe.db.get_value(
			"Bill of Lading", bl_name, "deposit_payment_journal_entry"
		)
	if bl_meta.has_field("deposit_payment_status"):
		if je and frappe.db.get_value("Journal Entry", je, "docstatus") == 1:
			header["deposit_payment_status"] = "Paid"
		elif cint(header.get("has_deposit", 1)) or cint(
			frappe.db.get_value("Bill of Lading", bl_name, "has_deposit")
		):
			if not frappe.db.get_value("Bill of Lading", bl_name, "deposit_payment_status") in (
				"Paid",
			):
				header.setdefault("deposit_payment_status", "Unpaid")

	if header:
		frappe.db.set_value("Bill of Lading", bl_name, header, update_modified=False)


def _drop_tracker_deposit_columns(columns: list[str]) -> None:
	for col in columns:
		try:
			frappe.db.sql_ddl(
				f"ALTER TABLE `tabContainer Tracker` DROP COLUMN `{col}`"
			)
		except Exception:
			frappe.log_error(
				title=f"Drop Container Tracker column {col}",
				message=frappe.get_traceback(),
			)
