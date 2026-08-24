# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

"""Licence types and the per-company yearly renewal checklists.

Source: "CGM WORLDWIDE SHIPPING - COMPANY YEARLY RENEWAL PERMITS" (three lists,
one per company). Every item on those lists renews annually, so each type carries a
12-month default validity and the register suggests an expiry date once an issue date
is entered.

Two entry points, deliberately wired differently:

- :func:`seed_license_types` is master data. It runs on install and on every migrate,
  and only ever creates what is missing.
- :func:`seed_company_permit_register` creates actual register records, so it is NOT
  automatic - run it per company with ``bench execute`` when that company is ready:

      bench --site <site> execute \
        cgm_shipping.cgm_worldwide_shipping.customizations.license_seed_data.seed_company_permit_register \
        --kwargs "{'checklist': 'CGM Worldwide Shipping', 'company': 'CGM Worldwide Shipping Company Limited'}"
"""

import frappe

YEARLY = 12

# (type name, description). Descriptions expand the acronyms used on the source list;
# KGCHU is left blank rather than guessed at.
LICENSE_TYPES = [
	("Business Permit", "County single business permit."),
	("CB11 Customs Bond", "KRA customs security bond (form CB11)."),
	("CR12", "Registrar of Companies extract listing directors and shareholders."),
	("Customs License", "KRA licence to operate as a clearing and forwarding agent."),
	("K.E.B.S", "Kenya Bureau of Standards registration."),
	("K.M.A", "Kenya Maritime Authority licence."),
	("KGCHU", ""),
	("KIFWA", "Kenya International Freight and Warehousing Association membership."),
	("Signature Specimen", "Specimen signatures filed with customs."),
	("T.C.C", "KRA Tax Compliance Certificate."),
	("Transglobal Cargo Consolidators Association", "Association membership."),
	("WIBA", "Work Injury Benefits Act cover for employees."),
]

# Which types each company renews every year, as listed on the source document.
COMPANY_CHECKLISTS = {
	"CGM Worldwide Shipping": [
		"Customs License",
		"CB11 Customs Bond",
		"KIFWA",
		"Business Permit",
		"WIBA",
		"CR12",
		"T.C.C",
		"Signature Specimen",
		"K.M.A",
	],
	"CGM Consolidators": [
		"K.M.A",
		"KGCHU",
		"Business Permit",
		"K.E.B.S",
		"WIBA",
		"T.C.C",
		"CR12",
		"Transglobal Cargo Consolidators Association",
	],
	"Tomwill": [
		"Customs License",
		"CB11 Customs Bond",
		"KIFWA",
		"Business Permit",
		"WIBA",
		"CR12",
		"T.C.C",
		"Signature Specimen",
	],
}


def seed_license_types() -> None:
	"""Create any missing License Type. Never edits one that already exists."""
	if not frappe.db.exists("DocType", "License Type"):
		return

	for type_name, description in LICENSE_TYPES:
		if frappe.db.exists("License Type", type_name):
			continue

		frappe.get_doc(
			{
				"doctype": "License Type",
				"type_name": type_name,
				"default_validity_months": YEARLY,
				"description": description,
			}
		).insert(ignore_permissions=True)


def permit_license_name(checklist: str, type_name: str) -> str:
	"""Licence name for a checklist row, e.g. "Tomwill - Business Permit".

	The entity is carried in the name because more than one of these checklists can
	be registered against the same ERPNext Company - all three share Business Permit,
	WIBA, CR12 and T.C.C, and without the prefix they would be indistinguishable in
	the list, in reminder emails, and to the duplicate check below.
	"""
	return f"{checklist} - {type_name}"


def seed_company_permit_register(checklist: str, company: str) -> list[str]:
	"""Create the register rows for one checklist against an ERPNext Company.

	Rows start on "Renew When Needed" because the source list carries no dates -
	they show as Renewal Required until someone enters the certificate's issue and
	expiry dates and switches the basis to Fixed Expiry Date.

	Skips rows already recorded for the company, so it is safe to re-run after adding
	a type to a checklist.
	"""
	if checklist not in COMPANY_CHECKLISTS:
		frappe.throw(f"Unknown checklist {checklist!r}. Expected one of {sorted(COMPANY_CHECKLISTS)}.")

	if not frappe.db.exists("Company", company):
		frappe.throw(f"Company {company!r} does not exist.")

	seed_license_types()

	created = []
	for type_name in COMPANY_CHECKLISTS[checklist]:
		license_name = permit_license_name(checklist, type_name)
		if frappe.db.exists("License Register", {"company": company, "license_name": license_name}):
			continue

		licence = frappe.get_doc(
			{
				"doctype": "License Register",
				"license_name": license_name,
				"license_type": type_name,
				"company": company,
				"renewal_basis": "Renew When Needed",
			}
		).insert(ignore_permissions=True)
		created.append(licence.name)

	frappe.db.commit()
	return created


def seed_all_permit_registers(company: str) -> dict[str, list[str]]:
	"""Register every checklist against one Company.

	Used where the entities do not each have their own ERPNext Company - the licence
	name keeps them apart, but note the Company shown on a reminder email is the one
	passed here, not the entity the permit actually belongs to.
	"""
	return {name: seed_company_permit_register(name, company) for name in COMPANY_CHECKLISTS}
