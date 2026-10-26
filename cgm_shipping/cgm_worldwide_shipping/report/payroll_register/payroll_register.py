# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import math
import re
from collections import defaultdict

import frappe
from frappe.utils import flt, formatdate

TAXABLE_INCOME = "Taxable Income"

# Starting width for amount columns; fit_column_widths() then sizes each one to its longest
# figure. Amounts are shown without the currency symbol (see payroll_register.js).
AMOUNT_WIDTH = 96

# The grid is set at 11.5px (payroll_register.js): roughly 7px per bold digit, 6.6px per letter,
# plus the cell's padding and border.
DIGIT_PX = 7.2
LETTER_PX = 6.6
CELL_PADDING_PX = 22


def execute(filters=None):
    filters = filters or {}

    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    if from_date and to_date and from_date > to_date:
        frappe.throw("From Date cannot be after To Date.")

    salary_slips = get_salary_slips(filters)
    if not salary_slips:
        return base_columns() + summary_columns(), []

    slip_names = [ss.name for ss in salary_slips]
    included_components = get_included_components()
    meta = get_component_meta(included_components)

    # Formula-based included components are ALWAYS shown as their own column and computed (see
    # below), even when they are not part of the salary structure and so never land on a slip.
    forced = [c for c in included_components if _is_formula_component(meta.get(c))]
    forced_set = set(forced)
    forced_earning = [c for c in forced if meta[c].type == "Earning"]
    forced_deduction = [c for c in forced if meta[c].type == "Deduction"]

    earning_components, deduction_components, employer_components, has_taxable_income = get_components(
        slip_names, included_components
    )
    # Render forced components only in their dedicated zone, never twice.
    earning_components = [c for c in earning_components if c not in forced_set]
    deduction_components = [c for c in deduction_components if c not in forced_set]

    # Add the on-report deductions' metadata (abbreviations) so a forced component like
    # Taxable Salary can be positioned right after the last deduction its formula references
    # (e.g. gross_pay - NSSF - SHIF - Housing Levy → sits just before PAYE). Without these
    # abbreviations the formula matches nothing and the column falls to the end of the block.
    meta.update(get_component_meta(deduction_components))

    fields = {}
    for comp in earning_components + forced_earning:
        fields[comp] = scrub_fieldname(comp, "e_")
    for comp in deduction_components + forced_deduction:
        fields[comp] = scrub_fieldname(comp, "d_")
    for comp in employer_components:
        fields[comp] = scrub_fieldname(comp, "c_")
    ti_field = scrub_fieldname(TAXABLE_INCOME, "e_")

    columns = build_columns(
        earning_components, deduction_components, has_taxable_income,
        forced_earning, forced_deduction, fields, ti_field, meta, employer_components,
    )
    split_by_month = bool(filters.get("split_by_month"))
    if split_by_month:
        # One row per payslip, so each row says which month it was paid for.
        name_idx = next(i for i, c in enumerate(columns) if c["fieldname"] == "employee_name")
        columns.insert(name_idx + 1, {"label": "Month", "fieldname": "month", "fieldtype": "Data", "width": 80})

    component_map = get_component_amounts(slip_names, included_components)
    # Per-slip {abbr: amount} so forced components' formulas can be evaluated in the slip's context.
    slip_abbr_amounts = get_abbr_amounts(slip_names) if forced else {}

    numeric_fields = (
        [fields[c] for c in earning_components]
        + ["gross_pay"]
        + ([ti_field] if has_taxable_income else [])
        + [fields[c] for c in forced_earning]
        + [fields[c] for c in deduction_components]
        + [fields[c] for c in forced_deduction]
        + ["total_deduction", "net_pay"]
        + [fields[c] for c in employer_components]
    )

    data_rows = []
    totals = {field: 0.0 for field in numeric_fields}

    for ss in salary_slips:
        sd = component_map.get(ss.name, {})
        context = None  # built lazily only when a forced component must be computed
        row = {
            "salary_slip": ss.name,
            "employee": ss.employee,
            "employee_name": ss.employee_name,
            "month": formatdate(ss.posting_date or ss.start_date, "MMM yyyy"),
            "payment_days": flt(ss.payment_days),
            "currency": ss.currency,
            "gross_pay": flt(ss.gross_pay),
            "total_deduction": flt(ss.total_deduction),
            "net_pay": flt(ss.net_pay),
        }

        for comp in earning_components:
            row[fields[comp]] = flt(sd.get(("earnings", comp), 0))

        if has_taxable_income:
            row[ti_field] = flt(sd.get(("earnings", TAXABLE_INCOME), 0))

        # Forced components: use the slip's own amount when it has a non-zero one, otherwise compute
        # the formula in the slip's context.
        for comp in forced_earning + forced_deduction:
            pf = "earnings" if comp in forced_earning else "deductions"
            amt = flt(sd.get((pf, comp), 0))
            if not amt:
                if context is None:
                    context = build_context(ss, slip_abbr_amounts.get(ss.name, {}))
                amt = flt(eval_formula(meta[comp].formula, context))
            row[fields[comp]] = amt

        for comp in deduction_components:
            row[fields[comp]] = flt(sd.get(("deductions", comp), 0))

        for comp in employer_components:
            row[fields[comp]] = flt(sd.get(("employer_contributions", comp), 0))

        for field in numeric_fields:
            totals[field] += flt(row.get(field, 0))

        data_rows.append(row)

    if not split_by_month:
        data_rows = consolidate_by_employee(data_rows, [*numeric_fields, "payment_days"])

    totals_row = {
        "salary_slip": "Total",
        "employee": "",
        "employee_name": "Total",
        "payment_days": "",
        "currency": salary_slips[0].currency,
        "bold": 1,
    }
    totals_row.update(totals)
    data_rows.append(totals_row)

    fit_column_widths(columns, data_rows)
    return columns, data_rows


