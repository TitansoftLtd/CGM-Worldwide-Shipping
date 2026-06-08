"""Add a unique index on Project.custom_cgm_ref_no to prevent duplicate CGM refs.

Project is named by naming_series, so there is no DB-level uniqueness on the CGM
reference. Without a constraint, two concurrent creations can be assigned the same
reference (the application-level check can't see the other's uncommitted row).

This patch is non-destructive:
  * empty strings are normalised to NULL (MySQL allows many NULLs but not many
    equal non-null values);
  * if duplicate references already exist the index is skipped and the duplicates
    are logged for manual resolution - the patch never renumbers a business ref.
"""

import frappe

INDEX_NAME = "cgm_ref_no_unique"


def execute():
	if not frappe.db.has_column("Project", "custom_cgm_ref_no"):
		return

	# 1. Normalise empty strings to NULL so they don't collide under the index.
	frappe.db.sql(
		"UPDATE `tabProject` SET custom_cgm_ref_no = NULL WHERE custom_cgm_ref_no = ''"
	)

	# 2. Skip (non-destructively) if duplicates exist - do not renumber refs.
	dups = frappe.db.sql(
		"""
		SELECT custom_cgm_ref_no, COUNT(*) AS c
		FROM `tabProject`
		WHERE custom_cgm_ref_no IS NOT NULL AND custom_cgm_ref_no != ''
		GROUP BY custom_cgm_ref_no
		HAVING c > 1
		""",
		as_dict=True,
	)
	if dups:
		frappe.log_error(
			title="CGM ref unique index skipped",
			message=(
				"Duplicate custom_cgm_ref_no values exist; unique index NOT added. "
				"Resolve these and re-run this patch:\n"
				+ "\n".join(f"{d.custom_cgm_ref_no} x{d.c}" for d in dups)
			),
		)
		return

	# 3. Add the unique constraint if it isn't already present (add_unique handles
	#    the DDL commit that frappe.db.sql forbids).
	if frappe.db.sql("SHOW INDEX FROM `tabProject` WHERE Key_name = %s", INDEX_NAME):
		return
	frappe.db.add_unique("Project", "custom_cgm_ref_no", constraint_name=INDEX_NAME)
