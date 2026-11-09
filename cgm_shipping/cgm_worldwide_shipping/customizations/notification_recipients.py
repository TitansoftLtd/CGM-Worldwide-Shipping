"""Nothing the system sends reaches a login that has been disabled.

A disabled user has left. Frappe drops them from a role recipient already, but not
from the other ways a notification is addressed - a field on the document, a static
cc, the assignee list - and `notification_routing` resolves a role to its assignees
and appends their addresses itself, which skips Frappe's check entirely. On
production that is 27 open assignments belonging to people who have gone, 26 of them
on Tasks, and their mobile numbers are still on file.

Filtered in one place rather than per notification, because who holds a role and who
a field points at both change without anyone editing the rule.

Order matters. A departed assignee is dropped when the assignee is *chosen*
(`live_logins`), not at the end, so a routed role still falls back to its live
holders. Filtering only the finished list would send the notification nowhere, which
is how the leave watch notices went missing in the first place.
"""

from __future__ import annotations

import frappe

#: Digits compared when matching a phone number, so 0796770725, +254796770725 and
#: 254796770725 are recognised as the same person.
TAIL = 9


def _norm(value) -> str:
	return (value or "").strip().lower()


def _tail(number) -> str:
	digits = "".join(c for c in str(number or "") if c.isdigit())
	return digits[-TAIL:] if len(digits) >= TAIL else ""


def _disabled_users(fields: list[str]) -> list:
	"""Users who have left. Unfiltered on purpose: this runs in background jobs."""
	try:
		return frappe.get_all("User", filters={"enabled": 0}, fields=fields)
	except Exception:
		# Never let this stop a notification going out to live people.
		frappe.log_error("Could not read disabled users; recipients unfiltered")
		return []


def gone_addresses() -> set[str]:
	"""Logins and email addresses of users who have left."""
	out: set[str] = set()
	for u in _disabled_users(["name", "email"]):
		out.update({_norm(u.name), _norm(u.email)})
	out.discard("")
	return out


def gone_numbers() -> set[str]:
	"""Phone numbers of users who have left, from their User and Employee records.

	Both, because they disagree: for every departed employee on production the
	Employee cell number differs from the User mobile, and in one case the real
	number is only on the Employee record. Reading User alone would have texted them.
	"""
	out: set[str] = set()
	logins = []
	for u in _disabled_users(["name", "mobile_no", "phone"]):
		logins.append(u.name)
		out.update({_tail(u.mobile_no), _tail(u.phone)})
	if logins:
		try:
			for e in frappe.get_all(
				"Employee", filters={"user_id": ["in", logins]}, fields=["cell_number"]
			):
				out.add(_tail(e.cell_number))
		except Exception:
			frappe.log_error("Could not read employee numbers of disabled users")
	out.discard("")
	return out


def gone_logins() -> set[str]:
	"""Logins of users who have left."""
	try:
		logins = frappe.get_all("User", filters={"enabled": 0}, pluck="name")
	except Exception:
		frappe.log_error("Could not read disabled users; recipients unfiltered")
		return set()
	return {_norm(x) for x in logins} - {""}


def _report(why: str, dropped: list) -> None:
	"""Say so. A recipient dropped in silence is a notification nobody can trace."""
	if dropped:
		frappe.logger("cgm_notifications").info(
			f"{why or 'outgoing mail'}: dropped disabled recipients {sorted(map(str, dropped))}"
		)


def live_addresses(addresses, why: str = "") -> list[str]:
	"""Drop addresses belonging to a disabled login. A non-user is left alone."""
	gone = gone_addresses()
	kept, dropped = [], []
	for a in addresses or []:
		(dropped if _norm(a) in gone else kept).append(a)
	_report(why, dropped)
	return kept


def live_numbers(numbers, why: str = "") -> list[str]:
	"""Drop phone numbers belonging to a disabled login."""
	gone = gone_numbers()
	kept, dropped = [], []
	for n in numbers or []:
		(dropped if _tail(n) in gone else kept).append(n)
	_report(why, dropped)
	return kept


def live_logins(users, why: str = "") -> list[str]:
	"""Drop users who have left, before they are chosen as the recipient.

	Early so a routed role whose only assignee has gone falls back to the role
	instead of reaching nobody.
	"""
	gone = gone_logins()
	kept, dropped = [], []
	for u in users or []:
		(dropped if _norm(u) in gone else kept).append(u)
	_report(why, dropped)
	return kept


def drop_disabled_from_email_queue(doc, method=None) -> None:
	"""Backstop for mail queued outside a Notification: assignments, workflow, ERPNext.

	Left alone when a Communication is behind it. That is somebody pressing Send, and
	their mail must go where they addressed it.
	"""
	if doc.get("communication"):
		return
	rows = doc.get("recipients") or []
	if not rows:
		return
	gone = gone_addresses()
	kept = [r for r in rows if _norm(r.get("recipient")) not in gone]
	if len(kept) == len(rows):
		return
	dropped = [r.get("recipient") for r in rows if _norm(r.get("recipient")) in gone]
	_report(f"Email Queue for {doc.get('reference_doctype')} {doc.get('reference_name')}", dropped)
	# as_value: replace the list outright rather than re-initialising each child row.
	doc.set("recipients", kept, as_value=True)
	if not kept:
		# Nothing to send. Recorded so the empty row explains itself.
		doc.error = "All recipients are disabled users. Nothing sent."