@frappe.whitelist()
def get_payroll_analysis(filters: str | dict | None = None) -> dict:
    """The figures behind the register, read the way finance reads a payroll.

    Same slips as the register (same filters). Payables are grouped by the account each amount
    is posted to, so a new statutory component appears here without any change to this report.
    """
    if not frappe.get_doc("Report", "Payroll Register").is_permitted():
        frappe.throw("Not permitted to view the Payroll Register.", frappe.PermissionError)

    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    slips = get_salary_slips(frappe._dict(filters))
    if not slips:
        return {}

    company = slips[0].company
    names = [ss.name for ss in slips]
    details = frappe.get_all(
        "Salary Detail",
        filters={"parenttype": "Salary Slip", "parent": ["in", names]},
        fields=["parent", "parentfield", "salary_component", "amount", "default_amount",
                "do_not_include_in_total", "do_not_include_in_accounts"],
    )
    accounts = {
        a.parent: a
        for a in frappe.get_all(
            "Salary Component Account",
            filters={"parenttype": "Salary Component", "company": company},
            fields=["parent", "account", "liability_account"],
        )
    }

    employer = defaultdict(float)  # slip -> employer contributions
    full_gross = defaultdict(float)  # slip -> gross for a full month
    payables = {}
    for d in details:
        amount = flt(d.amount)
        if d.parentfield == "employer_contributions":
            employer[d.parent] += amount
            account, side = (accounts.get(d.salary_component) or frappe._dict()).liability_account, "employer"
        elif d.parentfield == "deductions" and not (d.do_not_include_in_total and d.do_not_include_in_accounts):
            account, side = (accounts.get(d.salary_component) or frappe._dict()).account, "staff"
        else:
            if d.parentfield == "earnings" and not d.do_not_include_in_total:
                full_gross[d.parent] += flt(d.default_amount)
            continue

        row = payables.setdefault(account or d.salary_component, {"staff": 0.0, "employer": 0.0, "components": []})
        row[side] += amount
        if d.salary_component not in row["components"]:
            row["components"].append(d.salary_component)

    gross = sum(flt(ss.gross_pay) for ss in slips)
    employer_total = sum(employer.values())
    summary = {
        "people": len({ss.employee for ss in slips}),
        "slips": len(slips),
        "gross_pay": gross,
        "total_deduction": sum(flt(ss.total_deduction) for ss in slips),
        "net_pay": sum(flt(ss.net_pay) for ss in slips),
        "employer_contributions": employer_total,
        "cost_to_company": gross + employer_total,
    }

    roles = {}
    for ss in slips:
        r = roles.setdefault(ss.designation or "Not set", {"people": set(), "slips": 0, "gross_pay": 0.0, "employer": 0.0})
        r["people"].add(ss.employee)
        r["slips"] += 1
        r["gross_pay"] += flt(ss.gross_pay)
        r["employer"] += employer[ss.name]
    by_role = sorted(
        (
            {
                "designation": role,
                "people": len(r["people"]),
                "gross_pay": r["gross_pay"],
                "employer_contributions": r["employer"],
                "cost": r["gross_pay"] + r["employer"],
                "monthly_cost_per_person": (r["gross_pay"] + r["employer"]) / r["slips"],
            }
            for role, r in roles.items()
        ),
        key=lambda r: -r["cost"],
    )

    part_month = [
        {
            "employee": ss.employee,
            "employee_name": ss.employee_name,
            "month": formatdate(ss.posting_date or ss.start_date, "MMMM yyyy"),
            "working_days": flt(ss.total_working_days),
            "payment_days": flt(ss.payment_days),
            "full_month_gross": full_gross[ss.name],
            "gross_pay": flt(ss.gross_pay),
        }
        for ss in slips
        if flt(ss.payment_days) < flt(ss.total_working_days)
    ]

    return {
        "currency": slips[0].currency,
        "summary": summary,
        "by_role": by_role,
        "payables": [
            {"account": account, "components": r["components"], "staff": r["staff"],
             "employer": r["employer"], "total": r["staff"] + r["employer"]}
            for account, r in sorted(payables.items())
        ],
        "part_month": part_month,
    }


