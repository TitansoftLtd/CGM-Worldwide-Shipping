"""Collapse documents re-uploaded to the same task.

Why: Frappe keeps a File record per upload and never removes the one an Attach
field replaced, so the same receipt uploaded six times left six records. One
shipment's attachment list showed 53 rows. Production held 641 redundant records
out of 2,461.

What: for each (task, file) with more than one record, keeps the newest and drops
the rest. Only groups where every copy shares one content hash, so a changed file
reusing a name is left alone. Deleted at db level: File.on_trash would comment
"Attachment Removed" on the task when nothing was removed, and the file on disk
must stay for the copy we keep.

Idempotent. One-time - retire per docs/guides/patches.md.
"""

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_attachments import (
		drop_existing_duplicate_task_attachments,
	)

	if not frappe.db.exists("DocType", "Task"):
		return
	dropped = drop_existing_duplicate_task_attachments()
	frappe.db.commit()
	print(f"drop_duplicate_task_attachments: removed {dropped} redundant File record(s)")
