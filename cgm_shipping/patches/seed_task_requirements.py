"""Seed CGM Shipping Settings: sea task completion rules."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements.seed_data import (
	DEFAULT_AUTO_COMPLETE_SEQS,
	DEFAULT_DOC_CODES,
	DEFAULT_FINANCE_KIND_BY_SEQ,
	DEFAULT_FINANCE_PAYMENT_SEQS,
	DEFAULT_LIGHT_PROOF_SEQS,
	DEFAULT_PERMIT_APPLICATION_SEQS,
	DEFAULT_PERMIT_STAGES,
	DEFAULT_UCR_APPLICATION_SEQS,
)


def build_requirement_seed_rows() -> list[dict]:
	rows: list[dict] = []
	for seq in sorted(DEFAULT_AUTO_COMPLETE_SEQS):
		rows.append({"sequence_no": seq, "requirement_type": "Auto Complete", "value": ""})
	for seq in sorted(DEFAULT_UCR_APPLICATION_SEQS):
		rows.append({"sequence_no": seq, "requirement_type": "UCR Application", "value": ""})
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


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return
	settings = frappe.get_doc("CGM Shipping Settings")
	meta = frappe.get_meta("CGM Shipping Settings")
	changed = False
	if meta.has_field("custom_sea_clearance_task_requirements") and not settings.get(
		"custom_sea_clearance_task_requirements"
	):
		for row in build_requirement_seed_rows():
			settings.append("custom_sea_clearance_task_requirements", row)
		changed = True
	if changed:
		settings.save(ignore_permissions=True)
		frappe.db.commit()
