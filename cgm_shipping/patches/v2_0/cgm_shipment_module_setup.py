"""Install CGM Worldwide Shipping: roles, naming series, sample CFS masters."""
from __future__ import annotations

import frappe


ROLES = (
	"Operations Manager",
	"Declarant",
	"Finance User",
	"Field Officer",
	"Transport Officer",
)

CFS_SEED = (
	("FedEx", "MAT"),
	("Transglobal", "CSC"),
	("Siginon", "SIG"),
	("Aramex", "TCC"),
	("Swissport", "KAH"),
)

NAMING_SERIES = (
	("Shipment Dossier", "CGM/IM-.YYYY.-.MM.-.###"),
	("Shipment Dossier", "CGM/EX-.YYYY.-.MM.-.###"),
	("Shipment Dossier", "CGM/LCL-.YYYY.-.MM.-.###"),
	("Shipment Dossier", "CGM/FCL-.YYYY.-.MM.-.###"),
)


def execute():
	if not frappe.db.exists("DocType", "CFS Master"):
		return
	_ensure_roles()
	_ensure_naming_series()
	_ensure_cfs_masters()


def _ensure_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			doc = frappe.new_doc("Role")
			doc.role_name = role
			doc.desk_access = 1
			doc.insert(ignore_permissions=True)


def _ensure_naming_series():
	for dt, series in NAMING_SERIES:
		existing = frappe.db.get_value("Property Setter", {"doc_type": dt, "property": "options", "field_name": "naming_series"}, "name")
		if existing:
			continue
		# Naming series are typically configured in Naming Series doctype on site
		if frappe.db.exists("DocType", "Naming Series"):
			name = frappe.db.get_value("Naming Series", {"target": dt}, "name")
			if not name:
				ns = frappe.new_doc("Naming Series")
				ns.target = dt
				ns.set("series", series)
				ns.insert(ignore_permissions=True)


def _ensure_cfs_masters():
	for cfs_name, cfs_code in CFS_SEED:
		if frappe.db.exists("CFS Master", cfs_name):
			continue
		doc = frappe.new_doc("CFS Master")
		doc.cfs_name = cfs_name
		doc.cfs_code = cfs_code
		doc.insert(ignore_permissions=True)
