import frappe


def execute():
	# KRA PIN is customer onboarding / compliance — not Sea-specific. Empty mode matches
	# all projects in seed_required_document_rows (filter includes "" and None).
	name = frappe.db.get_value("Document Type", {"code": "KRA_PIN"}, "name")
	if not name:
		return
	frappe.db.set_value("Document Type", name, "mode_of_transport", "")
	frappe.db.commit()
