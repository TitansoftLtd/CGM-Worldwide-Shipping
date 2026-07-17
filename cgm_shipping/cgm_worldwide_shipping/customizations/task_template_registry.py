"""CGM Task Template names and legacy flow-key compatibility."""

from __future__ import annotations

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	ROAD_TRANSIT_INBOUND_TASK_FLOW_KEY,
	ROAD_TRANSIT_OUTBOUND_TASK_FLOW_KEY,
	SEA_TASK_FLOW_KEY,
	SEA_TRANSIT_EXPORT_TASK_FLOW_KEY,
	SEA_TRANSIT_IMPORT_TASK_FLOW_KEY,
)

# Canonical template record names (CGM Task Template.template_name / .name).
SEA_IMPORT_TEMPLATE = "Sea Import Workflow"
SEA_EXPORT_TEMPLATE = "Sea Export Workflow"
AIR_IMPORT_TEMPLATE = "Air Import Workflow"
AIR_EXPORT_TEMPLATE = "Air Export Workflow"
SEA_TRANSIT_IMPORT_TEMPLATE = "Sea Transit Import Workflow"
SEA_TRANSIT_EXPORT_TEMPLATE = "Sea Transit Export Workflow"
ROAD_TRANSIT_OUTBOUND_TEMPLATE = "Road Transit Outbound Workflow"
ROAD_TRANSIT_INBOUND_TEMPLATE = "Road Transit Inbound Workflow"

ALL_TEMPLATE_NAMES: frozenset[str] = frozenset(
	{
		SEA_IMPORT_TEMPLATE,
		SEA_EXPORT_TEMPLATE,
		AIR_IMPORT_TEMPLATE,
		AIR_EXPORT_TEMPLATE,
		SEA_TRANSIT_IMPORT_TEMPLATE,
		SEA_TRANSIT_EXPORT_TEMPLATE,
		ROAD_TRANSIT_OUTBOUND_TEMPLATE,
		ROAD_TRANSIT_INBOUND_TEMPLATE,
	}
)

LEGACY_FLOW_KEY_TO_TEMPLATE: dict[str, str] = {
	SEA_TASK_FLOW_KEY: SEA_IMPORT_TEMPLATE,
	SEA_TRANSIT_IMPORT_TASK_FLOW_KEY: SEA_TRANSIT_IMPORT_TEMPLATE,
	SEA_TRANSIT_EXPORT_TASK_FLOW_KEY: SEA_TRANSIT_EXPORT_TEMPLATE,
	ROAD_TRANSIT_OUTBOUND_TASK_FLOW_KEY: ROAD_TRANSIT_OUTBOUND_TEMPLATE,
	ROAD_TRANSIT_INBOUND_TASK_FLOW_KEY: ROAD_TRANSIT_INBOUND_TEMPLATE,
}

TEMPLATE_TO_LEGACY_FLOW_KEY: dict[str, str] = {
	v: k for k, v in LEGACY_FLOW_KEY_TO_TEMPLATE.items()
}

# Shipment Type name → default template (fixture / admin setup).
SHIPMENT_TYPE_TEMPLATE_MAP: dict[str, str] = {
	"Sea Import": SEA_IMPORT_TEMPLATE,
	"Sea Export": SEA_EXPORT_TEMPLATE,
	"Air Import": AIR_IMPORT_TEMPLATE,
	"Air Export": AIR_EXPORT_TEMPLATE,
	"Sea Transit Import": SEA_TRANSIT_IMPORT_TEMPLATE,
	"Sea Transit Export": SEA_TRANSIT_EXPORT_TEMPLATE,
	"Road Transit Outbound": ROAD_TRANSIT_OUTBOUND_TEMPLATE,
	"Road Transit Inbound": ROAD_TRANSIT_INBOUND_TEMPLATE,
}

# Shipment Type name → Container Tracker Mode.
SHIPMENT_TYPE_TRACKER_MODE_MAP: dict[str, str] = {
	"Sea Import": "Mombasa Port",
	"Sea Export": "Export",
	"Air Import": "ICD Nairobi",
	"Air Export": "Export",
	"Sea Transit Import": "Transit Import",
	"Sea Transit Export": "Transit Export",
	"Road Transit Outbound": "Transit Export",
	"Road Transit Inbound": "Transit Import",
}


def normalize_template_name(value: str | None) -> str | None:
	"""Map legacy flow keys or template names to canonical template name."""
	if not value:
		return None
	key = str(value).strip()
	if not key:
		return None
	if key in ALL_TEMPLATE_NAMES:
		return key
	return LEGACY_FLOW_KEY_TO_TEMPLATE.get(key)


def task_matches_template(task, template_name: str) -> bool:
	"""True when Task.custom_task_flow_key matches template or its legacy key."""
	flow = (task.get("custom_task_flow_key") if hasattr(task, "get") else task) or ""
	flow = str(flow).strip()
	if not flow:
		return False
	if flow == template_name:
		return True
	return normalize_template_name(flow) == template_name


def is_sea_import_task(task) -> bool:
	return task_matches_template(task, SEA_IMPORT_TEMPLATE)


def is_sea_import_template_name(name: str | None) -> bool:
	return normalize_template_name(name) == SEA_IMPORT_TEMPLATE


def legacy_flow_key_for_template(template_name: str | None) -> str | None:
	normalized = normalize_template_name(template_name)
	if not normalized:
		return None
	return TEMPLATE_TO_LEGACY_FLOW_KEY.get(normalized)


def workflow_flow_keys_for_template(template_name: str | None) -> list[str]:
	"""Task.custom_task_flow_key values for a template (name + legacy key)."""
	normalized = normalize_template_name(template_name)
	if not normalized:
		raw = (template_name or "").strip()
		return [raw] if raw else []

	keys = [normalized]
	legacy = TEMPLATE_TO_LEGACY_FLOW_KEY.get(normalized)
	if legacy and legacy not in keys:
		keys.append(legacy)
	return keys


def is_transit_template_name(name: str | None) -> bool:
	normalized = normalize_template_name(name)
	return normalized in {
		SEA_TRANSIT_IMPORT_TEMPLATE,
		SEA_TRANSIT_EXPORT_TEMPLATE,
		ROAD_TRANSIT_OUTBOUND_TEMPLATE,
		ROAD_TRANSIT_INBOUND_TEMPLATE,
	}
