"""Mark the intake tasks on each CGM Task Template.

Why: which tasks are completed at project creation, when the client's intake
documents are already there, was decided in code - Sea Import's Auto Complete
steps, a hardcoded step 1 for Road Transit Inbound, and Sea Import's steps for
Sea Transit Import too, which also completed its step 2 (Request shipping line
charges from B/L). The template now marks them: Complete When Client Documents
Are In.

What: sets that flag on the rows the seed marks (Sea Import 1-2, Road Transit
Inbound 1, Sea Transit Import 1), matched by subject, then by sequence.
A template that already has a flagged row is left alone.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it.
"""

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		TEMPLATE_DEFINITIONS,
		_subject_key,
	)

	if not frappe.get_meta("CGM Task Template Item").has_field("completes_on_intake"):
		return

	for definition in TEMPLATE_DEFINITIONS:
		name = definition["template_name"]
		wanted = [row for row in definition["tasks"] if row.get("completes_on_intake")]
		if not wanted or not frappe.db.exists("CGM Task Template", name):
			continue
		rows = frappe.get_all(
			"CGM Task Template Item",
			filters={"parent": name, "parenttype": "CGM Task Template"},
			fields=["name", "sequence_no", "subject", "completes_on_intake"],
		)
		if any(row.completes_on_intake for row in rows):
			continue

		by_subject = {_subject_key(row.subject): row for row in rows}
		by_sequence = {int(row.sequence_no or 0): row for row in rows}
		marked = []
		for seed in wanted:
			row = by_subject.get(_subject_key(seed["subject"])) or by_sequence.get(int(seed["sequence_no"]))
			if row:
				frappe.db.set_value(
					"CGM Task Template Item", row.name, "completes_on_intake", 1, update_modified=False
				)
				marked.append(int(row.sequence_no or 0))
		print(f"Intake tasks on {name}: {sorted(marked)}")
