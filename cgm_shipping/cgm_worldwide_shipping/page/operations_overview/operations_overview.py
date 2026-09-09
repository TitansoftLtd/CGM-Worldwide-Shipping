"""Server side of the Operations Overview management dashboard.

The page answers one question for management: where is money or time leaking
right now. Everything here is aggregate; there is no row-level listing, that
is what the Container Ops Board is for.

Two things about this data are worth knowing before reading the queries:

1. Container Tracker is milestone driven. It carries ~35 date columns marking
   the container's journey, and most of them are legitimately empty for a
   container that has not reached that leg yet. So every average below is
   computed only over the containers that have BOTH ends of the leg filled,
   and the sample size is returned alongside the number. An average over two
   containers is not a trend, and the page says so rather than hiding it.

2. Money is stored in mixed currencies. kpa_amount is KES on some rows and
   USD on others, so the totals are grouped by their stated currency and
   never added together. Summing them would invent a number.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, nowdate

# Thresholds that decide whether a headline number is calm, warning or
# critical. They live in one place so they can be tuned without hunting
# through the queries, and so the UI never invents its own severity.
THRESHOLDS = {
	"demurrage_days": {"warn": 10, "critical": 30},
	"containers_past_free_days": {"warn": 1, "critical": 5},
	"containers_at_risk": {"warn": 1, "critical": 3},
	"return_overdue": {"warn": 1, "critical": 3},
	"overdue_tasks": {"warn": 5, "critical": 20},
	"port_dwell_days": {"warn": 7, "critical": 14},
}

# The stages of the container journey, in order, as (start column, end column,
# label). Each label names both ends of the stage: "Discharge" alone does not
# say whether it means the wait before discharge or the discharge itself.
#
# ETA to ATA is deliberately NOT in this list. It is the gap between the
# promised and the actual arrival date, which is a schedule slip by the
# shipping line, not a stage of work anyone at CGM performs. It used to sit
# here, and because it is usually the largest number it was reported as the
# bottleneck, which pointed management at the one thing they cannot influence
# and hid the slowest stage they can. It is measured separately below.
JOURNEY_LEGS = [
	("ata", "discharging_date", "Arrival to discharge"),
	("discharging_date", "custom_release_date", "Discharge to customs release"),
	("custom_release_date", "gate_out_date_port", "Customs release to port gate-out"),
	("gate_out_date_port", "gate_in_date_warehouse", "Port gate-out to warehouse"),
	("gate_in_date_warehouse", "offloading_date", "Warehouse arrival to offload"),
	("offloading_date", "actual_empty_return", "Offload to empty return"),
]

# Schedule reliability: how far the vessel's actual arrival ran from its ETA.
SCHEDULE_VARIANCE = ("eta", "ata")

AGEING_BUCKETS = [(0, 7, "0-7 days"), (8, 14, "8-14 days"), (15, 30, "15-30 days"), (31, None, "30+ days")]



def _base_currency() -> str | None:
	"""The currency to assume when a charge row does not state one.

	Previously this was the literal 'KES' in seven places, which quietly made
	the dashboard wrong for any company not trading in shillings: a blank
	currency column would have been reported as Kenyan regardless. It is now
	resolved from the site, then the company, and if neither answers, nothing
	is assumed at all and the row keeps its own null.
	"""
	currency = frappe.defaults.get_global_default("currency")
	if not currency:
		companies = frappe.get_all(
			"Company", fields=["default_currency"], order_by="creation asc", limit=1
		)
		currency = companies[0].get("default_currency") if companies else None
	return currency or None



# Which filters each section actually responds to.
#
# Not every section is container scoped. Documentation and Compliance counts
# bills of lading, permits and licences, none of which hang off a container, so
# filtering to one shipping line leaves its numbers completely unchanged.
# Income vs Expense reads the ledger, which has no arrival date, so it moves
# only for an explicit date range.
#
# Left on screen, those sections look like they answered the filter when they
# simply ignored it, which is worse than not showing them: a reader compares a
# filtered number against an unfiltered one without being told.
CONTAINER_FILTERS = {
	"date_from", "date_to", "shipping_line", "customer", "project", "status", "cargo_size",
}
SECTION_FILTERS = {
	"headline": CONTAINER_FILTERS,
	"exposure": CONTAINER_FILTERS | {"currency"},
	"cycle": CONTAINER_FILTERS,
	"mix": CONTAINER_FILTERS,
	"commercial": CONTAINER_FILTERS,
	"compliance": set(),
	# Handled separately: it needs both ends of a range, not either.
	"financials": {"date_from", "date_to"},
}

# Two headline cards are not container scoped either. Open Projects counts
# every open project and Overdue Tasks every late task, whatever container
# filter is on.
CARD_FILTERS = {
	"active_jobs": set(),
	"overdue_tasks": set(),
}


def _active_filters(filters) -> set:
	"""The page-level filter keys the user has actually set.

	Currency is deliberately not one of them. It is a control that lives
	inside the Cost Exposure panel and changes only that panel, so counting it
	here meant picking a currency hid every other section on the page,
	including all seven headline cards. A panel's own control must not blank
	the page around it.
	"""
	return {k for k in CONTAINER_FILTERS if filters.get(k)}


def _applies(name: str, active: set, is_card: bool = False) -> bool:
	"""Whether a section or card responds to any filter currently applied."""
	if not active:
		return True
	responds = (CARD_FILTERS if is_card else SECTION_FILTERS).get(
		name, CONTAINER_FILTERS
	)
	if not is_card and name == "financials":
		# The profit and loss window only moves when a complete range is given;
		# a single open-ended bound leaves it on the fiscal year.
		return bool({"date_from", "date_to"} <= active)
	return bool(responds & active)


def _severity(key: str, value: float) -> str:
	"""Map a raw number onto calm / warn / critical using THRESHOLDS."""
	limits = THRESHOLDS.get(key)
	if not limits:
		return "ok"
	if value >= limits["critical"]:
		return "critical"
	if value >= limits["warn"]:
		return "warn"
	return "ok"


def _parse_filters(filters) -> frappe._dict:
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	return frappe._dict(filters or {})


def _date_clause(filters, column: str = "ata") -> tuple[str, dict]:
	"""Restrict to a period. Returns a SQL fragment and its bind values.

	The period applies to the container's actual arrival, which is the point
	the job becomes CGM's problem.

	A container with no arrival date is excluded. It used to be kept, on the
	grounds that dropping it would understate the backlog, but that made the
	clause "arrived in August OR never arrived", which no list view filter can
	express: every date-filtered card then disagreed with the list its own
	click opened. "Arrived in this window" is also the reading a person
	expects. Containers with no ATA are still fully visible in the default,
	unfiltered view, which is where a backlog should be spotted anyway.
	"""
	values: dict = {}
	clauses = []
	if filters.get("date_from"):
		clauses.append(f"ct.`{column}` >= %(date_from)s")
		values["date_from"] = filters["date_from"]
	if filters.get("date_to"):
		clauses.append(f"ct.`{column}` <= %(date_to)s")
		values["date_to"] = filters["date_to"]
	if filters.get("shipping_line"):
		clauses.append("ct.shipping_line = %(shipping_line)s")
		values["shipping_line"] = filters["shipping_line"]
	if filters.get("customer"):
		clauses.append("p.customer = %(customer)s")
		values["customer"] = filters["customer"]
	if filters.get("project"):
		clauses.append("ct.project = %(project)s")
		values["project"] = filters["project"]
	if filters.get("status"):
		clauses.append("ct.status = %(status)s")
		values["status"] = filters["status"]
	if filters.get("cargo_size"):
		clauses.append("ct.cargo_size = %(cargo_size)s")
		values["cargo_size"] = filters["cargo_size"]
	return (" and " + " and ".join(clauses)) if clauses else "", values


def _headline(where: str, values: dict, filters) -> list[dict]:
	"""The cards across the top. Each carries its own severity."""
	today = nowdate()

	row = frappe.db.sql(
		f"""
		select
			count(*) total,
			sum(case when ct.actual_empty_return is null then 1 else 0 end) active,
			sum(case when ct.gate_out_date_port is null and ct.ata is not null then 1 else 0 end) at_port,
			sum(coalesce(ct.demurrage_days, 0)) demurrage_days,
			sum(case when coalesce(ct.demurrage_days, 0) > 0 then 1 else 0 end) demurrage_containers,
			sum(case
				when ct.free_days_end_date is not null
				 and ct.free_days_end_date < %(today)s
				 and ct.gate_out_date_port is null
				then 1 else 0 end) past_free,
			sum(case
				when ct.free_days_end_date is not null
				 and ct.free_days_end_date between %(today)s and %(soon)s
				 and ct.gate_out_date_port is null
				then 1 else 0 end) at_risk,
			sum(case
				when ct.actual_empty_return is null
				 and ct.expected_empty_return is not null
				 and ct.expected_empty_return < %(today)s
				then 1 else 0 end) return_overdue,
			-- Coverage counters. A risk metric reading zero is only reassuring
			-- if the column it depends on is actually filled in; otherwise the
			-- zero means "not tracked" and must not be shown as "all clear".
			sum(case when ct.free_days_end_date is not null then 1 else 0 end) tracked_free_days,
			sum(case when ct.expected_empty_return is not null then 1 else 0 end) tracked_returns
		from `tabContainer Tracker` ct
		left join `tabProject` p on p.name = ct.project
		where 1=1 {where}
		""",
		{**values, "today": today, "soon": add_days(today, 3)},
		as_dict=True,
	)
	agg = row[0] if row else frappe._dict()

	active_jobs = frappe.db.count("Project", {"status": "Open"})
	overdue_tasks = frappe.db.sql(
		"""select count(*) from `tabTask`
		   where status not in ('Completed', 'Cancelled')
		     and exp_end_date is not null and exp_end_date < %s""",
		(today,),
	)[0][0]
	# The licence and receivable counts that used to be computed here were
	# left behind when those cards moved into the panels. They were three
	# queries per request whose results were assigned and never read.
	# _compliance() and _financials() each run their own.

	total = cint(agg.get("total"))

	routes = _card_routes(filters)
	active = _active_filters(filters)

	def card(key, label, value, hint, severity="ok", fmt="int", tracked=None):
		# tracked is the number of records that can answer this metric at all.
		# When none can, the number is not a finding, it is a blind spot, and
		# it gets its own severity so the card cannot be misread as healthy.
		if tracked is not None and total and not tracked:
			severity = "nodata"
			hint = _("Not tracked on any of the {0} containers").format(total)
		elif tracked is not None and total and tracked < total:
			hint = _("{0}, based on {1} of {2} containers").format(hint, tracked, total)
		return {
			"key": key,
			"label": label,
			"value": value,
			"hint": hint,
			"severity": severity,
			"format": fmt,
			"tracked": tracked,
			"total": total if tracked is not None else None,
			"route": routes.get(key),
			"applies": _applies(key, active, is_card=True),
		}

	# Seven cards, not eleven. A headline strip that wraps onto a second row
	# stops being a headline: everything on it competes and nothing reads as
	# urgent. Metrics that were cut are not lost, they are shown in the panel
	# that already covers them in more depth. Free days expiring folds into
	# the past-free-days hint, licences into Documentation and Compliance,
	# and receivables into Receivables vs Payables.
	free_days_hint = _("Accruing demurrage now")
	if cint(agg.get("at_risk")):
		free_days_hint = _("Accruing now, {0} more expiring within 3 days").format(
			cint(agg.get("at_risk"))
		)

	# The free days pair share a severity: a container about to start
	# accruing is the same problem one day earlier, so the card takes
	# whichever of the two is worse.
	free_days_severity = max(
		_severity("containers_past_free_days", cint(agg.get("past_free"))),
		_severity("containers_at_risk", cint(agg.get("at_risk"))),
		key=lambda s: ["ok", "warn", "critical"].index(s),
	)

	return [
		card("active_jobs", _("Open Projects"), active_jobs, _("Projects still open")),
		card("containers_active", _("Containers in Play"), cint(agg.get("active")),
		     _("Not yet returned empty")),
		card("at_port", _("Awaiting Gate-Out"), cint(agg.get("at_port")),
		     _("Arrived but still in port")),
		card("containers_past_free_days", _("Past Free Days"), cint(agg.get("past_free")),
		     free_days_hint, free_days_severity,
		     tracked=cint(agg.get("tracked_free_days"))),
		card("demurrage_days", _("Demurrage Days"), cint(agg.get("demurrage_days")),
		     # Says "across N containers" because this card is a sum of days
		     # while its drill-down opens containers. Without the count the
		     # two numbers look like they disagree.
		     _("Days accrued across {0} containers").format(cint(agg.get("demurrage_containers"))),
		     _severity("demurrage_days", cint(agg.get("demurrage_days")))),
		card("return_overdue", _("Empty Returns Overdue"), cint(agg.get("return_overdue")),
		     _("Past expected return date"),
		     _severity("return_overdue", cint(agg.get("return_overdue"))),
		     tracked=cint(agg.get("tracked_returns"))),
		card("overdue_tasks", _("Overdue Tasks"), cint(overdue_tasks),
		     _("Past their end date"), _severity("overdue_tasks", cint(overdue_tasks))),
	]



def _container_route_filters(filters) -> dict:
	"""The dashboard's own filters, expressed as Container Tracker list filters.

	Drill-down has to land on exactly the records behind the number, so the
	page filters are translated rather than dropped. Client is the awkward
	one: it lives on Project, not on Container Tracker, so it is resolved to
	the matching project names and passed as an "in" filter. That keeps the
	list count equal to the card instead of merely close to it.
	"""
	out: dict = {}
	# Every filter that narrows the query has to narrow the drill-down too.
	# shipping_line, status, cargo_size and project map straight across;
	# forgetting three of them was what made a card reading 1 open a list of
	# 21. Kept as an explicit loop so adding a filter to _date_clause without
	# adding it here is harder to do by accident.
	for field in ("shipping_line", "status", "cargo_size", "project"):
		if filters.get(field):
			out[field] = filters[field]
	if filters.get("date_from") and filters.get("date_to"):
		out["ata"] = ["between", [filters["date_from"], filters["date_to"]]]
	elif filters.get("date_from"):
		out["ata"] = [">=", filters["date_from"]]
	elif filters.get("date_to"):
		out["ata"] = ["<=", filters["date_to"]]
	if filters.get("customer") and not filters.get("project"):
		# Client lives on Project, not on Container Tracker, so it is resolved
		# to the matching project names. Skipped when an explicit project
		# filter is set, because overwriting it with the client's full project
		# list would widen the drill-down beyond what the card counted.
		projects = frappe.get_all(
			"Project", filters={"customer": filters["customer"]}, pluck="name"
		)
		# An empty list would filter to nothing, which is the correct answer
		# when the client has no projects.
		out["project"] = ["in", projects or [""]]
	return out


def _card_routes(filters) -> dict:
	"""Where each headline card drills through to.

	Defined here, beside the aggregate queries, so a change to what a number
	counts is made in the same file as where clicking it takes you.
	"""
	today = nowdate()
	base = _container_route_filters(filters)

	# frappe.get_all and the list view compile a date "<" filter to
	# IFNULL(col, '0001-01-01') < value, so every row with NO date set matches
	# "earlier than today". The cards ask for `col is not null and col < today`
	# in SQL, so a card reading 0 opened a list of 927 tasks that simply had no
	# due date. A bounded range is NULL-safe, and because frappe expands the
	# upper bound of a between to 23:59:59.999999 on Datetime fields, this is
	# exactly equivalent to "< today" rather than merely close to it.
	#
	# It also has to stay expressible as one key per field, because list view
	# route options are a plain object and cannot carry two conditions on the
	# same column.
	before_today = ["between", ["1900-01-01", add_days(today, -1)]]

	def ct(extra: dict) -> dict:
		return {"doctype": "Container Tracker", "filters": {**base, **extra}}

	return {
		"active_jobs": {"doctype": "Project", "filters": {"status": "Open"}},
		"containers_active": ct({"actual_empty_return": ["is", "not set"]}),
		"at_port": ct({"ata": base.get("ata") or ["is", "set"],
		               "gate_out_date_port": ["is", "not set"]}),
		"containers_past_free_days": ct({
			"free_days_end_date": before_today,
			"gate_out_date_port": ["is", "not set"],
		}),
		"demurrage_days": ct({"demurrage_days": [">", 0]}),
		"return_overdue": ct({
			"expected_empty_return": before_today,
			"actual_empty_return": ["is", "not set"],
		}),
		"overdue_tasks": {
			"doctype": "Task",
			"filters": {
				"status": ["not in", ["Completed", "Cancelled"]],
				"exp_end_date": before_today,
			},
		},
	}


def _exposure(where: str, values: dict, filters=None) -> dict:
	"""Money at risk, grouped by the currency it is actually stored in.

	Demurrage and KPA port charges are held in separate currency columns and
	the KPA one genuinely varies row to row, so these are never added into a
	single figure.

	The currency filter applies here and nowhere else. It answers "show me the
	USD exposure", which is a question about charges; applying it to container
	counts or open jobs would silently drop containers that simply have no
	charge posted yet.
	"""
	filters = filters or {}
	cur_filter = filters.get("currency")
	base_currency = _base_currency()
	values = {**values, "base_currency": base_currency}
	dem_cur = (
		" and coalesce(ct.demurrage_rate_currency, %(base_currency)s) = %(cur_filter)s"
		if cur_filter else ""
	)
	kpa_cur = (
		" and coalesce(ct.kpa_rate_currency, %(base_currency)s) = %(cur_filter)s"
		if cur_filter else ""
	)
	if cur_filter:
		values = {**values, "cur_filter": cur_filter}
	demurrage = frappe.db.sql(
		f"""select coalesce(ct.demurrage_rate_currency, %(base_currency)s) currency,
		           coalesce(sum(ct.demurrage_amount), 0) amount,
		           count(case when ct.demurrage_amount > 0 then 1 end) containers
		    from `tabContainer Tracker` ct
		    left join `tabProject` p on p.name = ct.project
		    where 1=1 {where}{dem_cur}
		    group by 1 having amount > 0""",
		values, as_dict=True,
	)
	kpa = frappe.db.sql(
		f"""select coalesce(ct.kpa_rate_currency, %(base_currency)s) currency,
		           coalesce(sum(ct.kpa_amount), 0) amount,
		           count(case when ct.kpa_amount > 0 then 1 end) containers
		    from `tabContainer Tracker` ct
		    left join `tabProject` p on p.name = ct.project
		    where 1=1 {where}{kpa_cur}
		    group by 1 having amount > 0""",
		values, as_dict=True,
	)
	by_line = frappe.db.sql(
		f"""select coalesce(ct.shipping_line, 'Unassigned') line,
		           count(*) containers,
		           coalesce(sum(ct.demurrage_days), 0) demurrage_days,
		           coalesce(sum(ct.demurrage_amount), 0) demurrage_amount
		    from `tabContainer Tracker` ct
		    left join `tabProject` p on p.name = ct.project
		    where 1=1 {where}
		    group by 1 order by demurrage_days desc, containers desc limit 8""",
		values, as_dict=True,
	)
	by_client = frappe.db.sql(
		f"""select coalesce(p.customer, 'Unassigned') client,
		           count(*) containers,
		           coalesce(sum(ct.demurrage_days), 0) demurrage_days,
		           sum(case when ct.gate_out_date_port is null and ct.ata is not null
		                    then 1 else 0 end) at_port
		    from `tabContainer Tracker` ct
		    left join `tabProject` p on p.name = ct.project
		    where 1=1 {where}
		    group by 1 order by containers desc limit 8""",
		values, as_dict=True,
	)
	return {
		"currency_filter": cur_filter,
		"demurrage": demurrage,
		"kpa": kpa,
		"by_line": by_line,
		"by_client": by_client,
	}


def _cycle_time(where: str, values: dict) -> dict:
	"""Average duration of each leg, with the sample size it rests on."""
	legs = []
	reversed_total = 0
	for start, end, label in JOURNEY_LEGS:
		# A leg whose end date precedes its start date is a data entry error,
		# not a negative duration. Averaging those in would quietly drag the
		# leg below zero and make a real delay look like a head start, so they
		# are excluded from the average and counted separately instead.
		row = frappe.db.sql(
			f"""select avg(case when datediff(ct.`{end}`, ct.`{start}`) >= 0
			                    then datediff(ct.`{end}`, ct.`{start}`) end) avg_days,
			           max(datediff(ct.`{end}`, ct.`{start}`)) max_days,
			           count(case when datediff(ct.`{end}`, ct.`{start}`) >= 0 then 1 end) sample,
			           count(case when datediff(ct.`{end}`, ct.`{start}`) < 0 then 1 end) reversed
			    from `tabContainer Tracker` ct
			    left join `tabProject` p on p.name = ct.project
			    where ct.`{start}` is not null and ct.`{end}` is not null {where}""",
			values, as_dict=True,
		)
		r = row[0] if row else frappe._dict()
		reversed_total += cint(r.get("reversed"))
		if not cint(r.get("sample")):
			legs.append({
				"label": _(label), "avg_days": None, "max_days": None,
				"sample": 0, "reversed": cint(r.get("reversed")),
			})
			continue
		legs.append({
			"label": _(label),
			"avg_days": round(flt(r.get("avg_days")), 1),
			"max_days": cint(r.get("max_days")),
			"sample": cint(r.get("sample")),
			"reversed": cint(r.get("reversed")),
		})

	# Schedule reliability, kept apart from the stages above. A positive
	# average means the vessel arrived that many days after its ETA.
	start, end = SCHEDULE_VARIANCE
	srow = frappe.db.sql(
		f"""select avg(datediff(ct.`{end}`, ct.`{start}`)) avg_days,
		           count(*) sample,
		           count(case when datediff(ct.`{end}`, ct.`{start}`) > 0 then 1 end) late,
		           count(case when datediff(ct.`{end}`, ct.`{start}`) < 0 then 1 end) early
		    from `tabContainer Tracker` ct
		    left join `tabProject` p on p.name = ct.project
		    where ct.`{start}` is not null and ct.`{end}` is not null {where}""",
		values, as_dict=True,
	)
	s = srow[0] if srow else frappe._dict()
	schedule = {
		"avg_days": round(flt(s.get("avg_days")), 1) if cint(s.get("sample")) else None,
		"sample": cint(s.get("sample")),
		"late": cint(s.get("late")),
		"early": cint(s.get("early")),
	}

	# The bottleneck is the slowest stage that rests on more than one
	# container. A single slow container is an incident, not a bottleneck.
	measured = [leg for leg in legs if leg["sample"] > 1 and leg["avg_days"] is not None]
	bottleneck = max(measured, key=lambda leg: leg["avg_days"]) if measured else None

	today = nowdate()
	ageing = []
	for lo, hi, label in AGEING_BUCKETS:
		bound = f"and datediff(%(today)s, ct.ata) <= {hi}" if hi else ""
		count = frappe.db.sql(
			f"""select count(*) from `tabContainer Tracker` ct
			    left join `tabProject` p on p.name = ct.project
			    where ct.ata is not null and ct.gate_out_date_port is null
			      and datediff(%(today)s, ct.ata) >= {lo} {bound} {where}""",
			{**values, "today": today},
		)[0][0]
		ageing.append({"label": _(label), "count": cint(count), "critical": hi is None})

	dwell = frappe.db.sql(
		f"""select avg(datediff(%(today)s, ct.ata)) from `tabContainer Tracker` ct
		    left join `tabProject` p on p.name = ct.project
		    where ct.ata is not null and ct.gate_out_date_port is null {where}""",
		{**values, "today": today},
	)[0][0]

	return {
		"legs": legs,
		"schedule": schedule,
		"reversed_dates": reversed_total,
		"bottleneck": bottleneck,
		"ageing": ageing,
		"avg_port_dwell": round(flt(dwell), 1) if dwell is not None else None,
		"dwell_severity": _severity("port_dwell_days", flt(dwell or 0)),
	}


def _status_mix(where: str, values: dict) -> dict:
	status = frappe.db.sql(
		f"""select coalesce(nullif(ct.status, ''), 'Unset') label, count(*) count
		    from `tabContainer Tracker` ct
		    left join `tabProject` p on p.name = ct.project
		    where 1=1 {where} group by 1 order by count desc limit 10""",
		values, as_dict=True,
	)
	location = frappe.db.sql(
		f"""select coalesce(nullif(ct.current_location, ''), 'Unset') label, count(*) count
		    from `tabContainer Tracker` ct
		    left join `tabProject` p on p.name = ct.project
		    where 1=1 {where} group by 1 order by count desc limit 10""",
		values, as_dict=True,
	)
	return {"status": status, "location": location}


def _compliance() -> dict:
	"""Documentation and licensing. These are not container scoped, so the
	period filter does not apply: an expired licence is a problem today no
	matter which month the shipment landed in."""
	bol = frappe.db.sql(
		"""select docstatus, count(*) count from `tabBill of Lading` group by 1""", as_dict=True
	)
	bol_map = {cint(r["docstatus"]): cint(r["count"]) for r in bol}

	permits = frappe.db.sql(
		"""select coalesce(nullif(status, ''), 'Unset') label, count(*) count
		   from `tabPermit Register` group by 1 order by count desc""", as_dict=True
	)
	permits_open = sum(cint(r["count"]) for r in permits if r["label"] != "Receipt Verified")

	idf = frappe.db.sql(
		"""select docstatus, count(*) count from `tabIDF UCR Record` group by 1""", as_dict=True
	)
	idf_map = {cint(r["docstatus"]): cint(r["count"]) for r in idf}

	licences = frappe.db.sql(
		"""select name, license_type, status, days_to_expiry
		   from `tabLicense Register`
		   where coalesce(disabled, 0) = 0
		     and (status in ('Expiring Soon', 'Renewal Required', 'Expired')
		          or (days_to_expiry is not null and days_to_expiry <= 60))
		   order by coalesce(days_to_expiry, 9999) asc limit 8""", as_dict=True
	)

	return {
		"bol": {
			"draft": bol_map.get(0, 0),
			"submitted": bol_map.get(1, 0),
			"cancelled": bol_map.get(2, 0),
		},
		"permits": permits,
		"permits_open": permits_open,
		"idf": {"draft": idf_map.get(0, 0), "submitted": idf_map.get(1, 0)},
		"licences": licences,
	}


def _commercial(where: str, values: dict) -> dict:
	top_clients = frappe.db.sql(
		f"""select coalesce(p.customer, 'Unassigned') client, count(*) containers,
		           count(distinct ct.project) jobs
		    from `tabContainer Tracker` ct
		    left join `tabProject` p on p.name = ct.project
		    where 1=1 {where}
		    group by 1 order by containers desc limit 8""",
		values, as_dict=True,
	)

	# Receivable ageing, billing and purchase totals used to live here too.
	# _financials() owns all three now and the page reads them from there, so
	# this was six queries per request building a payload nothing rendered.
	# Two sources for one number is also how the two drift apart.
	return {
		"top_clients": top_clients,
		"currency": _base_currency(),
	}



def _financial_period(filters) -> tuple[str, str, str]:
	"""The window the profit and loss figures cover.

	The container filters run on arrival dates, which have nothing to do with
	posting dates, so the ledger is never filtered by them implicitly. If
	management picks an explicit range it is honoured; otherwise the current
	fiscal year is used, because a profit figure with no stated period is
	not interpretable.
	"""
	if filters.get("date_from") and filters.get("date_to"):
		return filters["date_from"], filters["date_to"], _("Selected period")
	try:
		fy = frappe.get_cached_value(
			"Fiscal Year", frappe.defaults.get_user_default("fiscal_year"),
			["year_start_date", "year_end_date"], as_dict=True,
		)
	except Exception:
		fy = None
	if not fy:
		row = frappe.db.sql(
			"""select year_start_date, year_end_date from `tabFiscal Year`
			   where %s between year_start_date and year_end_date limit 1""",
			(nowdate(),), as_dict=True,
		)
		fy = row[0] if row else None
	if not fy:
		return add_days(nowdate(), -365), nowdate(), _("Last 12 months")
	return str(fy["year_start_date"]), str(fy["year_end_date"]), _("Fiscal year to date")


def _financials(filters) -> dict:
	"""Income against expense, and receivables against payables.

	Income and expense come from the ledger rather than from invoice totals:
	invoices miss journal entries, and management asks about the actual
	position, not the billed one. ERPNext holds income as a credit balance
	and expense as a debit balance, so each is signed accordingly here.
	"""
	start, end, period_label = _financial_period(filters)
	today = nowdate()

	rows = frappe.db.sql(
		"""select a.root_type,
		          sum(gl.credit - gl.debit) credit_net,
		          sum(gl.debit - gl.credit) debit_net
		   from `tabGL Entry` gl
		   join `tabAccount` a on a.name = gl.account
		   where gl.is_cancelled = 0 and a.root_type in ('Income', 'Expense')
		     and gl.posting_date between %(start)s and %(end)s
		   group by a.root_type""",
		{"start": start, "end": end}, as_dict=True,
	)
	income = expense = 0.0
	for r in rows:
		if r["root_type"] == "Income":
			income = flt(r["credit_net"])
		else:
			expense = flt(r["debit_net"])
	net = income - expense
	margin = (net / income * 100) if income else None

	# Month by month, so a single large posting cannot pass for a trend.
	trend = frappe.db.sql(
		"""select date_format(gl.posting_date, '%%b %%Y') label,
		          date_format(gl.posting_date, '%%Y-%%m') sort_key,
		          sum(case when a.root_type = 'Income' then gl.credit - gl.debit else 0 end) income,
		          sum(case when a.root_type = 'Expense' then gl.debit - gl.credit else 0 end) expense
		   from `tabGL Entry` gl
		   join `tabAccount` a on a.name = gl.account
		   where gl.is_cancelled = 0 and a.root_type in ('Income', 'Expense')
		     and gl.posting_date between %(start)s and %(end)s
		   group by 1, 2 order by sort_key""",
		{"start": start, "end": end}, as_dict=True,
	)
	for t in trend:
		t["income"] = flt(t["income"])
		t["expense"] = flt(t["expense"])
		t["net"] = t["income"] - t["expense"]

	top_expenses = frappe.db.sql(
		"""select gl.account, sum(gl.debit - gl.credit) amount
		   from `tabGL Entry` gl
		   join `tabAccount` a on a.name = gl.account
		   where gl.is_cancelled = 0 and a.root_type = 'Expense'
		     and gl.posting_date between %(start)s and %(end)s
		   group by 1 having amount > 0 order by amount desc limit 6""",
		{"start": start, "end": end}, as_dict=True,
	)

	def ageing(doctype: str) -> list[dict]:
		out = []
		for lo, hi, label in [(0, 30, "Current"), (31, 60, "31-60 days"),
		                      (61, 90, "61-90 days"), (91, None, "90+ days")]:
			bound = f"and datediff(%(today)s, due_date) <= {hi}" if hi else ""
			row = frappe.db.sql(
				f"""select coalesce(sum(outstanding_amount), 0), count(*)
				    from `tab{doctype}`
				    where docstatus = 1 and outstanding_amount > 0
				      and due_date is not null
				      and datediff(%(today)s, due_date) >= {lo} {bound}""",
				{"today": today},
			)[0]
			out.append({"label": _(label), "amount": flt(row[0]),
			            "count": cint(row[1]), "critical": hi is None})
		return out

	receivable = frappe.db.sql(
		"""select coalesce(sum(outstanding_amount), 0), count(*) from `tabSales Invoice`
		   where docstatus = 1 and outstanding_amount > 0"""
	)[0]
	payable = frappe.db.sql(
		"""select coalesce(sum(outstanding_amount), 0), count(*) from `tabPurchase Invoice`
		   where docstatus = 1 and outstanding_amount > 0"""
	)[0]
	overdue_ar = frappe.db.sql(
		"""select coalesce(sum(outstanding_amount), 0), count(*) from `tabSales Invoice`
		   where docstatus = 1 and outstanding_amount > 0 and due_date < %s""", (today,)
	)[0]
	overdue_ap = frappe.db.sql(
		"""select coalesce(sum(outstanding_amount), 0), count(*) from `tabPurchase Invoice`
		   where docstatus = 1 and outstanding_amount > 0 and due_date < %s""", (today,)
	)[0]

	return {
		"period_label": period_label,
		"period_from": start,
		"period_to": end,
		"income": income,
		"expense": expense,
		"net": net,
		"margin": round(margin, 1) if margin is not None else None,
		"trend": trend,
		"top_expenses": top_expenses,
		"receivable": {"amount": flt(receivable[0]), "count": cint(receivable[1]),
		               "overdue_amount": flt(overdue_ar[0]), "overdue_count": cint(overdue_ar[1]),
		               "ageing": ageing("Sales Invoice")},
		"payable": {"amount": flt(payable[0]), "count": cint(payable[1]),
		            "overdue_amount": flt(overdue_ap[0]), "overdue_count": cint(overdue_ap[1]),
		            "ageing": ageing("Purchase Invoice")},
		# Positive means more is owed to the business than by it.
		"working_position": flt(receivable[0]) - flt(payable[0]),
		"currency": _base_currency(),
	}


@frappe.whitelist()
def get_overview(filters=None):
	"""Everything the dashboard shows, in one round trip.

	One call rather than one per section: the page is read top to bottom and
	partial rendering would let management act on a half-loaded picture.
	"""
	if not frappe.has_permission("Container Tracker", "read"):
		frappe.throw(_("Not permitted to view operations data"), frappe.PermissionError)

	filters = _parse_filters(filters)
	where, values = _date_clause(filters)

	return {
		"headline": _headline(where, values, filters),
		"exposure": _exposure(where, values, filters),
		"cycle": _cycle_time(where, values),
		"mix": _status_mix(where, values),
		"compliance": _compliance(),
		"commercial": _commercial(where, values),
		"financials": _financials(filters),
		"applies": {
			name: _applies(name, _active_filters(filters))
			for name in SECTION_FILTERS
		},
		"active_filters": sorted(_active_filters(filters)),
		"generated_on": frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M"),
		"currency": _base_currency(),
	}


@frappe.whitelist()
def get_filter_options():
	"""Values for the dashboard's own filter controls.

	Statuses and currencies are read from the data rather than hardcoded, so a
	new status added in Container Tracker shows up in the filter without a
	code change, and a currency that nobody uses never appears at all.
	"""
	def column(col: str) -> list[str]:
		rows = frappe.db.sql(
			f"""select distinct `{col}` from `tabContainer Tracker`
			    where `{col}` is not null and `{col}` != '' order by 1"""
		)
		return [r[0] for r in rows]

	currencies = sorted(
		set(column("demurrage_rate_currency")) | set(column("kpa_rate_currency"))
	)
	return {
		"shipping_lines": column("shipping_line"),
		"statuses": column("status"),
		"currencies": currencies,
		"cargo_sizes": column("cargo_size"),
	}


# What each drill-down shows in its dialog. Kept beside the routes so the
# columns a card opens are chosen next to the filters that select the rows.
_CARD_COLUMNS = {
	"Container Tracker": [
		("container_number", "Container", "Data"),
		("bl_number", "B/L", "Data"),
		("project", "Project", "Link"),
		("status", "Status", "Data"),
		("shipping_line", "Line", "Data"),
		("ata", "Arrived", "Date"),
		("demurrage_days", "Dem. days", "Int"),
	],
	"Project": [
		("name", "Project", "Link"),
		("project_name", "Name", "Data"),
		("customer", "Client", "Data"),
		("status", "Status", "Data"),
		("expected_end_date", "Due", "Date"),
	],
	"Task": [
		("name", "Task", "Link"),
		("subject", "Subject", "Data"),
		("project", "Project", "Link"),
		("status", "Status", "Data"),
		("exp_end_date", "Due", "Date"),
	],
}

# A dialog is a preview, not a report. Anything longer than this belongs in
# the list view, and the dialog says so rather than silently truncating.
_CARD_PREVIEW_LIMIT = 100


@frappe.whitelist()
def get_card_records(key: str, filters=None):
	"""The records behind one headline card.

	Selected with exactly the filters the card's route carries, so the dialog
	cannot show a different set from the number that opened it.
	"""
	filters = _parse_filters(filters)
	route = _card_routes(filters).get(key)
	if not route:
		frappe.throw(_("Unknown card {0}").format(frappe.bold(key)))

	doctype = route["doctype"]
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(
			_("Not permitted to view {0}").format(doctype), frappe.PermissionError
		)

	columns = _CARD_COLUMNS.get(doctype, [("name", "Name", "Link")])
	fields = [col[0] for col in columns]
	if "name" not in fields:
		fields = ["name"] + fields

	total = frappe.db.count(doctype, route["filters"])
	rows = frappe.get_all(
		doctype,
		filters=route["filters"],
		fields=fields,
		limit_page_length=_CARD_PREVIEW_LIMIT,
		order_by="modified desc",
	)
	return {
		"doctype": doctype,
		"columns": [{"field": f, "label": _(l), "type": t} for f, l, t in columns],
		"rows": rows,
		"total": total,
		"shown": len(rows),
		"limit": _CARD_PREVIEW_LIMIT,
		"filters": route["filters"],
	}
