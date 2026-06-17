# Copyright (c) 2026, Titansoft Limited and contributors
"""Demurrage and detention calculations for Container Tracker."""

from __future__ import annotations

from typing import Any

from frappe.utils import getdate, today

from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	compute_container_metrics,
)


def compute_container_metrics_legacy(data: dict[str, Any]) -> dict[str, Any]:
	return compute_container_metrics(data)


def derive_current_location(
	*,
	data: dict[str, Any],
	actual_return,
	gate_out,
	discharge,
	delivery_date,
) -> str:
	delivery_location = (data.get("delivery_location") or "").strip()
	container_mode = data.get("container_mode") or ""

	if data.get("interchange_date"):
		return "Interchange received"
	if actual_return:
		return "Empty returned to line / depot"
	if data.get("gate_in_date_depot"):
		return "Empty depot"
	if delivery_date:
		return delivery_location or "Delivered to customer"
	if gate_out:
		if delivery_location:
			return f"In transit - {delivery_location}"
		return "Out of port (gate out)"
	if data.get("icd_gate_in_date") or data.get("icd_gate_out_date"):
		return "ICD Nairobi"
	if discharge:
		if "ICD" in container_mode:
			return "ICD / discharge yard"
		return "Port (discharged, not gated out)"
	if data.get("ata"):
		return "Vessel arrived - port"
	if data.get("eta"):
		return "En route to port"
	return "Pending arrival"


def derive_container_status(**kwargs) -> str | None:
	data = {
		"discharging_date": kwargs.get("discharge"),
		"gate_out_date_port": kwargs.get("gate_out"),
		"offloading_date": kwargs.get("delivery_date"),
		"actual_empty_return": kwargs.get("actual_return"),
	}
	return compute_container_metrics(data).get("status")


def apply_metrics_to_doc(doc) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
		apply_metrics_to_doc as apply_core,
		populate_rates_from_shipping_line,
	)

	populate_rates_from_shipping_line(doc)
	apply_core(doc)
	location = derive_current_location(
		data=doc.as_dict(),
		actual_return=doc.get("actual_empty_return"),
		gate_out=doc.get("gate_out_date_port"),
		discharge=doc.get("discharging_date"),
		delivery_date=doc.get("delivery_date"),
	)
	if not doc.get("current_location") or doc.get("status") in (
		"Released / In Transit",
		"At Warehouse",
		"Cargo Offloaded",
		"Discharged / At Port",
		"Vessel Berthed",
	):
		doc.current_location = location
