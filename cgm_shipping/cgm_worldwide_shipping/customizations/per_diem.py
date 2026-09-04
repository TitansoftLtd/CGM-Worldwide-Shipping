"""CGM job group structure and the per diem rates attached to it.

Source of truth: ``files/CGM Job Group Structure & Per diems.pdf`` - the signed HR
document that grades every post from **M** (Chairman / Director) down to **A**
(unclassified casuals and attachés) and sets a daily per diem rate per group.

The structure is stored on ERPNext's own **Employee Grade** master, one grade per
job group letter, extended by the Customize Form export at
`custom/employee_grade.json`:

* ``custom_per_diem_rate`` - daily rate in company currency.
* ``custom_job_group_designations`` - the posts that sit in the group.

Seniority is not recorded anywhere: the structure below is in the document's own order,
which is all the seeding needs.

Employee Grade is readable only by HR Manager, HR User and System Manager, so the
rate table stays with HR: **no per diem field is added to Employee**. An employee's
rate is resolved from their grade at the moment they claim, and is stamped onto the
Expense Claim / Employee Advance row so submitted documents keep the rate they used.

Seeding is deliberately non-destructive - a grade that already exists only has its
*blank* fields filled in, so a rate HR revises in the desk survives every migrate.
"""

from __future__ import annotations

import re
import unicodedata

import frappe
from frappe import _
from frappe.utils import flt

#: Expense Claim Type that turns an expense row into a per diem row.
PER_DIEM_EXPENSE_CLAIM_TYPE = "Per Diem"

#: Titles in the signed structure that already exist in the Designation master under
#: slightly different wording. Mapping them keeps the structure pointing at the
#: designations employees actually hold, instead of creating near-duplicates.
DESIGNATION_ALIASES = {
	"Declarants": "Declarant",
	"Senior Supervisor": "Supervisor - Field Operations",
	"Senior Operations Supervisor": "Supervisor - Operations",
	"Quality Assurance & Project Co-Ordinator": "Quality Assurance & Projects Coordinator",
	"IT Executive": "ICT Executive",
	"Accounts Assistant": "Finance Assistant",
	"Office Admin Executive": "Admin Executive",
	"Operations Officer - Tracking & Transport": "Operations Officer",
	"Field Operations Officer": "Operations - Field Officer",
	"Assistant Group Sales & Marketing Manager": "Assistant Sales & Marketing Manager",
	# Kept ASCII so the Designation record name stays URL-safe.
	"Unclassified (Casuals, Attachés)": "Unclassified (Casuals, Attaches)",
}

