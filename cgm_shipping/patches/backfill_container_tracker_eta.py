"""Align Container Tracker ETA / ATA / Custom Release Date with the Project.

Editing these on a Project never reached its containers: the tracker sync only
filled a blank value, and the bulk refreshes fired solely when a specific
clearance task completed. Projects whose dates were revised after their trackers
existed kept stale (or empty) container dates - and a stale Custom Release Date
also holds back the derived container status.

``sync_project_dates_to_trackers`` now propagates on Project update; this repairs
the rows that drifted before that hook existed.
"""

from __future__ import annotations

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
		_save_trackers,
		_trackers_for_project,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.project import get_project_ata

	if not frappe.db.exists("DocType", "Container Tracker"):
		return

	projects = frappe.db.sql(
		"""
		SELECT DISTINCT c.project
		FROM `tabContainer Tracker` c
		JOIN `tabProject` p ON p.name = c.project
		WHERE (p.custom_eta IS NOT NULL AND (c.eta IS NULL OR c.eta <> p.custom_eta))
		   OR (p.custom_actual_time_of_arrival_ata IS NOT NULL
		       AND (c.ata IS NULL OR c.ata <> p.custom_actual_time_of_arrival_ata))
		   OR (p.custom_custom_release_date IS NOT NULL
		       AND (c.custom_release_date IS NULL
		            OR c.custom_release_date <> p.custom_custom_release_date))
		""",
		pluck=True,
	)

	for project_name in projects:
		project = frappe.get_doc("Project", project_name)
		trackers = _trackers_for_project(project_name)
		if not trackers:
			continue

		eta = frappe.utils.getdate(project.custom_eta) if project.custom_eta else None
		ata = get_project_ata(project)
		release = project.get("custom_custom_release_date")
		release = frappe.utils.getdate(release) if release else None

		for ct in trackers:
			if eta:
				ct.eta = eta
			if ata:
				ct.ata = ata
				if not ct.get("discharging_date"):
					ct.discharging_date = ata
			if release:
				ct.custom_release_date = release

		_save_trackers(trackers)
		frappe.db.commit()
		print(
			f"{project_name}: aligned {len(trackers)} container(s) "
			f"(ETA {eta}, ATA {ata}, release {release})"
		)