def consolidate_by_employee(rows, sum_fields):
    """One row per employee for a range of several months, or several payroll runs in one.

    Rows arrive ordered by employee, so the first slip's row carries the employee's details
    and each later slip only adds its amounts and payment days.
    """
    by_employee = {}
    for row in rows:
        if row["employee"] not in by_employee:
            by_employee[row["employee"]] = {**row, "salary_slip": None, "month": None}
            continue
        merged = by_employee[row["employee"]]
        for field in sum_fields:
            merged[field] = flt(merged.get(field)) + flt(row.get(field))
    return list(by_employee.values())


def fit_column_widths(columns, data_rows):
    """Size each column so its widest value fits on one line, the bold totals included.

    Headers may wrap onto two lines, so a column only needs room for its longest single word.
    """
    for col in columns:
        header = max((len(word) for word in col["label"].split()), default=0) * LETTER_PX
        values = [row.get(col["fieldname"]) for row in data_rows]

        if col["fieldtype"] == "Currency":
            longest = max((len(f"{flt(v):,.2f}") for v in values if v not in (None, "")), default=0)
            content = longest * DIGIT_PX
        elif col["fieldname"] in ("employee", "employee_name", "month"):
            content = min(max((len(str(v or "")) for v in values), default=0), 30) * LETTER_PX
        else:
            continue

        col["width"] = math.ceil(max(content, header) + CELL_PADDING_PX)


def _is_formula_component(m):
    return bool(m and m.amount_based_on_formula and (m.formula or "").strip())


