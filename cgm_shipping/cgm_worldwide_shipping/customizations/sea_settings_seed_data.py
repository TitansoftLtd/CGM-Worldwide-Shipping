"""Default CGM Shipping Settings rows for migrate patches only (not imported at runtime)."""

from __future__ import annotations

SUPPLIER_INVOICE_CODE = "SUP_INV"

DEFAULT_SEA_IMPORT_TASK_TEMPLATE: list[dict[str, str]] = [
	{"task_subject": "Receive shipment documents from Client", "department": "Operations"},
	{"task_subject": "Share documents with Declarants", "department": "Operations"},
	{"task_subject": "Create UCR (IDF)", "department": "Declaration"},
	{"task_subject": "Finance pays UCR", "department": "Finance"},
	{
		"task_subject": "Apply for Pre-Clearance Permits (DVS, NBA, VMD, ACA)",
		"department": "Declaration",
	},
	{"task_subject": "Finance pays Pre-Clearance Permits", "department": "Finance"},
	{"task_subject": "Client conducts inspection", "department": "Operations"},
	{
		"task_subject": "Receive Final Clearance Documents (B/L, Invoice, PKL, COC)",
		"department": "Documentation",
	},
	{"task_subject": "Request Manifest and Local Import Charges", "department": "Documentation"},
	{"task_subject": "Attach Shipping Line Invoice", "department": "Documentation"},
	{"task_subject": "Finance pays Shipping Line Charges", "department": "Finance"},
	{"task_subject": "Create Entry", "department": "Declaration"},
	{"task_subject": "Finance Pays Entry Slip", "department": "Finance"},
	{"task_subject": "Lodge Delivery Order", "department": "Operations"},
	{"task_subject": "Prepare Post-Clearance Permits", "department": "Declaration"},
	{"task_subject": "Finance pays for Post-Clearance Permits", "department": "Finance"},
	{"task_subject": "Field Officers conduct clearance", "department": "Field Operations"},
	{"task_subject": "Supervisor obtains KPA Invoice", "department": "Operations"},
	{"task_subject": "Finance pays KPA Invoice", "department": "Finance"},
	{"task_subject": "Book trucks and notify warehouse", "department": "Transport"},
	{"task_subject": "Load trucks and exit port", "department": "Transport"},
	{"task_subject": "Monitor delivery to destination", "department": "Transport"},
	{"task_subject": "Offload cargo", "department": "Transport"},
	{"task_subject": "Return empty container to depot", "department": "Transport"},
	{"task_subject": "Receive interchange confirmation", "department": "Transport"},
]

DEFAULT_DOC_CODES: dict[int, list[str]] = {
	3: [],
	4: [],
	7: ["INSPECT"],
	8: [],
	9: ["MANIFEST"],
	10: [],
	11: [],
	14: ["DO"],
	17: ["FIELD", "DELIVERY_NOTE"],
}

DEFAULT_PERMIT_APPLICATION_SEQS: frozenset[int] = frozenset({5, 15})
DEFAULT_LIGHT_PROOF_SEQS: frozenset[int] = frozenset({20, 21, 22, 23, 24, 25})
DEFAULT_PERMIT_STAGES: dict[int, str] = {5: "Pre-clearance", 15: "Post-clearance"}
DEFAULT_AUTO_COMPLETE_SEQS: frozenset[int] = frozenset({1, 2})
DEFAULT_UCR_APPLICATION_SEQS: frozenset[int] = frozenset({3})
DEFAULT_ENTRY_APPLICATION_SEQS: frozenset[int] = frozenset({12})
DEFAULT_SHIPPING_LINE_APPLICATION_SEQS: frozenset[int] = frozenset({10})
DEFAULT_KPA_APPLICATION_SEQS: frozenset[int] = frozenset({18})
DEFAULT_FINANCE_PAYMENT_SEQS: frozenset[int] = frozenset({4, 6, 11, 13, 16, 19})
DEFAULT_FINANCE_KIND_BY_SEQ: dict[int, str] = {
	4: "UCR",
	6: "Permit",
	11: "Shipping Line",
	13: "Entry Slip",
	16: "Permit",
	19: "KPA",
}