JOB_GROUP_STRUCTURE = (
	{
		"job_group": "M",
		"per_diem_rate": 8000.0,
		"posts": (
			{"title": "Chairman"},
			{"title": "Director"},
		),
	},
	{
		"job_group": "L",
		"per_diem_rate": 3500.0,
		"posts": (
			{"title": "Group HR & Admin Manager", "holders": ("Shirleen Ngeno",)},
			{"title": "Group Chief Finance Officer", "holders": ("Emmanuel Ajas",)},
			{"title": "Group Sales & Marketing Officer", "holders": ("Mercy Mbogo",)},
			{"title": "Group Operations Manager"},
		),
	},
	{
		"job_group": "K",
		"per_diem_rate": 3000.0,
		"posts": (
			{"title": "Assistant Group Finance Manager", "holders": ("Maryann Ndungu",)},
			{"title": "Assistant Group Sales & Marketing Manager", "holders": ("Fatma Hassan",)},
		),
	},
	{
		"job_group": "J",
		"per_diem_rate": 2500.0,
		"posts": (
			{"title": "Operations Manager", "holders": ("Joseph Njoki",)},
		),
	},
	{
		"job_group": "I",
		"per_diem_rate": 2000.0,
		"posts": (
			{"title": "Senior Supervisor", "holders": ("Francis Makosolo",)},
		),
	},
	{
		"job_group": "H",
		"per_diem_rate": 2000.0,
		"posts": (
			{
				"title": "Declarants",
				"holders": ("Michael Mwendwa", "Robert Karimi", "Hamilton Mwakitele"),
			},
			{"title": "Senior Operations Supervisor", "holders": ("Felix Gor",)},
			{"title": "Quality Assurance & Project Co-Ordinator", "holders": ("Mary Chemtai",)},
			{"title": "Accountant"},
			{"title": "Freight Quotation & Business Development Executive"},
		),
	},
	{
		"job_group": "G",
		"per_diem_rate": 2000.0,
		"posts": (
			{"title": "IT Executive", "holders": ("Anna Auma",)},
			{"title": "Digital Marketing Executive", "holders": ("Brian Karuiru",)},
			{"title": "Accounts Assistant", "holders": ("Jackson Amunabi",)},
			{"title": "Office Admin Executive", "holders": ("Elynah Nkatha",)},
			{"title": "Operations Admin Executive", "holders": ("Faith Kaburu",)},
		),
	},
	{
		"job_group": "F",
		"per_diem_rate": 2000.0,
		"posts": (
			{"title": "Operations Supervisor", "holders": ("George Asowa",)},
			{"title": "Operations Officer - Tracking & Transport", "holders": ("Hilda Chepngeno",)},
		),
	},
	{
		"job_group": "E",
		"per_diem_rate": 2000.0,
		"posts": (
			{
				"title": "Field Operations Officer",
				"holders": (
					"Simon Mjomba",
					"Joseph Ngatia",
					"Michael Kabuthia",
					"Emmanuel Denja",
					"Philip Obiero",
					"Martin Mwangi",
				),
			},
		),
	},
	{
		"job_group": "D",
		"per_diem_rate": 2000.0,
		"posts": (
			{"title": "Assistant Field Operations Officer", "holders": ("Moses Odhiambo",)},
		),
	},
	{
		"job_group": "C",
		"per_diem_rate": 2000.0,
		"posts": (
			{"title": "Office Assistant", "holders": ("Justus Oduor", "Selphah Schola")},
		),
	},
	{
		"job_group": "B",
		"per_diem_rate": 2000.0,
		"posts": (
			{"title": "Interns"},
		),
	},
	{
		"job_group": "A",
		"per_diem_rate": 2000.0,
		"posts": (
			{"title": "Unclassified (Casuals, Attachés)"},
		),
	},
)


# ---------------------------------------------------------------------------
# Setup - called from install.after_migrate
# ---------------------------------------------------------------------------
PER_DIEM_RATE_ROLES = frozenset({"HR Manager", "HR User", "System Manager", "Administrator"})


def ensure_per_diem_setup() -> None:
	"""Idempotent installer for the job group structure and the per diem claim type.

	Runs after `sync_customizations` has applied `custom/employee_grade.json`, so the
	job group fields this writes to are already on Employee Grade.
	"""
	ensure_per_diem_expense_claim_type()
	seed_job_group_structure()
	warn_if_per_diem_rates_are_not_hr_only()


def warn_if_per_diem_rates_are_not_hr_only() -> None:
	"""Log an error if a non-HR role can read the per diem rate table.

	The rates live on Employee Grade precisely because only HR can open it. This app
	does not own that doctype's permissions - `custom/employee_grade.json` ships an
	empty ``custom_perms`` on purpose - so instead of silently re-asserting them, a
	drift is surfaced in the Error Log for HR to act on.
	"""
	roles = set(
		frappe.get_all(
			"Custom DocPerm",
			filters={"parent": "Employee Grade", "permlevel": 0, "read": 1},
			pluck="role",
		)
	)
	if not roles:
		roles = set(
			frappe.get_all(
				"DocPerm",
				filters={"parent": "Employee Grade", "permlevel": 0, "read": 1},
				pluck="role",
			)
		)

	leaked = sorted(roles - PER_DIEM_RATE_ROLES)
	if not leaked:
		return

	frappe.log_error(
		title="CGM per diem rates readable outside HR",
		message=(
			"These roles can read Employee Grade, and with it the per diem rate for "
			"every job group:\n"
			+ "\n".join(f"- {role}" for role in leaked)
			+ "\n\nRemove read on Employee Grade in Role Permission Manager if that "
			"was not intended."
		),
	)


