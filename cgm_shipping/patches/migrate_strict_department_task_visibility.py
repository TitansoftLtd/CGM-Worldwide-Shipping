"""Scope Task visibility to each role group's own departments.

Removes the legacy Operations → Documentation / Field Operations bundle from
CGM Role Group masters so users only see tasks for their roles.
"""

from __future__ import annotations


def execute():
	import frappe

	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		migrate_strict_department_task_visibility,
	)

	if not frappe.db.exists("DocType", "CGM Role Group"):
		return
	migrate_strict_department_task_visibility()
