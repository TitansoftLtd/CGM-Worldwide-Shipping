import frappe

MODES = ["Air", "Sea", "Road"]


def execute():
	# 1. Seed the Mode of Transport master.
	for mode in MODES:
		if not frappe.db.exists("Mode of Transport", mode):
			frappe.get_doc({"doctype": "Mode of Transport", "mode": mode}).insert(
				ignore_permissions=True
			)

	# 2. Migrate legacy single values into the child table. The old column is left
	#    orphaned by the fieldtype change (Frappe keeps removed columns until a trim),
	#    so it is still readable here.
	if "mode_of_transport" not in frappe.db.get_table_columns("Document Type"):
		return

	rows = frappe.db.sql(
		"""
		SELECT name, mode_of_transport
		FROM `tabDocument Type`
		WHERE mode_of_transport IS NOT NULL AND mode_of_transport != ''
		""",
		as_dict=True,
	)
	for row in rows:
		mode = (row.mode_of_transport or "").strip()
		if mode not in MODES:
			continue
		if frappe.db.exists(
			"Mode of Transport Item",
			{
				"parenttype": "Document Type",
				"parent": row.name,
				"mode_of_transport": mode,
			},
		):
			continue
		doc = frappe.get_doc("Document Type", row.name)
		doc.append("mode_of_transport", {"mode_of_transport": mode})
		# Document Type is submittable and these masters are already submitted.
		doc.flags.ignore_validate_update_after_submit = True
		doc.save(ignore_permissions=True)

	frappe.db.commit()
