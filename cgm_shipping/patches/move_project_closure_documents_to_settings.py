"""Require only the documents every shipment ends with before a Project is Completed.

Why: closing a Project needed every Document Type with Default Required ticked -
31 of them, none limited to a mode - attached and verified. Step documents (DO,
Entry, FIELD, ...), unused and duplicate types all counted, and almost nothing is
verified on projects, so no Project could be Completed. Closure now reads the
Completed rows in Settings > Shipment status documents, like every other status.

What:
- keeps Default Required on CI, PKL, KRA_PIN, BL (Sea) and AWB (Air), limiting BL
  and AWB to their mode when they list no mode yet; unticks the other types listed
  in UNTICK;
- deletes the unused duplicates KRA PIN, COI and Commercial Invoice COI when no
  row or stamp uses them (otherwise they are only unticked);
- renames c2 -> C2 and exit -> Exit Note and gives them the Customs category;
- adds Completed rows for the stages of the kept documents, with Must Be Verified
  off, when Settings has no Completed row yet.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it.
"""

import frappe

KEEP_MODES = {"CI": None, "PKL": None, "KRA_PIN": None, "BL": "Sea", "AWB": "Air"}
UNTICK = (
	"IDF", "IDF CERT", "UCR", "Entry", "DO", "FIELD", "Delivery Note", "Inspect", "Manifest",
	"c2", "exit", "COA", "COO", "LOA", "Booking", "COC", "SUP INV", "KPA INV",
	"BOR", "CCR", "MC", "IPA", "PIC", "KRA PIN", "COI", "Commercial Invoice COI",
)
DUPLICATES = ("KRA PIN", "COI", "Commercial Invoice COI")
RENAMES = {"c2": "C2", "exit": "Exit Note"}
FIELD = "custom_workflow_stage_requirements"


def _exact(name: str) -> bool:
	# Names compare case-insensitively in the database: "c2" also finds "C2".
	return frappe.db.get_value("Document Type", name, "name") == name


def _in_use(name: str) -> bool:
	if frappe.db.exists("Shipment Document", {"document_type": name}):
		return True
	for doctype, field in (("CGM Task Template Item", "required_document_types"), ("Task", "custom_required_document_types")):
		for value in frappe.get_all(doctype, filters={field: ["like", f"%{name}%"]}, pluck=field):
			if name in [token.strip() for token in (value or "").split(",")]:
				return True
	return False


def execute():
	if not frappe.db.exists("DocType", "Document Type"):
		return

	for name, mode in KEEP_MODES.items():
		if not _exact(name) or not mode or not frappe.db.exists("Mode of Transport", mode):
			continue
		if frappe.db.exists("Mode of Transport Item", {"parenttype": "Document Type", "parent": name}):
			continue
		frappe.get_doc(
			{
				"doctype": "Mode of Transport Item",
				"parent": name,
				"parenttype": "Document Type",
				"parentfield": "mode_of_transport",
				"idx": 1,
				"mode_of_transport": mode,
			}
		).db_insert()

	for name in UNTICK:
		if _exact(name) and frappe.db.get_value("Document Type", name, "default_required"):
			frappe.db.set_value("Document Type", name, "default_required", 0, update_modified=False)

	for name in DUPLICATES:
		if _exact(name) and not _in_use(name):
			frappe.delete_doc("Document Type", name, ignore_permissions=True, force=True)

	for old, new in RENAMES.items():
		if _exact(old):
			frappe.rename_doc("Document Type", old, new, force=True)
		if _exact(new):
			frappe.db.set_value("Document Type", new, {"code": new, "category": "Customs"}, update_modified=False)

	if frappe.db.exists(
		"Workflow Stage Requirement Item",
		{"parent": "CGM Shipping Settings", "parentfield": FIELD, "shipment_workflow_state": "Completed"},
	):
		return
	stages = []
	for name in KEEP_MODES:
		stage = frappe.db.get_value("Document Type", name, "required_stage") if _exact(name) else None
		if stage and stage not in stages:
			stages.append(stage)
	idx = frappe.db.count("Workflow Stage Requirement Item", {"parent": "CGM Shipping Settings", "parentfield": FIELD})
	for stage in stages:
		idx += 1
		frappe.get_doc(
			{
				"doctype": "Workflow Stage Requirement Item",
				"parent": "CGM Shipping Settings",
				"parenttype": "CGM Shipping Settings",
				"parentfield": FIELD,
				"idx": idx,
				"shipment_workflow_state": "Completed",
				"required_stage": stage,
				"verified_required": 0,
			}
		).db_insert()
	frappe.clear_document_cache("CGM Shipping Settings", "CGM Shipping Settings")
