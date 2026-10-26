"""CGM's reports and tools on the sidebars people actually work from.

A module's sidebar is shipped by the app that owns the module, and a site does not edit
what an app ships: it adds a layer over it (`Custom Sidebar`), which is what the desk's
own sidebar editor writes. Two modules need entries that no app ships:

* Payroll belongs to hrms, so CGM's payroll reports were reachable only by searching.
* CGM Worldwide Shipping had no Reports section at all, so its own reports sat in the
  one place nobody looks, or nowhere.

This runs from `after_migrate` rather than from a patch so a report added later, or a
layer someone reset back to standard, still ends up on the sidebar. It only ever adds an
entry that is missing, so an arrangement made in the desk survives. The one thing it will
undo is an entry deliberately removed, which comes back on the next deploy.
"""

from __future__ import annotations

import frappe

REPORTS_SECTION = "Reports"

#: One entry per module: the reports to list under `section`, and top-level tools, each
#: placed directly after the entry it belongs with.
SIDEBARS = (
	{
		"module": "Payroll",
		"section": REPORTS_SECTION,
		"section_icon": "notepad-text",
		"reports": (
			"Payroll Register",
			"NSSF Monthly Return",
			"SHIF Monthly Return",
			"PAYE Monthly Return",
			"DTB Salary Payment Schedule",
		),
		"tools": (("Additional Salary Tool", "piggy-bank", "Additional Salary"),),
	},
	{
		"module": "CGM Worldwide Shipping",
		"section": REPORTS_SECTION,
		"section_icon": "notepad-text",
		"reports": (
			"Completed Shipments",
			"Project Expense Summary",
			"Funding Request Report",
			"Material Request Funding",
			"Container Return Tracker",
			"Container Tracking Report",
		),
		"tools": (),
	},
)


def ensure_cgm_sidebar_entries() -> None:
	"""Add CGM's reports and tools to each module's sidebar site layer."""
	# The layered sidebar arrived in v16 and replaced an earlier store. On a build without
	# it there is nothing to add a layer to, and the earlier store is an inert archive
	# nothing renders, so there is no older path worth writing to.
	if not frappe.db.exists("DocType", "Custom Sidebar"):
		return

	from frappe.desk.doctype.custom_sidebar.custom_sidebar import (
		_save_customization,
		layer_arrangement,
	)

	for spec in SIDEBARS:
		module = spec["module"]
		if not frappe.db.exists("Module Def", module):
			continue

		arrangement = layer_arrangement(module, None)
		changed = _add_reports(arrangement, spec)
		changed = _add_tools(arrangement, spec) or changed

		if changed:
			_save_customization(module, arrangement, user=None)


def _present(arrangement: list[dict], link_type: str, link_to: str) -> bool:
	return any(
		row.get("link_type") == link_type and row.get("link_to") == link_to for row in arrangement
	)


def _section_end(arrangement: list[dict], section: str) -> int | None:
	"""Index just past the last entry of `section`, or None when there is no such section.

	The section runs from its own Section Break to the next one, so an entry inserted
	here lands inside it rather than at the bottom of the sidebar.
	"""
	start = next(
		(
			i
			for i, row in enumerate(arrangement)
			if row.get("type") == "Section Break" and (row.get("label") or "").strip() == section
		),
		None,
	)
	if start is None:
		return None

	return next(
		(
			i
			for i in range(start + 1, len(arrangement))
			if arrangement[i].get("type") == "Section Break"
		),
		len(arrangement),
	)


def _add_reports(arrangement: list[dict], spec: dict) -> bool:
	# A report absent from this site would be a sidebar entry that goes nowhere.
	wanted = [
		name
		for name in spec["reports"]
		if frappe.db.exists("Report", name) and not _present(arrangement, "Report", name)
	]
	if not wanted:
		return False

	at = _section_end(arrangement, spec["section"])
	if at is None:
		# No such section yet: start one at the end, which is where a reports section
		# belongs anyway.
		arrangement.append(_section(spec["section"], spec.get("section_icon") or ""))
		at = len(arrangement)

	for offset, name in enumerate(wanted):
		arrangement.insert(at + offset, _row("Report", name, name, "", child=1))
	return True


def _add_tools(arrangement: list[dict], spec: dict) -> bool:
	changed = False
	for name, icon, after in spec["tools"]:
		if not frappe.db.exists("DocType", name) or _present(arrangement, "DocType", name):
			continue
		at = next(
			(i + 1 for i, row in enumerate(arrangement) if row.get("link_to") == after),
			len(arrangement),
		)
		arrangement.insert(at, _row("DocType", name, name, icon, child=0))
		changed = True
	return changed


def _base_row(label: str, icon: str) -> dict:
	return {
		"key": None,
		"added": 1,
		"hidden": 0,
		"label": label,
		"icon": icon,
		"indent": 0,
		"collapsible": 1,
		"keep_closed": 0,
		"url": None,
		"show_arrow": 0,
		"filters": None,
		"route_options": None,
		"navigate_to_tab": None,
		"open_in_new_tab": 1,
	}


def _row(link_type: str, link_to: str, label: str, icon: str, *, child: int) -> dict:
	"""One link of a saved arrangement, marked as this layer's own addition."""
	return {
		**_base_row(label, icon),
		"type": "Link",
		"link_type": link_type,
		"link_to": link_to,
		"child": child,
	}


def _section(label: str, icon: str) -> dict:
	"""A collapsed section heading, matching how the shipped sidebars write one."""
	return {
		**_base_row(label, icon),
		"type": "Section Break",
		"link_type": "DocType",
		"link_to": None,
		"child": 0,
		"indent": 1,
		"keep_closed": 1,
	}
