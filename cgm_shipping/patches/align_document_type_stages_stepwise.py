import frappe


def execute():
	# Step 1: align each document code to the operational step it belongs to.
	code_to_stage = {
		# Step 4: Declaration & Pre-clearance preparation
		"CI": "Pre-IDF",
		"PKL": "Pre-IDF",
		"KRA_PIN": "Pre-IDF",
		# Permits
		"IPA": "Permits (pre-clearance)",
		"PIC": "Permits (pre-clearance)",
		# Step 5: Shipment in transit & tracking (docs collected while in transit)
		"COO": "Pre-arrival",
		"COA": "Pre-arrival",
		"MC": "Pre-arrival",
		# Process/support docs (not used as workflow gate)
		"BOR": "Not stage-specific",
		"CCR": "Not stage-specific",
	}

	for code, stage in code_to_stage.items():
		name = frappe.db.get_value("Document Type", {"code": code}, "name")
		if not name:
			continue
		frappe.db.set_value("Document Type", name, "required_stage", stage)

	frappe.db.commit()

