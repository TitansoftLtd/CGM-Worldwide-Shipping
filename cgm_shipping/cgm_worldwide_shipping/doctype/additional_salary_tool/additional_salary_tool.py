# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, get_first_day, get_last_day, getdate


class AdditionalSalaryTool(Document):
	pass


def _check_access():
	"""Whitelisted methods are reachable by any logged-in user over the API, so each one must
	enforce access explicitly. Instead of a hard-coded role list, this honours the doctype's own
	permissions — grant/revoke access in the Role Permission Manager for "Additional Salary Tool"
	(write), no code change needed."""
	if not frappe.has_permission("Additional Salary Tool", "write"):
		frappe.throw(_("You are not permitted to use the Additional Salary Tool."), frappe.PermissionError)


@frappe.whitelist()
def get_employees(
	company, salary_components, is_recurring=0, payroll_date=None, from_date=None, to_date=None
):
	"""Return active employees of the company, each pre-filled with the amount of any
	existing (submitted) Additional Salary for the selected components in the same period."""
	_check_access()
	return _build_employee_grid(
		company, salary_components, is_recurring, payroll_date, from_date, to_date
	)


def _build_employee_grid(
	company, salary_components, is_recurring=0, payroll_date=None, from_date=None, to_date=None
):
	if not company:
		frappe.throw(_("Please select a Company."))

	components = _parse_components(salary_components)
	if not components:
		frappe.throw(_("Please select at least one Salary Component."))

	is_recurring = int(is_recurring or 0)
	_validate_period(is_recurring, payroll_date, from_date, to_date)

	ref_date = from_date if is_recurring else payroll_date

	employees = frappe.get_all(
		"Employee",
		filters={"company": company, "status": "Active"},
		fields=["name as employee", "employee_name", "department", "branch"],
		order_by="branch asc, employee_name asc",
	)

	total_active = len(employees)
	emp_ids = [e.employee for e in employees]

	# All active employees are returned. Each is tagged with whether it has an active Salary
	# Structure Assignment in this company and its current Base, so the grid can show the Base
	# column and HR can spot/allocate the unassigned ones inline.
	assigned = _employees_with_assignment(company, emp_ids, ref_date)
	bases = _employee_bases(company, emp_ids, ref_date)
	skipped_no_assignment = total_active - len(assigned)

	# "School" for colour-coding/grouping: the Employee's Branch, falling back to Department.
	for emp in employees:
		emp["school"] = emp.get("branch") or emp.get("department") or _("Unassigned")
		emp["has_assignment"] = 1 if emp.employee in assigned else 0
		emp["base"] = bases.get(emp.employee)

	existing = _get_existing_amounts(
		company, components, emp_ids, is_recurring, payroll_date, from_date, to_date
	)

	for emp in employees:
		emp["amounts"] = existing.get(emp.employee, {})

	return {
		"employees": employees,
		"components": components,
		"total_active": total_active,
		"skipped_no_assignment": skipped_no_assignment,
	}


