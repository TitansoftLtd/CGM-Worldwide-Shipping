"""Per-container demurrage/KPA port charge calculation and accrual journal entries."""
from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt, fmt_money, getdate, nowdate, today

from cgm_shipping.cgm_worldwide_shipping.customizations.shipping_line_rates import (
	calculate_tiered_charge,
	daily_rate_for_day,
	get_demurrage_tiers,
	tier_currency_for_day,
)

CHARGE_TYPE_DEMURRAGE = "Demurrage/Detention"
CHARGE_TYPE_KPA_PORT = "KPA Port"

COMPUTED_CHARGE_FIELDS = (
	"demurrage_daily_rate",
	"demurrage_amount",
	"kpa_port_daily_rate",
	"kpa_amount",
)


def get_default_demurrage_currency() -> str:
	"""Fallback when a demurrage tier row has no currency — use company default."""
	return company_default_currency()


@frappe.request_cache
def company_default_currency() -> str:
	company = frappe.defaults.get_global_default("company")
	if company:
		return frappe.db.get_value("Company", company, "default_currency") or "USD"
	return "USD"


def sum_amounts_by_currency(
	rows: list[dict[str, Any]],
	amount_field: str,
	currency_field: str,
	*,
	default_currency: str | None = None,
) -> dict[str, float]:
	fallback = default_currency or company_default_currency()
	totals: dict[str, float] = {}
	for row in rows:
		amount = flt(row.get(amount_field))
		if not amount:
			continue
		currency = (row.get(currency_field) or fallback).strip() or fallback
		totals[currency] = totals.get(currency, 0.0) + amount
	return totals


def format_currency_totals(totals: dict[str, float]) -> str:
	parts = [
		fmt_money(amount, currency=currency)
		for currency, amount in sorted(totals.items())
		if flt(amount)
	]
	return " · ".join(parts)


def merge_currency_totals(*parts: dict[str, float]) -> dict[str, float]:
	merged: dict[str, float] = {}
	for totals in parts:
		for currency, amount in totals.items():
			merged[currency] = merged.get(currency, 0.0) + flt(amount)
	return merged


def project_posted_container_charge_totals(project: str) -> dict[str, float]:
	rows = frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=[
			"demurrage_amount_posted_to_je",
			"demurrage_rate_currency",
			"kpa_amount_posted_to_je",
			"kpa_rate_currency",
		],
	)
	return merge_currency_totals(
		sum_amounts_by_currency(
			rows, "demurrage_amount_posted_to_je", "demurrage_rate_currency"
		),
		sum_amounts_by_currency(rows, "kpa_amount_posted_to_je", "kpa_rate_currency"),
	)


