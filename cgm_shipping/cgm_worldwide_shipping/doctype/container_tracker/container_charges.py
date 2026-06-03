# Copyright (c) 2026, Titansoft Limited and contributors
"""Shared demurrage, detention, location, and status calculations for Container Tracker."""

from __future__ import annotations

from typing import Any

from frappe.utils import add_days, cint, date_diff, flt, getdate, today


def compute_container_metrics(data: dict[str, Any]) -> dict[str, Any]:
	"""Return computed charge, location, and status fields for a container row."""
	free_days = cint(data.get("free_days") or 0)
	discharge = data.get("discharging_date") or data.get("icd_mombasa_discharge_date")
	gate_out = data.get("gate_out_date_port")
	actual_return = data.get("actual_empty_return")
	delivery_date = data.get("delivery_date")
	custom_release = data.get("custom_release_date")

	expected_empty_return = None
	if gate_out and free_days:
		expected_empty_return = add_days(gate_out, free_days)

	port_days_used = 0
	demurrage_days = 0
	demurrage_date = None
	if discharge and gate_out:
		port_days_used = date_diff(gate_out, discharge)
		demurrage_days = max(0, port_days_used - free_days)
		if demurrage_days:
			demurrage_date = add_days(discharge, free_days) if free_days else add_days(discharge, 1)

	detention_end = actual_return or (gate_out and today())
	detention_days = 0
	if gate_out and detention_end:
		outside_days = date_diff(detention_end, gate_out)
		detention_days = max(0, outside_days - free_days)

	demurrage_rate = flt(data.get("daily_demurrage_rate"))
	detention_rate = flt(data.get("daily_detention_rate"))
	demurrage_amount = demurrage_days * demurrage_rate
	detention_amount = detention_days * detention_rate

	days_outstanding = 0
	if expected_empty_return and not actual_return:
		days_outstanding = max(0, date_diff(today(), expected_empty_return))

	status = derive_container_status(
		actual_return=actual_return,
		expected_empty_return=expected_empty_return,
		delivery_date=delivery_date,
		gate_out=gate_out,
		discharge=discharge,
		custom_release=custom_release,
	)

	current_location = derive_current_location(
		data=data,
		actual_return=actual_return,
		gate_out=gate_out,
		discharge=discharge,
		delivery_date=delivery_date,
	)

	return {
		"expected_empty_return": expected_empty_return,
		"port_days_used": port_days_used,
		"demurrage_days": demurrage_days,
		"demurrage_date": demurrage_date,
		"detention_days": detention_days,
		"demurrage_amount": demurrage_amount,
		"detention_amount": detention_amount,
		"days_outstanding": days_outstanding,
		"status": status,
		"current_location": current_location,
	}


def derive_container_status(
	*,
	actual_return,
	expected_empty_return,
	delivery_date,
	gate_out,
	discharge,
	custom_release,
) -> str | None:
	if actual_return:
		return "Empty Returned"
	if expected_empty_return and getdate(today()) > getdate(expected_empty_return):
		return "Overdue"
	if delivery_date and not actual_return:
		return "Empty Pending"
	if gate_out:
		return "Dispatched"
	if discharge or custom_release:
		return "Delivered"
	return None


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

	if actual_return:
		return "Empty returned to line / depot"
	if data.get("gate_in_date_depot"):
		return "Empty depot"
	if delivery_date:
		return delivery_location or "Delivered to customer"
	if gate_out:
		if delivery_location:
			return f"In transit — {delivery_location}"
		return "Out of port (gate out)"
	if data.get("icd_gate_in_date") or data.get("icd_gate_out_date"):
		return "ICD Nairobi"
	if discharge:
		if "ICD" in container_mode:
			return "ICD / discharge yard"
		return "Port (discharged, not gated out)"
	if data.get("ata"):
		return "Vessel arrived — port"
	if data.get("eta"):
		return "En route to port"
	return "Pending arrival"


def apply_metrics_to_doc(doc) -> None:
	"""Apply computed fields onto a Container Tracker document."""
	metrics = compute_container_metrics(doc.as_dict())
	for field, value in metrics.items():
		setattr(doc, field, value)
