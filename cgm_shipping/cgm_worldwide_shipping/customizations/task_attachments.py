"""Re-uploading a document to a task replaces it instead of stacking up.

Frappe keeps a File record per upload and never removes the one it replaced.
Only exact repeats go, newest kept; the file on disk is reference-counted by
content hash, so it stays. A different file is a new version, not a duplicate.
"""

from __future__ import annotations

import frappe


def _task_files(task: str, file_url: str) -> list:
	return frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Task",
			"attached_to_name": task,
			"file_url": file_url,
		},
		fields=["name"],
	)


def drop_superseded_task_attachment(doc, method=None) -> None:
	"""File after_insert: remove earlier records of the same file on the same task."""
	if doc.get("attached_to_doctype") != "Task":
		return
	task = doc.get("attached_to_name")
	file_url = doc.get("file_url")
	if not task or not file_url:
		return

	try:
		rows = _task_files(task, file_url)
	except Exception:
		frappe.log_error("Could not read task attachments; duplicate left in place")
		return

	# db.delete, not delete_doc: on_trash would log a removal that did not happen,
	# and would run a disk cleanup the kept copy's content hash makes wrong.
	for row in rows:
		# Keep the upload that triggered this, never whichever sorts first: a row
		# carrying a later creation would otherwise delete the one just made.
		if row.name == doc.name:
			continue
		try:
			frappe.db.delete("File", {"name": row.name})
		except Exception:
			frappe.log_error(f"Could not drop superseded attachment {row.name}")


def newest_per_file(rows: list[dict]) -> list[dict]:
	"""One row per (task, file), newest first. For the read-only shipment roll-up."""
	seen: set[tuple] = set()
	out = []
	for row in rows:
		key = (row.get("task"), row.get("file_url"))
		if key in seen:
			continue
		seen.add(key)
		out.append(row)
	return out


def drop_existing_duplicate_task_attachments() -> int:
	"""Patch helper: collapse re-uploads already in the system. Returns how many went."""
	rows = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Task"},
		fields=["name", "attached_to_name", "file_url", "content_hash", "creation"],
		order_by="creation desc",
	)
	groups: dict[tuple, list] = {}
	for row in rows:
		if not row.attached_to_name or not row.file_url:
			continue
		groups.setdefault((row.attached_to_name, row.file_url), []).append(row)

	dropped = 0
	for copies in groups.values():
		if len(copies) < 2:
			continue
		# Byte-identical only: a differing hash is a changed file reusing a name.
		hashes = {c.content_hash for c in copies}
		if len(hashes) != 1 or not copies[0].content_hash:
			continue
		for row in copies[1:]:  # newest first, so this keeps the latest
			frappe.db.delete("File", {"name": row.name})
			dropped += 1
	return dropped
