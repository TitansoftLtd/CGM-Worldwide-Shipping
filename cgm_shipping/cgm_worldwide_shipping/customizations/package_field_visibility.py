"""Package field visibility driven from CGM Shipping Settings.

Number of Packages / Package Type show when the Mode of Transport or Cargo Type
on the form is listed on CGM Shipping Settings. The eval string is written onto
Custom Fields when settings change or on migrate — Desk does not query Settings
on every depends_on evaluation.
"""

from __future__ import annotations

import re

import frappe

PACKAGE_FIELDS = (
	("Opportunity-custom_number_of_packages", "Opportunity"),
	("Opportunity-custom_package_type", "Opportunity"),
	("Project-custom_number_of_packages", "Project"),
	("Project-custom_package_type", "Project"),
)

SETTINGS_MODE_FIELD = "package_visibility_modes"
SETTINGS_CARGO_FIELD = "package_visibility_cargo_types"

OPP_CARGO_FIELDS = ("custom_cargo_type_", "custom_cargo_type")
PROJECT_CARGO_FIELDS = ("custom_cargo_type",)
MODE_FIELD = "custom_mode_of_transport"
AWB_CLAUSE = "doc.custom_air_waybill"

# Longer names first so custom_cargo_type_ is not truncated to custom_cargo_type.
_MANAGED_FIELDS = (
	"custom_cargo_type_",
	"custom_mode_of_transport",
	"custom_cargo_type",
	"custom_air_waybill",
)
_MANAGED_CLAUSE = re.compile(
	r"^doc\.(?:"
	+ "|".join(re.escape(name) for name in _MANAGED_FIELDS)
	+ r")(?:=='(?:\\'|[^'])*')?$"
)


def get_package_visibility_config() -> dict[str, list[str]]:
	"""Configured Mode of Transport and Cargo Type names (empty lists if unset)."""
	modes: list[str] = []
	cargo_types: list[str] = []
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return {"modes": modes, "cargo_types": cargo_types}
	if not frappe.db.exists("CGM Shipping Settings", "CGM Shipping Settings"):
		return {"modes": modes, "cargo_types": cargo_types}

	settings = frappe.get_cached_doc("CGM Shipping Settings", "CGM Shipping Settings")
	if settings.meta.has_field(SETTINGS_MODE_FIELD):
		modes = [
			(row.get("mode_of_transport") or "").strip()
			for row in (settings.get(SETTINGS_MODE_FIELD) or [])
			if (row.get("mode_of_transport") or "").strip()
		]
	if settings.meta.has_field(SETTINGS_CARGO_FIELD):
		cargo_types = [
			(row.get("cargo_type") or "").strip()
			for row in (settings.get(SETTINGS_CARGO_FIELD) or [])
			if (row.get("cargo_type") or "").strip()
		]
	return {"modes": modes, "cargo_types": cargo_types}


def _quote(value: str) -> str:
	return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _eq(fieldname: str, value: str) -> str:
	return f"doc.{fieldname}=={_quote(value)}"


def build_depends_on(
	*,
	modes: list[str] | None = None,
	cargo_types: list[str] | None = None,
	cargo_fields: tuple[str, ...] = OPP_CARGO_FIELDS,
	extra_clauses: tuple[str, ...] = (),
) -> str:
	"""Build a client-side depends_on eval from configured names (no DB at eval time)."""
	clauses: list[str] = list(extra_clauses)
	for mode in modes or []:
		if mode:
			clauses.append(_eq(MODE_FIELD, mode))
	for cargo in cargo_types or []:
		if not cargo:
			continue
		for fieldname in cargo_fields:
			clauses.append(_eq(fieldname, cargo))
	if not clauses:
		return "eval:0"
	return "eval:" + " || ".join(clauses)


def build_opportunity_depends_on(
	modes: list[str] | None = None,
	cargo_types: list[str] | None = None,
) -> str:
	config = get_package_visibility_config() if modes is None and cargo_types is None else None
	return build_depends_on(
		modes=config["modes"] if config else (modes or []),
		cargo_types=config["cargo_types"] if config else (cargo_types or []),
		cargo_fields=OPP_CARGO_FIELDS,
		extra_clauses=(AWB_CLAUSE,),
	)