def get_abbr_amounts(slip_names):
    """{slip: {component_abbr: amount}} from each slip's own earning/deduction rows, used to build
    the context for evaluating a forced component's formula."""
    by_slip = {}
    for r in frappe.get_all(
        "Salary Detail",
        filters={"parent": ["in", slip_names], "parenttype": "Salary Slip"},
        fields=["parent", "abbr", "amount"],
    ):
        if r.abbr:
            by_slip.setdefault(r.parent, {})[r.abbr] = flt(r.amount)
    return by_slip


def build_context(ss, abbr_amounts):
    """Formula evaluation context for a slip: its component amounts (by abbreviation) plus the
    common slip-level figures formulas reference."""
    context = dict(abbr_amounts)
    context["gross_pay"] = flt(ss.gross_pay)
    context["net_pay"] = flt(ss.net_pay)
    context["total_deduction"] = flt(ss.total_deduction)
    context["total_earnings"] = flt(ss.total_earnings)
    return context


def eval_formula(formula, context):
    """Evaluate an arithmetic salary formula (+ - * / and parentheses) against a {name: number}
    context. Unknown names resolve to 0; anything non-arithmetic (function calls, comparisons)
    yields 0. Self-contained — no safe_eval — so the same logic runs inside the report sandbox."""
    s = formula or ""
    n = len(s)

    toks = []
    i = 0
    while i < n:
        ch = s[i]
        if ch == " " or ch == "\t" or ch == "\n" or ch == "\r":
            i += 1
        elif ch == "+" or ch == "-" or ch == "*" or ch == "/" or ch == "(" or ch == ")":
            toks.append(("op", ch))
            i += 1
        elif ch.isdigit() or ch == ".":
            num = ""
            while i < n and (s[i].isdigit() or s[i] == "."):
                num += s[i]
                i += 1
            try:
                toks.append(("num", float(num)))
            except Exception:
                return 0.0
        elif ch.isalpha() or ch == "_":
            name = ""
            while i < n and (s[i].isalnum() or s[i] == "_"):
                name += s[i]
                i += 1
            toks.append(("id", name))
        else:
            return 0.0

    out = []
    stack = []
    prev = "start"
    for t in toks:
        typ = t[0]
        val = t[1]
        if typ == "num" or typ == "id":
            out.append(t)
            prev = "val"
        elif val == "(":
            if prev == "val":  # identifier( -> function call, unsupported
                return 0.0
            stack.append(t)
            prev = "open"
        elif val == ")":
            while stack and stack[-1][1] != "(":
                out.append(stack.pop())
            if stack and stack[-1][1] == "(":
                stack.pop()
            prev = "val"
        else:
            op = val
            if (val == "+" or val == "-") and (prev == "start" or prev == "op" or prev == "open"):
                op = "u" + val
            unary = (op == "u+" or op == "u-")
            cp = 3 if unary else (2 if (op == "*" or op == "/") else 1)
            while stack and stack[-1][0] == "op" and stack[-1][1] != "(":
                top = stack[-1][1]
                tunary = (top == "u+" or top == "u-")
                tp = 3 if tunary else (2 if (top == "*" or top == "/") else 1)
                if (not unary and tp >= cp) or (unary and tp > cp):
                    out.append(stack.pop())
                else:
                    break
            stack.append(("op", op))
            prev = "op"
    while stack:
        if stack[-1][1] == "(":
            return 0.0
        out.append(stack.pop())

    st = []
    for t in out:
        typ = t[0]
        val = t[1]
        if typ == "num":
            st.append(val)
        elif typ == "id":
            cval = context.get(val, 0)
            try:
                st.append(float(cval))
            except Exception:
                st.append(0.0)
        else:
            if val == "u-" or val == "u+":
                a = st.pop() if st else 0.0
                st.append(-a if val == "u-" else a)
            else:
                b = st.pop() if st else 0.0
                a = st.pop() if st else 0.0
                if val == "+":
                    st.append(a + b)
                elif val == "-":
                    st.append(a - b)
                elif val == "*":
                    st.append(a * b)
                elif val == "/":
                    st.append(a / b if b else 0.0)
    return st[-1] if st else 0.0