DEFAULT_SEA_WORKFLOW_TASK_GATES: list[dict] = [
	{"shipment_workflow_state": "Documents Received", "min_completed_task_seq": 1, "gate_rule": "Standard"},
	{"shipment_workflow_state": "UCR Applied", "min_completed_task_seq": 3, "gate_rule": "Standard"},
	{"shipment_workflow_state": "UCR Paid", "min_completed_task_seq": 4, "gate_rule": "UCR Finance Complete"},
	{"shipment_workflow_state": "Pre-clearance", "min_completed_task_seq": 5, "gate_rule": "Permit Invoices Submitted"},
	{"shipment_workflow_state": "Client Inspection", "min_completed_task_seq": 7, "gate_rule": "Standard"},
	{"shipment_workflow_state": "In Transit", "min_completed_task_seq": 8, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Final Docs Received", "min_completed_task_seq": 8, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Manifest Requested", "min_completed_task_seq": 9, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Line Paid & DO Lodged", "min_completed_task_seq": 14, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Entry Lodged", "min_completed_task_seq": 12, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Entry Paid", "min_completed_task_seq": 13, "gate_rule": "Entry Finance Complete"},
	{"shipment_workflow_state": "Post-clearance", "min_completed_task_seq": 15, "gate_rule": "Permit Invoices Submitted"},
	{"shipment_workflow_state": "Field Clearance", "min_completed_task_seq": 17, "gate_rule": "Standard"},
	{"shipment_workflow_state": "KPA Paid", "min_completed_task_seq": 19, "gate_rule": "KPA Finance Complete"},
	{"shipment_workflow_state": "In Delivery", "min_completed_task_seq": 19, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Containers Returned", "min_completed_task_seq": 24, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Completed", "min_completed_task_seq": 25, "gate_rule": "All Sea Tasks Complete"},
]

DEFAULT_SEA_IMPORT_WORKFLOW_STATES: list[str] = ["Draft"] + [
	row["shipment_workflow_state"]
	for row in DEFAULT_SEA_WORKFLOW_TASK_GATES
	if row.get("shipment_workflow_state")
]

DEFAULT_DOCUMENT_CHECKPOINT_SEQS: frozenset[int] = frozenset({8})


def build_requirement_seed_rows() -> list[dict]:
	rows: list[dict] = []
	for seq in sorted(DEFAULT_AUTO_COMPLETE_SEQS):
		rows.append({"sequence_no": seq, "requirement_type": "Auto Complete", "value": ""})
	for seq in sorted(DEFAULT_UCR_APPLICATION_SEQS):
		rows.append({"sequence_no": seq, "requirement_type": "UCR Application", "value": ""})
	for seq in sorted(DEFAULT_ENTRY_APPLICATION_SEQS):
		rows.append({"sequence_no": seq, "requirement_type": "Entry Application", "value": ""})
	for seq in sorted(DEFAULT_SHIPPING_LINE_APPLICATION_SEQS):
		rows.append({"sequence_no": seq, "requirement_type": "Shipping Line Application", "value": ""})
	for seq in sorted(DEFAULT_KPA_APPLICATION_SEQS):
		rows.append({"sequence_no": seq, "requirement_type": "KPA Application", "value": ""})
	for seq in sorted(DEFAULT_PERMIT_APPLICATION_SEQS):
		rows.append({"sequence_no": seq, "requirement_type": "Permit Application", "value": ""})
		rows.append(
			{
				"sequence_no": seq,
				"requirement_type": "Permit Stage",
				"value": DEFAULT_PERMIT_STAGES.get(seq, "Pre-clearance"),
			}
		)
	for seq in sorted(DEFAULT_LIGHT_PROOF_SEQS):
		rows.append({"sequence_no": seq, "requirement_type": "Light Proof", "value": ""})
	for seq in sorted(DEFAULT_DOCUMENT_CHECKPOINT_SEQS):
		rows.append({"sequence_no": seq, "requirement_type": "Document Checkpoint", "value": ""})
	for seq in sorted(DEFAULT_FINANCE_PAYMENT_SEQS):
		rows.append(
			{
				"sequence_no": seq,
				"requirement_type": "Finance Payment",
				"value": DEFAULT_FINANCE_KIND_BY_SEQ.get(seq, "Standard"),
			}
		)
	for seq, codes in sorted(DEFAULT_DOC_CODES.items()):
		for code in codes:
			rows.append({"sequence_no": seq, "requirement_type": "Document", "value": code})
	return rows


def _requirement_fingerprint(rows) -> frozenset[tuple]:
	"""Comparable set of (sequence_no, requirement_type, value) for settings alignment."""
	out: set[tuple] = set()
	for row in rows or []:
		if isinstance(row, dict):
			seq = int(row.get("sequence_no") or 0)
			rtype = (row.get("requirement_type") or "").strip()
			value = (row.get("value") or "").strip()
		else:
			seq = int(row.get("sequence_no") or 0)
			rtype = (row.get("requirement_type") or "").strip()
			value = (row.get("value") or "").strip()
		if seq and rtype:
			out.add((seq, rtype, value))
	return frozenset(out)


def sea_clearance_requirements_need_reseed(settings) -> bool:
	"""True when Permit Application / Finance Payment sequences drifted from defaults.

	A common drift maps Post-clearance Permit Application to seq 16 (Finance) instead
	of seq 15 (Prepare Post-Clearance Permits), which hides Task Permits on that task.
	"""
	current_rows = settings.get("custom_sea_clearance_task_requirements") or []
	if not current_rows:
		return True

	current = _requirement_fingerprint(current_rows)
	expected = _requirement_fingerprint(build_requirement_seed_rows())

	current_permit_apps = {seq for seq, rtype, _ in current if rtype == "Permit Application"}
	if current_permit_apps != set(DEFAULT_PERMIT_APPLICATION_SEQS):
		return True

	current_permit_finance = {
		seq
		for seq, rtype, value in current
		if rtype == "Finance Payment" and value == "Permit"
	}
	expected_permit_finance = {
		seq for seq, kind in DEFAULT_FINANCE_KIND_BY_SEQ.items() if kind == "Permit"
	}
	if current_permit_finance != expected_permit_finance:
		return True

	# Full fingerprint mismatch still reseeds so Entry/SL/KPA markers stay aligned.
	return current != expected


def reseed_sea_clearance_task_requirements(settings) -> bool:
	"""Replace sea clearance requirements with canonical seed rows. Returns True if changed."""
	meta = settings.meta if hasattr(settings, "meta") else None
	if meta and not meta.has_field("custom_sea_clearance_task_requirements"):
		return False
	if not sea_clearance_requirements_need_reseed(settings):
		return False
	settings.set("custom_sea_clearance_task_requirements", [])
	for row in build_requirement_seed_rows():
		settings.append("custom_sea_clearance_task_requirements", row)
	return True


def ensure_sea_clearance_task_requirements() -> bool:
	"""Idempotent: align CGM Shipping Settings requirement rows with seed defaults."""
	import frappe

	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return False
	settings = frappe.get_doc("CGM Shipping Settings")
	if not reseed_sea_clearance_task_requirements(settings):
		return False
	settings.save(ignore_permissions=True)
	frappe.clear_cache()
	return True
