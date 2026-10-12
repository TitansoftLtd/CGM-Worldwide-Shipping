"""One shape for every "you cannot complete this yet" dialog.
"""

import frappe


def blocked_dialog(
	title: str,
	lead: str,
	items: list[tuple[str, str]],
	*,
	indicator: str = "orange",
) -> None:
	"""Raise a dialog listing what is outstanding and what to do about each item.

	`items` is (what is missing, what to do). Always raises, so it reads as a guard
	at the point of use - the same contract `frappe.throw` has.
	"""
	body = [f"<p>{lead}</p>", "<ul>"]
	for label, detail in items:
		body.append(f"<li><b>{label}</b><br>{detail}</li>")
	body.append("</ul>")
	frappe.msgprint(
		"".join(body),
		title=title,
		indicator=indicator,
		raise_exception=frappe.ValidationError,
	)


def task_link(task_name: str, fallback: str = "") -> str:
	"""A clickable task link for dialog text, falling back to plain words.

	Every dialog that blames another record should let the reader open it, rather
	than naming it and leaving them to search.
	"""
	if not task_name:
		return fallback
	label = frappe.db.get_value("Task", task_name, "subject") or task_name
	return frappe.utils.get_link_to_form("Task", task_name, label)