def get_salary_slips(filters):
    conditions = ["ss.docstatus != 2"]
    values = {}

    for field in ("company", "employee", "payroll_entry"):
        if filters.get(field):
            conditions.append(f"ss.{field} = %({field})s")
            values[field] = filters.get(field)

    # Placed by the payroll run's posting date where there is one, so slips from a neighbouring
    # period whose start/end dates overlap the selected month are not pulled in.
    #
    # Falling back to the slip's own start date matters more than it looks. From and To Date are
    # required and default to this month, so the join always runs; and a LEFT JOIN with a
    # condition on the right-hand table is an inner join, because NULL >= a date is never true.
    # A slip raised on its own, without a Payroll Entry, was therefore invisible in every view
    # the report offers, with no filter that would bring it back.
    join_payroll_entry = bool(filters.get("from_date") or filters.get("to_date"))
    placed_on = "COALESCE(pe.posting_date, ss.start_date)"
    if filters.get("from_date"):
        conditions.append(f"{placed_on} >= %(from_date)s")
        values["from_date"] = filters.get("from_date")
    if filters.get("to_date"):
        conditions.append(f"{placed_on} <= %(to_date)s")
        values["to_date"] = filters.get("to_date")

    where_clause = " AND ".join(conditions)
    payroll_entry_join = "LEFT JOIN `tabPayroll Entry` pe ON pe.name = ss.payroll_entry" if join_payroll_entry else ""
    posting_date_select = "pe.posting_date" if join_payroll_entry else "NULL AS posting_date"
    order_by = "ss.employee, pe.posting_date, ss.start_date" if join_payroll_entry else "ss.employee, ss.start_date"

    salary_slips = frappe.db.sql(
        f"""
        SELECT
            ss.name, ss.employee, ss.employee_name, ss.payment_days,
            ss.designation, ss.total_working_days,
            ss.branch, ss.company, ss.start_date,
            ss.end_date, ss.salary_structure, ss.payroll_entry,
            ss.mode_of_payment, ss.currency,
            ss.gross_pay, ss.total_earnings, ss.total_deduction, ss.net_pay,
            {posting_date_select}
        FROM `tabSalary Slip` ss
        {payroll_entry_join}
        WHERE {where_clause}
        ORDER BY {order_by}
        """,
        values,
        as_dict=True,
    )

    return salary_slips


def get_included_components():
    """Components left out of the slip totals that are still ticked "Show in Payroll Register"
    (e.g. Taxable Pay). Such a component with a formula is computed and placed by it when a
    slip does not carry it.
    """
    return frappe.get_all(
        "Salary Component",
        filters={"do_not_include_in_total": 1, "custom_show_in_payroll_register": 1},
        pluck="name",
    )


def get_component_meta(names):
    """{component: row(type, abbr, amount_based_on_formula, formula)} for the given components."""
    if not names:
        return {}
    rows = frappe.get_all(
        "Salary Component",
        filters={"name": ["in", list(names)]},
        fields=["name", "type", "salary_component_abbr as abbr", "amount_based_on_formula", "formula"],
    )
    return {r.name: r for r in rows}


def included_clause(included_components, values):
    """Only components ticked "Show in Payroll Register" get a column."""
    return "AND IFNULL(sc.custom_show_in_payroll_register, 1) = 1"