def build_project_depends_on(
	modes: list[str] | None = None,
	cargo_types: list[str] | None = None,
) -> str:
	config = get_package_visibility_config() if modes is None and cargo_types is None else None
	return build_depends_on(
		modes=config["modes"] if config else (modes or []),
		cargo_types=config["cargo_types"] if config else (cargo_types or []),
		cargo_fields=PROJECT_CARGO_FIELDS,
	)


def _is_managed_depends_on(current: str | None) -> bool:
	"""True when depends_on is empty, hidden, or only uses this feature's fields.

	An administrator expression that mentions other fields is left alone.
	"""
	value = (current or "").strip()
	if not value or value == "eval:0":
		return True
	if not value.startswith("eval:"):
		return False
	expr = value[5:].strip()
	if expr == "0":
		return True
	clauses = [clause.strip() for clause in expr.split("||") if clause.strip()]
	if not clauses:
		return False
	return all(_MANAGED_CLAUSE.match(clause) for clause in clauses)


def apply_package_field_depends_on(*, force: bool = False) -> None:
	"""Write generated depends_on onto package Custom Fields.

	Skips a field whose depends_on was customized away from this module's
	expressions, unless ``force`` is True.
	"""
	config = get_package_visibility_config()
	expressions = {
		"Opportunity": build_opportunity_depends_on(config["modes"], config["cargo_types"]),
		"Project": build_project_depends_on(config["modes"], config["cargo_types"]),
	}
	for fieldname, dt in PACKAGE_FIELDS:
		if not frappe.db.exists("Custom Field", fieldname):
			continue
		current = frappe.db.get_value("Custom Field", fieldname, "depends_on") or ""
		new_value = expressions[dt]
		if current.strip() == new_value:
			continue
		if not force and not _is_managed_depends_on(current):
			continue
		_set_depends_on(fieldname, new_value)
	frappe.clear_cache(doctype="Opportunity")
	frappe.clear_cache(doctype="Project")


def _set_depends_on(fieldname: str, depends_on: str) -> None:
	"""Update Custom Field depends_on without wiping unrelated administrator properties."""
	if not frappe.db.exists("Custom Field", fieldname):
		return
	frappe.db.set_value(
		"Custom Field",
		fieldname,
		{"depends_on": depends_on, "hidden": 0},
		update_modified=False,
	)


def seed_package_visibility_defaults() -> bool:
	"""Fill empty Settings lists from names already present on Custom Field depends_on.

	Only runs when both MultiSelect tables are empty so an administrator's
	later edits are never reset. Returns True when settings were saved.
	"""
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return False
	if not frappe.get_meta("CGM Shipping Settings").has_field(SETTINGS_MODE_FIELD):
		return False

	settings = frappe.get_doc("CGM Shipping Settings")
	if settings.get(SETTINGS_MODE_FIELD) or settings.get(SETTINGS_CARGO_FIELD):
		return False

	changed = False
	if frappe.db.exists("DocType", "Mode of Transport"):
		for name in frappe.get_all("Mode of Transport", pluck="name"):
			if _master_currently_shows_packages("mode", name):
				settings.append(SETTINGS_MODE_FIELD, {"mode_of_transport": name})
				changed = True
	if frappe.db.exists("DocType", "Cargo Type"):
		for name in frappe.get_all("Cargo Type", pluck="name"):
			if _master_currently_shows_packages("cargo", name):
				settings.append(SETTINGS_CARGO_FIELD, {"cargo_type": name})
				changed = True

	if not changed:
		return False
	settings.flags.ignore_permissions = True
	settings.flags.skip_package_visibility_apply = True
	settings.save(ignore_permissions=True)
	return True


def _master_currently_shows_packages(kind: str, name: str) -> bool:
	"""True when existing Custom Field depends_on already includes this master name.

	Used only to copy today's live rule into empty Settings — not a business default.
	"""
	if kind == "mode":
		needles = [_eq(MODE_FIELD, name)]
	else:
		needles = [_eq(field, name) for field in (*OPP_CARGO_FIELDS, *PROJECT_CARGO_FIELDS)]
	for fieldname, _dt in PACKAGE_FIELDS:
		if not frappe.db.exists("Custom Field", fieldname):
			continue
		current = frappe.db.get_value("Custom Field", fieldname, "depends_on") or ""
		if any(needle in current for needle in needles):
			return True
	return False