def project_je_billed_display(project: str) -> str:
	"""Labelled JE billed totals using each charge's currency (e.g. USD), not company symbol."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.finance_cost_ledger import (
		_other_je_expense_totals_for_project,
	)

	totals = merge_currency_totals(
		project_posted_container_charge_totals(project),
		_other_je_expense_totals_for_project(project),
	)
	return format_currency_totals(totals)


def get_kpa_port_rate_settings() -> tuple[float, str]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		get_cgm_shipping_settings,
	)

	settings = get_cgm_shipping_settings()
	if not settings:
		return 0.0, "KES"
	rate = flt(settings.get("kpa_port_daily_rate"))
	currency = (settings.get("kpa_port_rate_currency") or "KES").strip()
	return rate, currency


def get_accrual_accounts() -> dict[str, str | None]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		get_cgm_shipping_settings,
	)

	settings = get_cgm_shipping_settings()
	if not settings:
		return {}
	return {
		"demurrage_expense": settings.get("demurrage_accrual_expense_account"),
		"demurrage_payable": settings.get("demurrage_accrual_payable_account"),
		"kpa_expense": settings.get("kpa_port_accrual_expense_account"),
		"kpa_payable": settings.get("kpa_port_accrual_payable_account"),
	}


def _resolve_demurrage_daily_rate(
	shipping_line: str | None, cargo_size: str | None, demurrage_days: int
) -> float:
	if not shipping_line or demurrage_days <= 0:
		return 0.0
	tiers = get_demurrage_tiers(shipping_line, cargo_size)
	if tiers:
		return daily_rate_for_day(demurrage_days, tiers)
	return 0.0


def _resolve_demurrage_currency(
	data: dict[str, Any],
	shipping_line: str | None,
	cargo_size: str | None,
	demurrage_days: int,
) -> str:
	if data.get("demurrage_rate_currency"):
		return data["demurrage_rate_currency"]
	tiers = get_demurrage_tiers(shipping_line, cargo_size) if shipping_line else []
	currency = tier_currency_for_day(
		demurrage_days, tiers, get_default_demurrage_currency()
	)
	return currency or get_default_demurrage_currency()


def _calculate_demurrage_amount(
	data: dict[str, Any], demurrage_days: int, manual_daily_rate: float
) -> float:
	if demurrage_days <= 0:
		return 0.0

	shipping_line = data.get("shipping_line")
	cargo_size = data.get("cargo_size")

	if manual_daily_rate > 0:
		base = manual_daily_rate * demurrage_days
	else:
		tiers = get_demurrage_tiers(shipping_line, cargo_size)
		base = calculate_tiered_charge(demurrage_days, tiers) if tiers else 0.0

	return flt(base) + flt(data.get("demurrage_amount_adjustment"))


def _calculate_kpa_port_amount(
	data: dict[str, Any], kpa_days: int, manual_daily_rate: float
) -> float:
	if kpa_days <= 0:
		return 0.0
	settings_rate, _currency = get_kpa_port_rate_settings()
	daily_rate = manual_daily_rate if manual_daily_rate > 0 else settings_rate
	base = flt(daily_rate) * kpa_days
	return flt(base) + flt(data.get("kpa_amount_adjustment"))


def compute_container_charge_amounts(
	data: dict[str, Any], metrics: dict[str, Any]
) -> dict[str, Any]:
	"""Return charge rates and accrued amounts for a container tracker row."""
	demurrage_days = int(metrics.get("demurrage_days") or 0)
	kpa_days = int(metrics.get("kpa_days") or 0)
	manual_dem_rate = flt(data.get("demurrage_daily_rate"))
	manual_kpa_rate = flt(data.get("kpa_port_daily_rate"))

	dem_currency = _resolve_demurrage_currency(
		data, data.get("shipping_line"), data.get("cargo_size"), demurrage_days
	)
	_kpa_rate, kpa_currency = get_kpa_port_rate_settings()

	display_dem_rate = manual_dem_rate
	if demurrage_days > 0 and display_dem_rate <= 0:
		display_dem_rate = _resolve_demurrage_daily_rate(
			data.get("shipping_line"), data.get("cargo_size"), demurrage_days
		)

	display_kpa_rate = manual_kpa_rate
	if kpa_days > 0 and display_kpa_rate <= 0:
		display_kpa_rate = _kpa_rate

	return {
		"demurrage_daily_rate": display_dem_rate,
		"demurrage_rate_currency": data.get("demurrage_rate_currency") or dem_currency,
		"demurrage_amount": _calculate_demurrage_amount(data, demurrage_days, manual_dem_rate),
		"kpa_port_daily_rate": display_kpa_rate,
		"kpa_rate_currency": data.get("kpa_rate_currency") or kpa_currency,
		"kpa_amount": _calculate_kpa_port_amount(data, kpa_days, manual_kpa_rate),
	}


def apply_charge_amounts_to_doc(doc, metrics: dict[str, Any] | None = None) -> None:
	if metrics is None:
		from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
			compute_container_metrics,
		)

		metrics = compute_container_metrics(doc.as_dict())

	amounts = compute_container_charge_amounts(doc.as_dict(), metrics)
	for field, value in amounts.items():
		if doc.meta.has_field(field):
			doc.set(field, value)


def refresh_project_container_charge_amounts(project: str) -> None:
	"""Recompute and persist charge metrics on every tracker for a project."""
	if not project:
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
		compute_container_metrics,
	)

	meta = frappe.get_meta("Container Tracker")
	persist_fields = [
		"free_days",
		"kpa_free_days",
		"expected_empty_return",
		"port_days_used",
		"demurrage_days",
		"kpa_days",
		"days_outstanding",
		"status",
		"demurrage_daily_rate",
		"demurrage_rate_currency",
		"demurrage_amount",
		"kpa_port_daily_rate",
		"kpa_rate_currency",
		"kpa_amount",
	]
	persist_fields = [field for field in persist_fields if meta.has_field(field)]
	if not persist_fields:
		return

	for name in frappe.get_all(
		"Container Tracker", filters={"project": project}, pluck="name"
	):
		data = frappe.get_doc("Container Tracker", name).as_dict()
		metrics = compute_container_metrics(data)
		updates = {field: metrics.get(field) for field in persist_fields}
		frappe.db.set_value("Container Tracker", name, updates, update_modified=False)

	refresh_project_charge_totals(project)


def refresh_project_charge_totals(project: str) -> None:
	if not project or not frappe.db.exists("Project", project):
		return
	meta = frappe.get_meta("Project")
	if not meta.has_field("custom_demurrage_accrued_total"):
		return

	rows = frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=[
			"demurrage_amount",
			"demurrage_rate_currency",
			"kpa_amount",
			"kpa_rate_currency",
			"demurrage_amount_posted_to_je",
			"kpa_amount_posted_to_je",
		],
	)
	dem_accrued = sum_amounts_by_currency(
		rows, "demurrage_amount", "demurrage_rate_currency"
	)
	kpa_accrued = sum_amounts_by_currency(rows, "kpa_amount", "kpa_rate_currency")
	dem_posted = sum_amounts_by_currency(
		rows, "demurrage_amount_posted_to_je", "demurrage_rate_currency"
	)
	kpa_posted = sum_amounts_by_currency(
		rows, "kpa_amount_posted_to_je", "kpa_rate_currency"
	)
	dem_accrued_label = format_currency_totals(dem_accrued)
	kpa_accrued_label = format_currency_totals(kpa_accrued)
	dem_posted_label = format_currency_totals(dem_posted)
	kpa_posted_label = format_currency_totals(kpa_posted)
	dem_accrued_numeric = sum(dem_accrued.values())
	kpa_accrued_numeric = sum(kpa_accrued.values())
	dem_posted_numeric = sum(dem_posted.values())
	kpa_posted_numeric = sum(kpa_posted.values())
	updates = {}
	if meta.has_field("custom_demurrage_accrued_total"):
		updates["custom_demurrage_accrued_total"] = dem_accrued_numeric
	if meta.has_field("custom_kpa_port_accrued_total"):
		updates["custom_kpa_port_accrued_total"] = kpa_accrued_numeric
	if meta.has_field("custom_demurrage_accrued_posted_total"):
		updates["custom_demurrage_accrued_posted_total"] = dem_posted_numeric
	if meta.has_field("custom_kpa_port_accrued_posted_total"):
		updates["custom_kpa_port_accrued_posted_total"] = kpa_posted_numeric
	if meta.has_field("custom_demurrage_accrued_total_display"):
		updates["custom_demurrage_accrued_total_display"] = dem_accrued_label
	if meta.has_field("custom_kpa_port_accrued_total_display"):
		updates["custom_kpa_port_accrued_total_display"] = kpa_accrued_label
	if meta.has_field("custom_demurrage_accrued_posted_total_display"):
		updates["custom_demurrage_accrued_posted_total_display"] = dem_posted_label
	if meta.has_field("custom_kpa_port_accrued_posted_total_display"):
		updates["custom_kpa_port_accrued_posted_total_display"] = kpa_posted_label
	if updates:
		frappe.db.set_value("Project", project, updates, update_modified=False)


@frappe.whitelist()
def refresh_project_costing_display(project: str) -> dict[str, str]:
	"""Refresh currency-labelled costing summaries on a Project."""
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	refresh_project_container_charge_amounts(project)
	from cgm_shipping.cgm_worldwide_shipping.customizations.finance_cost_ledger import (
		rebuild_project_finance_billed_total,
	)

	rebuild_project_finance_billed_total(project)
	doc = frappe.get_doc("Project", project)
	out: dict[str, str] = {}
	for fieldname in (
		"custom_demurrage_accrued_total_display",
		"custom_kpa_port_accrued_total_display",
		"custom_demurrage_accrued_posted_total_display",
		"custom_kpa_port_accrued_posted_total_display",
		"custom_finance_cost_total_display",
	):
		if doc.meta.has_field(fieldname):
			out[fieldname] = doc.get(fieldname) or ""
	return out


def _container_charge_deltas(project: str) -> list[dict[str, Any]]:
	rows = frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=[
			"name",
			"container_number",
			"project",
			"demurrage_days",
			"kpa_days",
			"demurrage_daily_rate",
			"kpa_port_daily_rate",
			"demurrage_amount",
			"kpa_amount",
			"demurrage_amount_posted_to_je",
			"kpa_amount_posted_to_je",
			"demurrage_rate_currency",
			"kpa_rate_currency",
		],
	)
	deltas: list[dict[str, Any]] = []
	for row in rows:
		dem_delta = flt(row.demurrage_amount) - flt(row.demurrage_amount_posted_to_je)
		if dem_delta > 0:
			deltas.append(
				{
					"container_tracker": row.name,
					"container_number": row.container_number,
					"project": project,
					"charge_type": CHARGE_TYPE_DEMURRAGE,
					"chargeable_days": row.demurrage_days or 0,
					"daily_rate": row.demurrage_daily_rate or 0,
					"amount": dem_delta,
					"currency": row.demurrage_rate_currency or company_default_currency(),
					"posted_field": "demurrage_amount_posted_to_je",
					"new_posted_total": flt(row.demurrage_amount),
				}
			)
		kpa_delta = flt(row.kpa_amount) - flt(row.kpa_amount_posted_to_je)
		if kpa_delta > 0:
			deltas.append(
				{
					"container_tracker": row.name,
					"container_number": row.container_number,
					"project": project,
					"charge_type": CHARGE_TYPE_KPA_PORT,
					"chargeable_days": row.kpa_days or 0,
					"daily_rate": row.kpa_port_daily_rate or 0,
					"amount": kpa_delta,
					"currency": row.kpa_rate_currency or company_default_currency(),
					"posted_field": "kpa_amount_posted_to_je",
					"new_posted_total": flt(row.kpa_amount),
				}
			)
	return deltas


def _append_je_line(
	je,
	*,
	account: str,
	amount: float,
	currency: str | None,
	company: str,
	project: str,
	remark: str,
	debit: bool,
) -> None:
	if not account or flt(amount) <= 0:
		return

	account_currency = frappe.db.get_value("Account", account, "account_currency")
	company_currency = frappe.db.get_value("Company", company, "default_currency")
	charge_currency = (currency or account_currency or company_currency or "").strip()
	if not charge_currency:
		charge_currency = company_default_currency()

	row = {"account": account, "project": project, "user_remark": remark}
	amount_in_account = flt(amount)

	if charge_currency != account_currency:
		from erpnext.setup.utils import get_exchange_rate

		exchange_rate = flt(
			get_exchange_rate(charge_currency, account_currency, je.posting_date)
		)
		if not exchange_rate:
			frappe.throw(
				frappe._(
					"Missing exchange rate from {0} to {1} on {2}. Add a Currency Exchange record before posting."
				).format(charge_currency, account_currency, je.posting_date)
			)
		amount_in_account = flt(amount) * exchange_rate
		je.multi_currency = 1
		row["exchange_rate"] = exchange_rate

	if debit:
		row["debit_in_account_currency"] = amount_in_account
	else:
		row["credit_in_account_currency"] = amount_in_account
	je.append("accounts", row)


def post_container_charge_accrual_for_project(project: str, *, submit: bool = True) -> dict[str, Any]:
	"""Create a delta accrual JE for one project; update posted amounts on trackers."""
	frappe.has_permission("Project", ptype="write", doc=project, throw=True)
	if not frappe.db.exists("Project", project):
		frappe.throw(frappe._("Project {0} not found").format(project))

	refresh_project_container_charge_amounts(project)
	deltas = _container_charge_deltas(project)
	if not deltas:
		return {"ok": True, "journal_entry": None, "message": frappe._("No new accrual amount to post.")}

	accounts = get_accrual_accounts()
	needed_missing: set[str] = set()
	for d in deltas:
		if d["charge_type"] == CHARGE_TYPE_DEMURRAGE:
			if not accounts.get("demurrage_expense"):
				needed_missing.add("Demurrage expense")
			if not accounts.get("demurrage_payable"):
				needed_missing.add("Demurrage payable")
		else:
			if not accounts.get("kpa_expense"):
				needed_missing.add("KPA port expense")
			if not accounts.get("kpa_payable"):
				needed_missing.add("KPA port payable")
	if needed_missing:
		frappe.throw(
			frappe._(
				"Set accrual accounts on CGM Shipping Settings before posting: {0}"
			).format(", ".join(sorted(set(needed_missing))))
		)

	company = frappe.db.get_value("Project", project, "company")
	if not company:
		frappe.throw(frappe._("Project {0} has no company.").format(project))

	grouped: dict[tuple[str, str], float] = {}
	for line in deltas:
		currency = (line.get("currency") or company_default_currency()).strip()
		key = (line["charge_type"], currency)
		grouped[key] = grouped.get(key, 0.0) + flt(line["amount"])

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = getdate(today())
	je.user_remark = frappe._("Container charge accrual — {0}").format(project)
	if je.meta.has_field("custom_cgm_source_project"):
		je.custom_cgm_source_project = project
	if je.meta.has_field("custom_cgm_accrual_kind"):
		je.custom_cgm_accrual_kind = "Container Charge Accrual"

	child_field = "custom_cgm_container_charge_lines"
	has_child_table = je.meta.has_field(child_field)

	for line in deltas:
		if has_child_table:
			je.append(
				child_field,
				{
					"container_tracker": line["container_tracker"],
					"container_number": line["container_number"],
					"charge_type": line["charge_type"],
					"chargeable_days": line["chargeable_days"],
					"daily_rate": line["daily_rate"],
					"amount": line["amount"],
					"project": project,
				},
			)

	remark_base = frappe._("Container charge accrual {0}").format(project)
	dem_total = 0.0
	kpa_total = 0.0
	for (charge_type, currency), amount in grouped.items():
		if charge_type == CHARGE_TYPE_DEMURRAGE:
			dem_total += amount
			expense_account = accounts["demurrage_expense"]
			payable_account = accounts["demurrage_payable"]
		else:
			kpa_total += amount
			expense_account = accounts["kpa_expense"]
			payable_account = accounts["kpa_payable"]

		_append_je_line(
			je,
			account=expense_account,
			amount=amount,
			currency=currency,
			company=company,
			project=project,
			remark=f"{remark_base} — {charge_type} ({currency})",
			debit=True,
		)
		_append_je_line(
			je,
			account=payable_account,
			amount=amount,
			currency=currency,
			company=company,
			project=project,
			remark=f"{remark_base} — {charge_type} ({currency})",
			debit=False,
		)

	je.insert(ignore_permissions=True)
	if submit:
		je.submit()

	# Mark posted totals on each tracker (aggregate by tracker+field)
	posted_by_tracker: dict[str, dict[str, float]] = {}
	for line in deltas:
		bucket = posted_by_tracker.setdefault(line["container_tracker"], {})
		bucket[line["posted_field"]] = line["new_posted_total"]

	for tracker_name, fields in posted_by_tracker.items():
		frappe.db.set_value(
			"Container Tracker", tracker_name, fields, update_modified=False
		)

	refresh_project_charge_totals(project)
	frappe.db.commit()

	return {
		"ok": True,
		"journal_entry": je.name,
		"demurrage_total": dem_total,
		"kpa_total": kpa_total,
		"lines": len(deltas),
	}


@frappe.whitelist()
def post_container_charge_accrual(project: str) -> dict[str, Any]:
	return post_container_charge_accrual_for_project(project, submit=True)


@frappe.whitelist()
def post_all_container_charge_accruals() -> dict[str, Any]:
	"""Daily batch — post delta accruals for every project with outstanding amounts."""
	projects = frappe.get_all(
		"Container Tracker",
		filters={"project": ["is", "set"]},
		pluck="project",
		distinct=True,
	)
	posted = []
	skipped = []
	for project in projects:
		try:
			result = post_container_charge_accrual_for_project(project, submit=True)
			if result.get("journal_entry"):
				posted.append({"project": project, "journal_entry": result["journal_entry"]})
			else:
				skipped.append(project)
		except Exception:
			frappe.log_error(title=f"Container accrual failed: {project}")
	return {"posted": posted, "skipped": skipped, "count": len(posted)}


def run_daily_container_charge_refresh() -> None:
	"""Refresh open tracker charge amounts then post delta accruals."""
	from cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_tracker import (
		refresh_open_container_metrics,
	)

	refresh_open_container_metrics()
	post_all_container_charge_accruals()