@frappe.whitelist()
def download_template(
	company, salary_components, is_recurring=0, payroll_date=None, from_date=None, to_date=None
):
	"""Stream an .xlsx template (Employee, Employee Name, Base + one column per selected component),
	pre-filled with any existing amounts, ready to fill offline and re-upload. The Base column is the
	employee's current Salary Structure Assignment base (blank when unassigned) and is for reference
	only — re-uploading the template ignores it (parse_template matches only Employee + components)."""
	_check_access()
	from frappe.utils.xlsxutils import build_xlsx_response

	grid = _build_employee_grid(
		company, salary_components, is_recurring, payroll_date, from_date, to_date
	)
	components = grid["components"]

	data = [["Employee", "Employee Name", "Base", *components]]
	for emp in grid["employees"]:
		amounts = emp.get("amounts") or {}
		data.append(
			[
				emp.get("employee"),
				emp.get("employee_name") or "",
				emp.get("base") or "",
				*[amounts.get(c, "") for c in components],
			]
		)

	build_xlsx_response(data, "Additional Salary Template")


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def manual_amount_salary_components(doctype, txt, searchfield, start, page_len, filters):
	"""Link-field query for the Salary Components picker. Returns only components whose amount is
	entered manually: enabled, no fixed amount, and no formula (NULL-safe via IFNULL/TRIM)."""
	_check_access()
	return frappe.db.sql(
		"""
		SELECT name
		FROM `tabSalary Component`
		WHERE disabled = 0
		  AND IFNULL(amount_based_on_formula, 0) = 0
		  AND IFNULL(amount, 0) = 0
		  AND (formula IS NULL OR TRIM(formula) = '')
		  AND ({key} LIKE %(txt)s OR name LIKE %(txt)s)
		ORDER BY
			IF(LOCATE(%(_txt)s, name) > 0, LOCATE(%(_txt)s, name), 99999),
			name
		LIMIT %(start)s, %(page_len)s
		""".format(key=searchfield or "name"),
		{
			"txt": "%%%s%%" % (txt or ""),
			"_txt": (txt or "").replace("%", ""),
			"start": start or 0,
			"page_len": page_len or 20,
		},
	)


def _load_drafts():
	"""All saved drafts as a {user: draft_json_string} dict (draft_data holds the JSON map)."""
	raw = frappe.db.get_single_value("Additional Salary Tool", "draft_data") or ""
	try:
		data = json.loads(raw) if raw else {}
	except (ValueError, TypeError):
		data = {}
	return data if isinstance(data, dict) else {}