def ensure_per_diem_expense_claim_type() -> None:
	"""Create the Per Diem Expense Claim Type if it is missing.

	No default account is seeded - Finance maps it to a ledger per company, exactly
	as they do for the stock claim types shipped by HRMS.
	"""
	if frappe.db.exists("Expense Claim Type", PER_DIEM_EXPENSE_CLAIM_TYPE):
		return

	frappe.get_doc(
		{
			"doctype": "Expense Claim Type",
			"expense_type": PER_DIEM_EXPENSE_CLAIM_TYPE,
			"description": _(
				"Daily subsistence allowance. The amount is calculated from the "
				"employee's job group rate on Employee Grade."
			),
		}
	).insert(ignore_permissions=True)


def seed_job_group_structure() -> None:
	"""Create the A-M Employee Grades from the signed structure.

	Seed-only for values HR owns: an existing grade keeps the rate and rank already
	on it, and only blank fields are filled. The designation table is rebuilt only
	when it is empty, so posts added or retired in the desk are not reverted.
	"""
	if not frappe.db.has_column("Employee Grade", "custom_per_diem_rate"):
		# custom/employee_grade.json has not been applied yet; nothing to seed into.
		return

	for group in JOB_GROUP_STRUCTURE:
		name = group["job_group"]
		rows = _designation_rows(group["posts"])

		if not frappe.db.exists("Employee Grade", name):
			doc = frappe.get_doc(
				{
					"doctype": "Employee Grade",
					"__newname": name,
					"custom_per_diem_rate": group["per_diem_rate"],
					"custom_job_group_designations": rows,
				}
			)
			doc.insert(ignore_permissions=True)
			continue

		doc = frappe.get_doc("Employee Grade", name)
		dirty = False
		if not flt(doc.get("custom_per_diem_rate")):
			doc.custom_per_diem_rate = group["per_diem_rate"]
			dirty = True
		if not doc.get("custom_job_group_designations"):
			doc.set("custom_job_group_designations", rows)
			dirty = True
		if dirty:
			doc.save(ignore_permissions=True)


def _designation_rows(posts: tuple[dict, ...]) -> list[dict]:
	"""Build the designation child rows for a group, creating missing Designations."""
	rows = []
	for post in posts:
		designation = DESIGNATION_ALIASES.get(post["title"], post["title"])
		if not frappe.db.exists("Designation", designation):
			frappe.get_doc(
				{"doctype": "Designation", "designation_name": designation}
			).insert(ignore_permissions=True)
		rows.append({"designation": designation})
	return rows


# ---------------------------------------------------------------------------
# Backfill - grading the people named in the document
# ---------------------------------------------------------------------------


def assign_job_groups_from_structure() -> dict:
	"""Set ``Employee.grade`` from the signed structure.

	Two passes, most specific first, and only ever onto employees with no grade yet -
	a grade set by HR is never overwritten:

	1. **Office holder** - the person named against a post in the document.
	2. **Designation** - anyone else holding a post that the structure grades.

	Returns a summary so the caller (patch or bench execute) can report what it did
	and, more usefully, what it could not place.
	"""
	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=["name", "employee_name", "designation", "grade"],
	)
	ungraded = [e for e in employees if not e.grade]

	assigned: list[dict] = []
	unmatched_holders: list[str] = []
	by_name: dict[str, str] = {}

	for group in JOB_GROUP_STRUCTURE:
		for post in group["posts"]:
			for holder in post.get("holders", ()):
				match = _match_employee(holder, employees)
				if not match:
					unmatched_holders.append(f"{holder} ({group['job_group']})")
					continue
				by_name[match] = group["job_group"]

	designation_groups = _designation_to_job_group()

	for employee in ungraded:
		job_group = by_name.get(employee.name)
		reason = "office holder"
		if not job_group and employee.designation:
			job_group = designation_groups.get(employee.designation)
			reason = "designation"
		if not job_group:
			continue
		frappe.db.set_value("Employee", employee.name, "grade", job_group)
		assigned.append(
			{
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"job_group": job_group,
				"matched_by": reason,
			}
		)

	assigned_ids = {row["employee"] for row in assigned}
	return {
		"assigned": assigned,
		"ungraded": [
			{"employee": e.name, "employee_name": e.employee_name, "designation": e.designation}
			for e in ungraded
			if e.name not in assigned_ids
		],
		"unmatched_office_holders": unmatched_holders,
	}


