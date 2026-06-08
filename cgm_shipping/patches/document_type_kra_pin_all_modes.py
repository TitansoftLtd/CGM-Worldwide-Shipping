import frappe


def execute():
	# 1. Create CI/PKL/KRA_PIN Document Type masters when missing.
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import ensure_document_types

	ensure_document_types()

	# 2. KRA PIN is customer onboarding - empty mode matches all transport modes in seeding.
	name = frappe.db.get_value("Document Type", {"code": "KRA_PIN"}, "name")
	if not name:
		return
	frappe.db.set_value("Document Type", name, "mode_of_transport", "", update_modified=False)
	frappe.db.commit()