@frappe.whitelist()
def save_draft(data):
	"""Persist the CURRENT USER's in-progress filters + entered amounts, so they can resume
	later. Drafts are stored per user, so users don't overwrite each other. `data` is a JSON
	string built on the client."""
	_check_access()
	if isinstance(data, dict):
		data = json.dumps(data)
	drafts = _load_drafts()
	drafts[frappe.session.user] = data
	frappe.db.set_single_value("Additional Salary Tool", "draft_data", json.dumps(drafts))
	return {"saved_on": frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")}


@frappe.whitelist()
def get_draft():
	"""Return the current user's saved draft (raw JSON string), or None."""
	_check_access()
	return {"data": _load_drafts().get(frappe.session.user)}


@frappe.whitelist()
def clear_draft():
	"""Discard the current user's saved draft (leaves other users' drafts untouched)."""
	_check_access()
	drafts = _load_drafts()
	if frappe.session.user in drafts:
		del drafts[frappe.session.user]
		frappe.db.set_single_value("Additional Salary Tool", "draft_data", json.dumps(drafts))
	return {"cleared": 1}


@frappe.whitelist()
def parse_template(filedata, salary_components):
	"""Decode an uploaded .xlsx (base64 data URL) and return grid rows
	[{employee, amounts: {component: amount}}] matched to the selected components by header."""
	_check_access()
	import base64

	from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

	components = _parse_components(salary_components)
	if not components:
		frappe.throw(_("Please select at least one Salary Component."))

	# filedata is a data URL ("data:...;base64,XXXX") or bare base64.
	content = base64.b64decode(filedata.split(",", 1)[-1])
	rows = read_xlsx_file_from_attached_file(fcontent=content) or []
	if len(rows) < 2:
		frappe.throw(_("The uploaded file has no data rows."))

	header = [(str(h).strip() if h is not None else "") for h in rows[0]]
	try:
		emp_col = header.index("Employee")
	except ValueError:
		frappe.throw(_("Column 'Employee' not found in the uploaded file."))

	# Map each selected component to its column (silently ignore components not in the file).
	comp_cols = {c: header.index(c) for c in components if c in header}

	result = []
	for raw in rows[1:]:
		employee = raw[emp_col] if emp_col < len(raw) else None
		if not employee:
			continue
		amounts = {}
		for c, idx in comp_cols.items():
			val = raw[idx] if idx < len(raw) else None
			amt = flt(val)
			if amt:
				amounts[c] = amt
		result.append({"employee": str(employee).strip(), "amounts": amounts})

	return {"rows": result}


@frappe.whitelist()
def create_additional_salaries(
	company,
	salary_components,
	rows,
	is_recurring=0,
	payroll_date=None,
	from_date=None,
	to_date=None,
):
	"""Create & submit one Additional Salary per (employee, component) with an amount entered.

	Each record's "Overwrite Salary Structure Amount" is set automatically: ON when that component
	already exists in the employee's Salary Structure (so this figure replaces the structured one),
	OFF otherwise (so it's an addition).

	Skips a (employee, component) when a submitted Additional Salary with the SAME amount already
	exists for the period (nothing changed).

	For recurring entries, an overlapping submitted record with a DIFFERENT amount is superseded:
	its To Date is shortened to the day before this tool's From Date (or cancelled outright when the
	new period fully covers it), then the new record is created. Each (employee, component) runs in a
	savepoint, so if creation fails the supersede is rolled back."""
	_check_access()
	if not company:
		frappe.throw(_("Please select a Company."))

	components = _parse_components(salary_components)
	if not components:
		frappe.throw(_("Please select at least one Salary Component."))

	is_recurring = int(is_recurring or 0)
	_validate_period(is_recurring, payroll_date, from_date, to_date)

	if isinstance(rows, str):
		rows = json.loads(rows)

	ref_date = from_date if is_recurring else payroll_date

	result = {
		"created": 0,
		"skipped": 0,
		"adjusted": 0,
		"cancelled": 0,
		"errors": [],
		"missing_assignment": [],
	}

	# Pre-fetch everything we need in a few batched queries instead of per (employee, component),
	# so a payroll run for hundreds of employees stays fast.
	employees_in_batch = list({str(r.get("employee")) for r in (rows or []) if r.get("employee")})
	# Currency / structure come from a Salary Structure Assignment IN THIS COMPANY only — an
	# assignment in another company must not make the employee look payable here.
	currencies = _currencies_for(employees_in_batch, ref_date, company)
	# Components already in each employee's Salary Structure → those get overwrite=1 automatically.
	structure_components = _employee_structure_components(employees_in_batch, ref_date, company)
	if is_recurring:
		overlaps_map = _recurring_overlaps_map(
			company, employees_in_batch, components, from_date, to_date
		)
	else:
		# Existing submitted one-time records anywhere in the SAME MONTH, so we supersede them
		# (cancel + recreate) instead of adding a duplicate on a different day of the month.
		existing_records = _one_time_records_in_month(
			company, employees_in_batch, components, payroll_date
		)

	for row in rows or []:
		employee = row.get("employee")
		if not employee:
			continue
		employee = str(employee)  # IDs may arrive as numbers; keep them string-keyed throughout

		amounts = row.get("amounts") or {}

		# A missing Salary Structure Assignment affects the whole employee, not a single
		# component — collect it once per employee (only if they have an amount to create) so the
		# client can offer to allocate a Salary Structure to them, rather than just erroring.
		currency = currencies.get(employee)
		if not currency:
			if any(flt(amounts.get(c)) > 0 for c in components):
				result["missing_assignment"].append(employee)
			continue

		for component in components:
			amount = flt(amounts.get(component))
			# A blank cell is simply not entered, not a meaningful "skip". Counting these made
			# the "Skipped" badge a huge number (rows x components); only genuine unchanged
			# already-exists cases below increment "skipped".
			if amount <= 0:
				continue

			# "Nothing changed" checks + records to supersede (in-memory from the pre-fetch).
			overlaps = []
			existing_recs = []
			if is_recurring:
				overlaps = overlaps_map.get((employee, component), [])
				if any(flt(o.amount) == amount for o in overlaps):
					result["skipped"] += 1
					continue
			else:
				existing_recs = existing_records.get((employee, component), [])
				# Same amount already submitted for this date → nothing to do.
				if any(flt(rec.amount) == amount for rec in existing_recs):
					result["skipped"] += 1
					continue

			# Overwrite the structured amount only when this component is part of the employee's
			# Salary Structure; for components not in it (e.g. a one-off Bonus) overwrite is moot.
			overwrite = 1 if component in structure_components.get(employee, set()) else 0

			frappe.db.savepoint("ast_row")
			try:
				# Supersede any existing submitted record for the same period so we never end up
				# with two Additional Salaries for the same employee + component + date: recurring
				# overlaps are shortened/cancelled; one-time same-date records are cancelled.
				if is_recurring:
					adjusted, cancelled = _supersede_recurring_overlaps(overlaps, from_date)
				else:
					adjusted, cancelled = 0, _cancel_records(existing_recs)

				_create_additional_salary(
					company=company,
					employee=employee,
					component=component,
					amount=amount,
					currency=currency,
					is_recurring=is_recurring,
					payroll_date=payroll_date,
					from_date=from_date,
					to_date=to_date,
					overwrite=overwrite,
				)
				result["created"] += 1
				result["adjusted"] += adjusted
				result["cancelled"] += cancelled
			except Exception as e:
				frappe.db.rollback(save_point="ast_row")
				result["errors"].append(f"{employee} / {component}: {e}")

	# Attach names to the missing-assignment employees so the client can list them clearly.
	if result["missing_assignment"]:
		name_rows = frappe.get_all(
			"Employee",
			filters={"name": ["in", result["missing_assignment"]]},
			fields=["name", "employee_name"],
		)
		names = {str(r.name): r.employee_name for r in name_rows}
		result["missing_assignment"] = [
			{"employee": str(e), "employee_name": names.get(str(e), "")}
			for e in result["missing_assignment"]
		]

	return result


@frappe.whitelist()
def assign_salary_structure(salary_structure, from_date, employees, company=None):
	"""Create & submit a Salary Structure Assignment per employee, like the standard Salary
	Structure Allocation flow — reuses HRMS's create_salary_structure_assignment (which resolves the
	Default Payroll Payable Account, currency and validations).

	`employees` is a list of {employee, base}; each row carries its own Base. The assignment's From
	Date is the given date, except for employees who joined after it (new hires) — those start from
	their joining date, since an assignment can't precede the joining date. Returns {created, errors}."""
	_check_access()
	if not (salary_structure and from_date):
		frappe.throw(_("Salary Structure and From Date are required."))

	if isinstance(employees, str):
		employees = json.loads(employees)

	rows = []
	for e in employees or []:
		if isinstance(e, dict):
			emp, base = e.get("employee"), flt(e.get("base"))
		else:
			emp, base = e, 0
		if emp:
			rows.append((str(emp), base))
	if not rows:
		return {"created": 0, "errors": []}

	from hrms.payroll.doctype.salary_structure.salary_structure import create_salary_structure_assignment

	ss = frappe.get_doc("Salary Structure", salary_structure)
	base_from = getdate(from_date)

	joining = {
		r.name: r.date_of_joining
		for r in frappe.get_all(
			"Employee",
			filters={"name": ["in", [emp for emp, _ in rows]]},
			fields=["name", "date_of_joining"],
		)
	}

	created = 0
	errors = []
	for emp, base in rows:
		# An assignment can't start before the employee joined — use the joining date when they
		# joined after the chosen From Date (new employee).
		eff_from = base_from
		doj = joining.get(emp)
		if doj and getdate(doj) > eff_from:
			eff_from = getdate(doj)

		if frappe.db.exists(
			"Salary Structure Assignment",
			{
				"employee": emp,
				"salary_structure": ss.name,
				"from_date": eff_from,
				"company": ss.company,
				"docstatus": 1,
			},
		):
			continue

		frappe.db.savepoint("ast_ssa")
		try:
			create_salary_structure_assignment(
				employee=emp,
				salary_structure=ss.name,
				company=ss.company,
				currency=ss.currency,
				from_date=eff_from,
				base=base or None,
			)
			created += 1
		except Exception as e:
			frappe.db.rollback(save_point="ast_ssa")
			errors.append(f"{emp}: {e}")

	return {"created": created, "errors": errors}


@frappe.whitelist()
def assign_structure_with_base(company, employee, base, from_date, replace=0):
	"""Inline allocation from the grid's Base column: create & submit a Salary Structure Assignment
	for one employee using the company's LATEST active Salary Structure and the given base. The
	assignment starts on from_date, or the employee's joining date if they joined later.

	An employee can only have one assignment per From Date. If one already exists on that date this
	returns {needs_replace: 1, ...} (instead of erroring) so the client can confirm; calling again
	with replace=1 cancels the existing one and creates the new. Returns the effective base/date."""
	_check_access()
	if not (company and employee):
		frappe.throw(_("Company and Employee are required."))
	employee = str(employee)
	replace = int(replace or 0)

	structure = frappe.get_all(
		"Salary Structure",
		filters={"company": company, "is_active": "Yes", "docstatus": 1},
		fields=["name", "currency"],
		order_by="creation desc",
		limit=1,
	)
	if not structure:
		frappe.throw(_("No active Salary Structure found for {0}. Create one first.").format(company))
	ss = structure[0]

	eff_from = getdate(from_date) if from_date else getdate(frappe.utils.nowdate())
	doj = frappe.db.get_value("Employee", employee, "date_of_joining")
	if doj and getdate(doj) > eff_from:
		eff_from = getdate(doj)

	# Only one submitted assignment is allowed per (employee, from_date). Ask before replacing.
	existing = frappe.get_all(
		"Salary Structure Assignment",
		filters={"employee": employee, "from_date": eff_from, "docstatus": 1},
		pluck="name",
	)
	if existing and not replace:
		return {"needs_replace": 1, "existing": existing, "from_date": str(eff_from)}

	from hrms.payroll.doctype.salary_structure.salary_structure import create_salary_structure_assignment

	if existing:
		for n in existing:
			frappe.get_doc("Salary Structure Assignment", n).cancel()

	name = create_salary_structure_assignment(
		employee=employee,
		salary_structure=ss.name,
		company=company,
		currency=ss.currency,
		from_date=eff_from,
		base=flt(base) or None,
	)

	return {
		"created": 1,
		"assignment": name,
		"salary_structure": ss.name,
		"from_date": str(eff_from),
		"base": flt(base),
	}


def _parse_components(salary_components):
	if isinstance(salary_components, str):
		salary_components = json.loads(salary_components)

	result = []
	seen = set()
	for c in salary_components or []:
		if isinstance(c, dict):
			c = c.get("salary_component")
		if c and c not in seen:
			seen.add(c)
			result.append(c)
	return result


def _validate_period(is_recurring, payroll_date, from_date, to_date):
	if is_recurring:
		if not (from_date and to_date):
			frappe.throw(_("From Date and To Date are required for recurring Additional Salary."))
		if getdate(from_date) > getdate(to_date):
			frappe.throw(_("From Date cannot be after To Date."))
	elif not payroll_date:
		frappe.throw(_("Payroll Date is required."))


def _period_bounds(is_recurring, payroll_date, from_date, to_date):
	"""[start, end] dates the selected run covers: the From/To range for recurring, otherwise the
	WHOLE MONTH of the payroll date (so any posting date in that month matches the same records)."""
	if is_recurring:
		return getdate(from_date), getdate(to_date)
	d = getdate(payroll_date)
	return get_first_day(d), get_last_day(d)


def _get_existing_amounts(company, components, employees, is_recurring, payroll_date, from_date, to_date):
	"""Latest existing amount per (employee, component) that already applies to the selected period,
	so the grid pre-fills them and HR doesn't create duplicate Additional Salaries within the same
	month / date range.

	Matches submitted Additional Salaries that are either a one-time record posted IN the period, or
	a recurring record whose From/To range OVERLAPS the period."""
	if not employees:
		return {}

	start, end = _period_bounds(is_recurring, payroll_date, from_date, to_date)
	base = {
		"docstatus": 1,
		"company": company,
		"employee": ["in", employees],
		"salary_component": ["in", components],
	}

	one_time = frappe.get_all(
		"Additional Salary",
		filters={**base, "is_recurring": 0, "payroll_date": ["between", [start, end]]},
		fields=["employee", "salary_component", "amount", "modified"],
	)
	recurring = frappe.get_all(
		"Additional Salary",
		# `disabled: 0` mirrors _recurring_overlaps_map (the supersede set). A disabled recurring
		# record is inactive — if we pre-filled from it, the create flow wouldn't supersede it and
		# would create a duplicate.
		filters={
			**base,
			"is_recurring": 1,
			"disabled": 0,
			"from_date": ["<=", end],
			"to_date": [">=", start],
		},
		fields=["employee", "salary_component", "amount", "modified"],
	)

	amounts = {}
	# Latest record (by modified) wins when more than one applies to the same key.
	for r in sorted(one_time + recurring, key=lambda r: r.modified):
		amounts.setdefault(r.employee, {})[r.salary_component] = flt(r.amount)
	return amounts


def _recurring_overlaps_map(company, employees, components, from_date, to_date):
	"""{(employee, component): [overlapping recurring Additional Salary rows]} for the batch."""
	if not employees:
		return {}

	rows = frappe.get_all(
		"Additional Salary",
		filters={
			"docstatus": 1,
			"disabled": 0,
			"is_recurring": 1,
			"company": company,
			"employee": ["in", employees],
			"salary_component": ["in", components],
			"from_date": ["<=", getdate(to_date)],
			"to_date": [">=", getdate(from_date)],
		},
		fields=["name", "employee", "salary_component", "from_date", "to_date", "amount"],
	)

	overlaps = {}
	for r in rows:
		overlaps.setdefault((r.employee, r.salary_component), []).append(r)
	return overlaps


def _supersede_recurring_overlaps(overlaps, from_date):
	"""Close off overlapping recurring records so the new one can be created without overlap.

	Shorten each overlap's To Date to the day before `from_date`; if that would precede its own
	From Date (new period fully covers it), cancel it instead. Returns (adjusted, cancelled) counts."""
	cutoff = add_days(getdate(from_date), -1)
	adjusted = cancelled = 0

	for o in overlaps:
		if cutoff < getdate(o.from_date):
			frappe.get_doc("Additional Salary", o.name).cancel()
			cancelled += 1
		else:
			frappe.db.set_value("Additional Salary", o.name, "to_date", cutoff)
			adjusted += 1

	return adjusted, cancelled


def _one_time_records_in_month(company, employees, components, payroll_date):
	"""{(employee, component): [submitted one-time Additional Salary records]} posted ANYWHERE in the
	same month as payroll_date, so a one-time run supersedes (cancels) them instead of creating a
	duplicate on a different day of the same month."""
	if not employees:
		return {}

	d = getdate(payroll_date)
	rows = frappe.get_all(
		"Additional Salary",
		filters={
			"docstatus": 1,
			"is_recurring": 0,
			"company": company,
			"employee": ["in", employees],
			"salary_component": ["in", components],
			"payroll_date": ["between", [get_first_day(d), get_last_day(d)]],
		},
		fields=["name", "employee", "salary_component", "amount"],
	)

	records = {}
	for r in rows:
		records.setdefault((r.employee, r.salary_component), []).append(r)
	return records


def _cancel_records(records):
	"""Cancel each given Additional Salary; returns how many were cancelled."""
	cancelled = 0
	for r in records:
		frappe.get_doc("Additional Salary", r.name).cancel()
		cancelled += 1
	return cancelled


def _employees_with_assignment(company, employees, ref_date):
	"""Set of employees (from the given list) that have a submitted Salary Structure Assignment
	effective on/before ref_date — i.e. employees who can actually be paid."""
	if not employees:
		return set()

	filters = {"company": company, "docstatus": 1, "employee": ["in", employees]}
	if ref_date:
		filters["from_date"] = ["<=", getdate(ref_date)]

	return set(
		frappe.get_all("Salary Structure Assignment", filters=filters, pluck="employee", distinct=True)
	)


def _currencies_for(employees, ref_date, company):
	"""{employee: currency} from each employee's latest assignment on/before ref_date for company."""
	if not employees:
		return {}

	rows = frappe.get_all(
		"Salary Structure Assignment",
		filters={
			"employee": ["in", employees],
			"company": company,
			"docstatus": 1,
			"from_date": ["<=", getdate(ref_date)],
		},
		fields=["employee", "currency", "from_date"],
		order_by="from_date asc",  # ascending so the latest assignment overwrites earlier ones
	)

	currencies = {}
	for r in rows:
		if r.currency:
			currencies[r.employee] = r.currency
	return currencies


def _employee_bases(company, employees, ref_date):
	"""{employee: base} from each employee's latest assignment on/before ref_date for company."""
	if not employees:
		return {}

	rows = frappe.get_all(
		"Salary Structure Assignment",
		filters={
			"employee": ["in", employees],
			"company": company,
			"docstatus": 1,
			"from_date": ["<=", getdate(ref_date)],
		},
		fields=["employee", "base", "from_date"],
		order_by="from_date asc",  # ascending so the latest assignment overwrites earlier ones
	)

	bases = {}
	for r in rows:
		bases[r.employee] = flt(r.base)
	return bases


def _employee_structure_components(employees, ref_date, company):
	"""{employee: set(salary_component)} present in each employee's effective Salary Structure
	(earnings + deductions), based on their latest assignment on/before ref_date for company."""
	if not employees:
		return {}

	rows = frappe.get_all(
		"Salary Structure Assignment",
		filters={
			"employee": ["in", employees],
			"company": company,
			"docstatus": 1,
			"from_date": ["<=", getdate(ref_date)],
		},
		fields=["employee", "salary_structure", "from_date"],
		order_by="from_date asc",  # ascending so the latest assignment overwrites earlier ones
	)

	emp_structure = {}
	for r in rows:
		if r.salary_structure:
			emp_structure[r.employee] = r.salary_structure

	structures = list(set(emp_structure.values()))
	if not structures:
		return {}

	details = frappe.get_all(
		"Salary Detail",
		filters={"parenttype": "Salary Structure", "parent": ["in", structures]},
		fields=["parent", "salary_component"],
	)
	structure_components = {}
	for d in details:
		structure_components.setdefault(d.parent, set()).add(d.salary_component)

	return {emp: structure_components.get(struct, set()) for emp, struct in emp_structure.items()}


def _create_additional_salary(
	company, employee, component, amount, currency, is_recurring, payroll_date, from_date, to_date, overwrite
):
	doc = frappe.new_doc("Additional Salary")
	doc.company = company
	doc.employee = employee
	doc.salary_component = component
	doc.amount = amount
	doc.currency = currency
	doc.overwrite_salary_structure_amount = overwrite
	doc.ref_doctype = "Additional Salary Tool"

	if is_recurring:
		doc.is_recurring = 1
		doc.from_date = from_date
		doc.to_date = to_date
	else:
		doc.is_recurring = 0
		doc.payroll_date = payroll_date

	doc.insert()
	doc.submit()
	return doc.name