def _designation_to_job_group() -> dict[str, str]:
	"""Map each designation to the job group that holds it.

	Read from the live Employee Grade tables rather than the seed constant, so posts
	HR has since added or moved are honoured. :func:`validate_job_group_designations`
	guarantees a designation sits in at most one grade, so the map is unambiguous by
	construction. Falls back to the document for a site where nothing is seeded yet.
	"""
	rows = frappe.get_all(
		"CGM Job Group Designation",
		filters={"parenttype": "Employee Grade"},
		fields=["designation", "parent"],
	)
	if rows:
		return {row.designation: row.parent for row in rows if row.designation}

	mapping: dict[str, str] = {}
	for group in JOB_GROUP_STRUCTURE:
		for post in group["posts"]:
			title = post["title"]
			mapping.setdefault(DESIGNATION_ALIASES.get(title, title), group["job_group"])
	return mapping


def _normalise_name(value: str) -> frozenset[str]:
	"""Name tokens, folded so ``Ndung'u`` and ``Ndungu`` compare equal."""
	folded = unicodedata.normalize("NFKD", value or "")
	folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
	folded = re.sub(r"[^a-z0-9 ]+", "", folded.lower())
	return frozenset(token for token in folded.split() if token)


def _match_employee(holder: str, employees: list) -> str | None:
	"""Resolve an office holder from the document to exactly one Employee.

	The document uses short names ("Philip Obiero") against fuller records
	("Phillip Odiwour Obiero"), so full-token containment is tried first and a
	surname-only match second. Anything ambiguous is left for HR rather than guessed.
	"""
	wanted = _normalise_name(holder)
	if not wanted:
		return None

	candidates = [e for e in employees if wanted <= _normalise_name(e.employee_name)]
	if len(candidates) == 1:
		return candidates[0].name
	if candidates:
		return None

	surname = holder.split()[-1]
	surname_token = _normalise_name(surname)
	candidates = [e for e in employees if surname_token <= _normalise_name(e.employee_name)]
	return candidates[0].name if len(candidates) == 1 else None


# ---------------------------------------------------------------------------
# Rate lookup
# ---------------------------------------------------------------------------


def get_employee_per_diem_rate(employee: str) -> float:
	"""Daily per diem rate for *employee*, from the job group on their Employee Grade."""
	if not employee:
		return 0.0
	grade = frappe.db.get_value("Employee", employee, "grade")
	if not grade:
		return 0.0
	return flt(frappe.db.get_value("Employee Grade", grade, "custom_per_diem_rate"))


@frappe.whitelist()
def get_per_diem_details(employee: str) -> dict:
	"""Rate lookup for the Expense Claim / Employee Advance forms.

	Guarded on document access rather than on a role name: whoever can read the
	Employee record - the person themselves, their expense approver, HR - can see the
	rate that applies to them. The rate *table* stays on Employee Grade, which only
	HR can open.
	"""
	frappe.has_permission("Employee", "read", doc=employee, throw=True)
	grade = frappe.db.get_value("Employee", employee, "grade")
	return {
		"employee": employee,
		"job_group": grade,
		"per_diem_rate": get_employee_per_diem_rate(employee),
	}