def get_components(slip_names, included_components=None):
    """Return ordered earning, deduction and employer contribution components, and whether
    Taxable Income is present.

    Components are ordered by their first appearance (MIN idx) across the slips, then by name.
    """
    values = {f"slip_{i}": name for i, name in enumerate(slip_names)}
    placeholders = ", ".join([f"%(slip_{i})s" for i in range(len(slip_names))])
    rows = frappe.db.sql(
        f"""
        SELECT
            sd.parentfield,
            sd.salary_component,
            MIN(sd.idx) AS min_idx
        FROM `tabSalary Detail` sd
        LEFT JOIN `tabSalary Component` sc
            ON sc.name = sd.salary_component
        WHERE sd.parent IN ({placeholders})
          AND sd.parenttype = 'Salary Slip'
          AND sd.parentfield IN ('earnings', 'deductions', 'employer_contributions')
          {included_clause(included_components, values)}
        GROUP BY sd.parentfield, sd.salary_component
        ORDER BY min_idx, sd.salary_component
        """,
        values,
        as_dict=True,
    )

    earning_components = []
    deduction_components = []
    employer_components = []
    has_taxable_income = False

    for r in rows:
        if r.parentfield == "earnings":
            if r.salary_component == TAXABLE_INCOME:
                has_taxable_income = True
            else:
                earning_components.append(r.salary_component)
        elif r.parentfield == "deductions":
            deduction_components.append(r.salary_component)
        elif r.parentfield == "employer_contributions":
            employer_components.append(r.salary_component)

    return earning_components, deduction_components, employer_components, has_taxable_income


def get_component_amounts(slip_names, included_components=None):
    """Map each slip to {(parentfield, salary_component): amount}."""
    values = {f"slip_{i}": name for i, name in enumerate(slip_names)}
    placeholders = ", ".join([f"%(slip_{i})s" for i in range(len(slip_names))])
    detail_rows = frappe.db.sql(
        f"""
        SELECT
            sd.parent,
            sd.parentfield,
            sd.salary_component,
            sd.amount
        FROM `tabSalary Detail` sd
        LEFT JOIN `tabSalary Component` sc
            ON sc.name = sd.salary_component
        WHERE sd.parent IN ({placeholders})
          AND sd.parenttype = 'Salary Slip'
          {included_clause(included_components, values)}
        """,
        values,
        as_dict=True,
    )

    component_map = {}
    for r in detail_rows:
        component_map.setdefault(r.parent, {})[(r.parentfield, r.salary_component)] = flt(r.amount)
    return component_map


def scrub_fieldname(component, prefix):
    # Custom (not frappe.scrub) to keep the e_/d_ prefix and guarantee an ASCII-safe fieldname.
    fn = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in component.lower())
    return prefix + fn


def base_columns():
    return [
        # {"label": "Salary Slip", "fieldname": "salary_slip", "fieldtype": "Link", "options": "Salary Slip", "width": 150},
        # Data, not Link: a link to Employee displays the employee's name instead of the ID.
        {"label": "Employee ID", "fieldname": "employee", "fieldtype": "Data", "width": 100},
        {"label": "Employee Name", "fieldname": "employee_name", "fieldtype": "Data", "width": 140},
        {"label": "Payment Days", "fieldname": "payment_days", "fieldtype": "Float", "precision": "1", "width": 70},
    ]


def summary_columns():
    return [
        {"label": "Gross Pay", "fieldname": "gross_pay", "fieldtype": "Currency", "width": AMOUNT_WIDTH},
        {"label": "Deduction", "fieldname": "total_deduction", "fieldtype": "Currency", "width": AMOUNT_WIDTH},
        {"label": "Net Pay", "fieldname": "net_pay", "fieldtype": "Currency", "width": AMOUNT_WIDTH},
    ]


def _referenced_deductions(formula, deduction_components, meta):
    """Deduction components whose abbreviation appears in `formula` (e.g. NSSF, SHA, EHT for
    `gross_pay - NSSF - SHA - EHT`), preserving the deduction column order."""
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", formula or ""))
    return [
        comp for comp in deduction_components
        if meta.get(comp) and meta[comp].abbr and meta[comp].abbr in tokens
    ]


