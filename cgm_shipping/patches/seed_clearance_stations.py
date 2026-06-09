# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""Seed the Container Freight Stations (Clearance Station) from the KRA list.

Creates the CFS Location masters and the Clearance Stations that link to them.
Names are stored in Title Case; the Station Code keeps the official uppercase
abbreviation. Idempotent: existing stations (matched by Station Code) are
updated, missing ones created. Safe to re-run.
"""

import frappe

# (CFS name, Abbreviation / Station Code, Location) per the KRA CFS list.
STATIONS = [
	("Transami", "MCT", "Port Reitz"),
	("African Line", "ALT", "Jomvu"),
	("Greatlakes", "GLP", "Jomvu"),
	("Consolbase I", "FFK", "Changamwe"),
	("Signon Freight Ltd", "SIG", "Miritini"),
	("Focus", "FOC", "Port/Kipevu Area"),
	("Compact", "CCF", "Miritini"),
	("Awanad", "AWD", "Mikindani"),
	("Regional Logistics", "RLC", "Miritini"),
	("Portside", "POR", "Msa Island"),
	("Kencont", "KEN", "Msa Island (Likoni)"),
	("Bossfreight", "BFT", "Likoni"),
	("Multiple Inland Cont. Depot", "MCD", "Kibarani"),
	("Unifreight", "UNF", "Kibarani"),
	("Mitchell Cotts II", "MCF", "Kibarani"),
	("Msa Island Cont. Terminal", "MICT", "Makupa"),
	("Autoport", "AUT", "Island"),
	("Mitchell Cotts I", "MIT", "Shimanzi"),
	("Consolbase II", "CB2", "Changamwe"),
	("Interpel", "ILL", "Kipevu Area"),
	("Makupa Transit Shed", "MTS", "Port Area"),
]


def seed():
	"""Create/refresh the CFS Locations and Clearance Stations. Idempotent."""
	for cfs_name, code, location in STATIONS:
		if location and not frappe.db.exists("CFS Location", location):
			frappe.get_doc(
				{"doctype": "CFS Location", "location_name": location}
			).insert(ignore_permissions=True)

		existing = frappe.db.get_value("Clearance Station", {"station_code": code})
		if existing:
			doc = frappe.get_doc("Clearance Station", existing)
			doc.cfs_name = cfs_name
			doc.location = location
			doc.save(ignore_permissions=True)
		else:
			frappe.get_doc(
				{
					"doctype": "Clearance Station",
					"station_code": code,
					"cfs_name": cfs_name,
					"location": location,
				}
			).insert(ignore_permissions=True)

	frappe.db.commit()


def execute():
	seed()