def _require_rate(employee: str, employee_name: str | None = None) -> float:
	rate = get_employee_per_diem_rate(employee)
	if rate > 0:
		return rate

	grade = frappe.db.get_value("Employee", employee, "grade")
	if not grade:
		frappe.throw(
			_("{0} has no job group. Ask HR to set the Grade on the employee record.").format(
				employee_name or employee
			),
			title=_("Per Diem Rate Not Set"),
		)
	frappe.throw(
		_("Job group {0} has no per diem rate. Ask HR to set it on Employee Grade {0}.").format(
			grade
		),
		title=_("Per Diem Rate Not Set"),
	)
	return 0.0


# ---------------------------------------------------------------------------
# Document events
# ---------------------------------------------------------------------------


def validate_job_group_designations(doc, method=None) -> None:
	"""A designation belongs to exactly one job group.

	Two grades claiming the same post would mean two per diem rates for the same job,
	with nothing able to say which applies - the employee's rate would come down to
	which grade someone happened to set. Refused at the source instead, naming the
	grade that already holds it so HR can move it rather than hunt for it.
	"""
	rows = doc.get("custom_job_group_designations") or []

	seen: dict[str, int] = {}
	for row in rows:
		if not row.designation:
			continue
		if row.designation in seen:
			frappe.throw(
				_("Row #{0}: {1} is already listed in row #{2} of this job group.").format(
					row.idx, frappe.bold(row.designation), seen[row.designation]
				),
				title=_("Designation Listed Twice"),
			)
		seen[row.designation] = row.idx

	if not seen:
		return

	clashes = frappe.get_all(
		"CGM Job Group Designation",
		filters={
			"designation": ("in", list(seen)),
			"parenttype": "Employee Grade",
			"parent": ("!=", doc.name),
		},
		fields=["designation", "parent"],
	)
	if not clashes:
		return

	frappe.throw(
		_("A designation can sit in only one job group. Remove it from the other grade first:")
		+ "<ul>"
		+ "".join(
			_("<li>{0} is already in job group {1}</li>").format(
				frappe.bold(clash.designation), frappe.bold(clash.parent)
			)
			for clash in clashes
		)
		+ "</ul>",
		title=_("Designation already in another Job Group"),
	)


def validate_expense_claim_per_diem(doc, method=None) -> None:
	"""Price per diem rows from the claimant's job group.

	The days are what the employee enters; the rate and the amount are derived, so a
	claim can never be filed at a rate the structure does not give them. Rows of any
	other expense type keep their per diem fields clear.
	"""
	for row in doc.get("expenses") or []:
		if row.expense_type != PER_DIEM_EXPENSE_CLAIM_TYPE:
			row.custom_per_diem_days = 0
			row.custom_per_diem_rate = 0
			continue

		days = flt(row.custom_per_diem_days)
		if days <= 0:
			frappe.throw(
				_("Row #{0}: enter the number of days claimed for {1}.").format(
					row.idx, PER_DIEM_EXPENSE_CLAIM_TYPE
				),
				title=_("Per Diem Days Required"),
			)

		rate = _require_rate(doc.employee, doc.get("employee_name"))
		row.custom_per_diem_rate = rate
		row.amount = flt(days * rate, row.precision("amount"))
		if flt(row.sanctioned_amount) > row.amount or not flt(row.sanctioned_amount):
			row.sanctioned_amount = row.amount


def validate_employee_advance_per_diem(doc, method=None) -> None:
	"""Price a per diem advance from the employee's job group."""
	days = flt(doc.get("custom_per_diem_days"))
	if days <= 0:
		doc.custom_per_diem_rate = 0
		return

	rate = _require_rate(doc.employee, doc.get("employee_name"))
	doc.custom_per_diem_rate = rate
	doc.advance_amount = flt(days * rate, doc.precision("advance_amount"))