def _consuming_tax_field(forced_formula, deduction_components, fields, meta):
    """Field of the on-report deduction that is the *tax computed from* the taxable base — the
    column the taxable-income figure should sit immediately before.

    A taxable-base earning subtracts the statutory pre-tax deductions (Taxable Salary =
    `gross_pay - NSSF - SHA - EHT`). The tax that consumes it — PAYE (`gross_pay - NSSF - SHA -
    AHL`) — is the only deduction whose own formula references those same statutory deductions;
    plain gross-based levies (NSSF, SHIF, Housing Levy = `gross_pay - AP`) reference none of them.
    So we anchor on the first on-report deduction sharing a statutory reference with the earning.
    Returns None when no such tax is on the report (caller falls back to referenced-deduction order).
    """
    dedn_abbrs = {meta[c].abbr for c in deduction_components if meta.get(c) and meta[c].abbr}
    forced_tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", forced_formula or ""))
    base_dedns = forced_tokens & dedn_abbrs  # statutory deductions the taxable base subtracts
    if not base_dedns:
        return None
    for comp in deduction_components:
        m = meta.get(comp)
        if not m or not m.formula:
            continue
        tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m.formula))
        if (tokens & base_dedns) - {m.abbr}:
            return fields[comp]
    return None


def build_columns(earning_components, deduction_components, has_taxable_income,
                  forced_earning, forced_deduction, fields, ti_field, meta, employer_components=()):
    columns = base_columns()

    for comp in earning_components:
        columns.append({"label": comp, "fieldname": fields[comp], "fieldtype": "Currency", "width": AMOUNT_WIDTH})

    columns.append({"label": "Gross Pay", "fieldname": "gross_pay", "fieldtype": "Currency", "width": AMOUNT_WIDTH})

    if has_taxable_income:
        columns.append({"label": "Taxable Income", "fieldname": ti_field, "fieldtype": "Currency", "width": AMOUNT_WIDTH})

    for comp in deduction_components:
        columns.append({"label": comp, "fieldname": fields[comp], "fieldtype": "Currency", "width": AMOUNT_WIDTH})

    # Forced/derived components (e.g. Taxable Salary) are positioned by their formula so they sit
    # with the figures they relate to:
    #   1. A taxable-base earning goes immediately BEFORE the tax computed from it (PAYE), i.e.
    #      right after the statutory pre-tax deductions — the natural Gross → statutory → Taxable
    #      → PAYE reading order.
    #   2. Otherwise it goes right AFTER the last deduction its formula references.
    #   3. Failing both, it falls to the end of the deduction block.
    for comp in forced_earning + forced_deduction:
        col = {"label": comp, "fieldname": fields[comp], "fieldtype": "Currency", "width": AMOUNT_WIDTH}
        insert_idx = len(columns)

        consuming_field = None
        if comp in forced_earning:
            consuming_field = _consuming_tax_field(
                meta[comp].formula, deduction_components, fields, meta
            )

        if consuming_field:
            for i, c in enumerate(columns):
                if c.get("fieldname") == consuming_field:
                    insert_idx = i  # right BEFORE the tax that consumes the taxable base
                    break
        else:
            referenced = _referenced_deductions(meta[comp].formula, deduction_components, meta)
            if referenced:
                last_ref_field = fields[referenced[-1]]
                for i, c in enumerate(columns):
                    if c.get("fieldname") == last_ref_field:
                        insert_idx = i + 1
                        break

        columns.insert(insert_idx, col)

    columns.extend([
        {"label": "Deduction", "fieldname": "total_deduction", "fieldtype": "Currency", "width": AMOUNT_WIDTH},
        {"label": "Net Pay", "fieldname": "net_pay", "fieldtype": "Currency", "width": AMOUNT_WIDTH},
    ])

    # What the company pays on top of gross pay.
    for comp in employer_components:
        columns.append({"label": comp, "fieldname": fields[comp], "fieldtype": "Currency", "width": AMOUNT_WIDTH})
    return columns
