"""Grade active employees against the signed CGM job group structure.

**Why:** the job group structure and its per diem rates arrived as an HR document
(`files/CGM Job Group Structure & Per diems.pdf`); existing Employee records carried
no grade at all, so no one could claim a per diem until the document was applied to
the data.

**What:** seeds the A-M Employee Grades (via `ensure_per_diem_setup`, which
`install.after_migrate` also runs) and then fills ``Employee.grade`` for active
employees the document places - by office holder name first, by designation second.

**Idempotent:** yes, and non-destructive. Only employees with a blank grade are
touched, so a grade HR sets or corrects in the desk is never overwritten. Employees
the document does not place are left blank and listed in the migrate output for HR.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.per_diem import (
	assign_job_groups_from_structure,
	ensure_per_diem_setup,
)


def execute() -> None:
	if not frappe.db.exists("DocType", "Employee Grade"):
		return

	ensure_per_diem_setup()
	result = assign_job_groups_from_structure()
	frappe.db.commit()

	print(f"CGM job groups: graded {len(result['assigned'])} employee(s)")
	for row in result["assigned"]:
		print(f"  {row['job_group']}  {row['employee_name']} ({row['matched_by']})")

	if result["unmatched_office_holders"]:
		print("  Named in the structure but not found in Employee:")
		for holder in result["unmatched_office_holders"]:
			print(f"    - {holder}")

	if result["ungraded"]:
		print("  Left ungraded - HR to place these manually:")
		for row in result["ungraded"]:
			print(f"    - {row['employee_name']} ({row['designation'] or 'no designation'})")
