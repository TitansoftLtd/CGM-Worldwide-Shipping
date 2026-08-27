"""Recruitment schema for the public CGM job application.

Adds the Territory / Notice Period fields the careers form collects on top of the
stock HRMS Job Applicant, and classifies Territory records so the Territory link
can be filtered by type. Installers are idempotent and run from
`install.after_migrate`.
"""
from __future__ import annotations

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	_remove_cf,
	_upsert_cf,
)

# Territory records are classified with these so a Territory link field can be
# narrowed to just counties or just countries.
TERRITORY_TYPES = ("County", "Country")
TERRITORY_TYPE_OPTIONS = "\n" + "\n".join(TERRITORY_TYPES)

NOTICE_PERIODS = (
	"Immediately Available",
	"1 Month",
	"2 Months",
	"3 Months",
	"More than 3 Months",
)
NOTICE_PERIOD_OPTIONS = "\n" + "\n".join(NOTICE_PERIODS)

KENYA = "Kenya"

# The 47 counties of the Constitution of Kenya 2010, First Schedule.
KENYAN_COUNTIES = (
	"Mombasa",
	"Kwale",
	"Kilifi",
	"Tana River",
	"Lamu",
	"Taita Taveta",
	"Garissa",
	"Wajir",
	"Mandera",
	"Marsabit",
	"Isiolo",
	"Meru",
	"Tharaka Nithi",
	"Embu",
	"Kitui",
	"Machakos",
	"Makueni",
	"Nyandarua",
	"Nyeri",
	"Kirinyaga",
	"Murang'a",
	"Kiambu",
	"Turkana",
	"West Pokot",
	"Samburu",
	"Trans Nzoia",
	"Uasin Gishu",
	"Elgeyo Marakwet",
	"Nandi",
	"Baringo",
	"Laikipia",
	"Nakuru",
	"Narok",
	"Kajiado",
	"Kericho",
	"Bomet",
	"Kakamega",
	"Vihiga",
	"Bungoma",
	"Busia",
	"Siaya",
	"Kisumu",
	"Homa Bay",
	"Migori",
	"Kisii",
	"Nyamira",
	"Nairobi City",
)

WEB_FORM = "cgm-job-application"
WEB_FORM_ROUTE = "careers/apply"


def ensure_recruitment_custom_fields() -> None:
	"""Field-only installer, called from install.before_migrate.

	The careers Web Form lists these fieldnames, so they have to exist before the
	standard Web Form JSON is imported. In developer mode a Web Form saved while a
	referenced field is missing exports itself back over its own source file minus
	that field, which silently truncates the form.
	"""
	if not frappe.db.table_exists("Territory") or not frappe.db.table_exists("Job Applicant"):
		return

	ensure_territory_type_field()
	ensure_job_applicant_fields()


def ensure_recruitment_schema() -> None:
	"""Entry point called from install.after_migrate."""
	ensure_recruitment_custom_fields()
	seed_kenyan_counties()
	point_job_openings_at_cgm_form()


def ensure_territory_type_field() -> None:
	"""Classify Territory masters so the applicant's Territory link can be filtered."""
	_upsert_cf(
		"Territory",
		{
			"fieldname": "custom_territory_type",
			"label": "Territory Type",
			"fieldtype": "Select",
			"options": TERRITORY_TYPE_OPTIONS,
			"insert_after": "is_group",
			"description": (
				"Classifies this territory so Territory link fields can be filtered by type. "
				"Leave blank for grouping nodes that are neither a county nor a country."
			),
		},
	)


def ensure_job_applicant_fields() -> None:
	"""County picker on Job Applicant, scoped by the Country of Residence.

	There is deliberately no Territory Type field here: the type lives on the
	Territory master, and the applicant's country is what narrows the list.
	"""
	# Removed in favour of driving the county list straight off `country`.
	_remove_cf("Job Applicant", "custom_territory_type")

	_upsert_cf(
		"Job Applicant",
		{
			"fieldname": "custom_territory",
			"label": "County",
			"fieldtype": "Link",
			"options": "Territory",
			"insert_after": "country",
			"depends_on": "eval:doc.country",
			"description": "Counties available for the selected Country of Residence.",
		},
	)
	_upsert_cf(
		"Job Applicant",
		{
			"fieldname": "custom_notice_period",
			"label": "Notice Period",
			"fieldtype": "Select",
			"options": NOTICE_PERIOD_OPTIONS,
			"insert_after": "custom_territory",
			"description": "How soon the applicant can start.",
		},
	)


def seed_kenyan_counties() -> None:
	"""Create the 47 counties under the Kenya territory and type every node.

	Territories that already exist keep their place in the tree; only their type is
	filled in, so a manually curated hierarchy is never reshuffled.
	"""
	if not frappe.db.exists("Territory", KENYA):
		# Nothing to hang the counties off. Leave the tree alone rather than
		# inventing a root that the sales setup did not ask for.
		return

	# Kenya has to be a group before it can hold county children, otherwise the
	# next save of Kenya trips NestedSet.validate_ledger.
	kenya = frappe.get_doc("Territory", KENYA)
	changed = False
	if not kenya.is_group:
		kenya.is_group = 1
		changed = True
	if kenya.get("custom_territory_type") != "Country":
		kenya.custom_territory_type = "Country"
		changed = True
	if changed:
		kenya.save(ignore_permissions=True)

	for county in KENYAN_COUNTIES:
		if frappe.db.exists("Territory", county):
			if frappe.db.get_value("Territory", county, "custom_territory_type") != "County":
				frappe.db.set_value("Territory", county, "custom_territory_type", "County")
			continue

		doc = frappe.new_doc("Territory")
		doc.territory_name = county
		doc.parent_territory = KENYA
		doc.is_group = 0
		doc.custom_territory_type = "County"
		doc.insert(ignore_permissions=True)


def point_job_openings_at_cgm_form() -> None:
	"""Route openings that have no explicit form of their own to the CGM one.

	An opening with a route already set was pointed somewhere deliberately, so it
	is left untouched.
	"""
	if not frappe.db.exists("Web Form", WEB_FORM):
		return

	for name in frappe.get_all(
		"Job Opening",
		filters={"job_application_route": ("in", ("", None))},
		pluck="name",
	):
		frappe.db.set_value("Job Opening", name, "job_application_route", WEB_FORM_ROUTE)


def get_country_territory(country: str | None) -> dict | None:
	"""The Country-typed Territory standing in for a Country master, if there is one.

	Territory and Country masters are separate trees that happen to share names, so
	the country the applicant picked is matched to a territory by name.
	"""
	if not country:
		return None

	return frappe.db.get_value(
		"Territory",
		{"name": country, "custom_territory_type": "Country"},
		["name", "lft", "rgt"],
		as_dict=True,
	)


def get_county_options() -> list[dict]:
	"""Counties for the careers form, each tagged with the country it sits under.

	Lets the browser narrow the list to the chosen Country of Residence without a
	round trip.
	"""
	rows = frappe.get_all(
		"Territory",
		filters={"custom_territory_type": "County"},
		fields=["name", "lft", "rgt"],
		order_by="name asc",
	)
	countries = frappe.get_all(
		"Territory",
		filters={"custom_territory_type": "Country"},
		fields=["name", "lft", "rgt"],
	)

	def country_of(row) -> str | None:
		for country in countries:
			if country.lft <= row.lft and row.rgt <= country.rgt:
				return country.name
		return None

	return [{"value": r.name, "label": r.name, "country": country_of(r)} for r in rows]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def county_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link query behind the County field on Job Applicant.

	Offers only counties inside the subtree of the selected Country of Residence.
	"""
	filters = filters or {}
	country = filters.get("country")
	if not country:
		return []

	country_node = get_country_territory(country)
	if not country_node:
		# No territory for that country, so it has no counties to offer.
		return []

	conditions = {
		"custom_territory_type": "County",
		"lft": (">=", country_node.lft),
		"rgt": ("<=", country_node.rgt),
	}
	if txt:
		conditions["name"] = ("like", f"%{txt}%")

	return frappe.get_all(
		"Territory",
		filters=conditions,
		fields=["name"],
		order_by="name asc",
		limit_start=start,
		limit_page_length=page_len,
		as_list=True,
	)


def validate_job_applicant_territory(doc, method=None) -> None:
	"""The county must be a county, and must sit inside the country of residence.

	The careers form only filters the list in the browser, so the pairing has to be
	enforced here for anything posted straight at the endpoint.
	"""
	if not doc.get("custom_territory"):
		return

	if not doc.get("country"):
		frappe.throw(_("Select a Country of Residence before choosing a County."))

	territory = frappe.db.get_value(
		"Territory", doc.custom_territory, ["custom_territory_type", "lft", "rgt"], as_dict=True
	)
	if not territory or territory.custom_territory_type != "County":
		frappe.throw(
			_("{0} is not a County.").format(frappe.bold(doc.custom_territory))
		)

	country_node = get_country_territory(doc.country)
	if not country_node or not (
		country_node.lft <= territory.lft and territory.rgt <= country_node.rgt
	):
		frappe.throw(
			_("County {0} is not in {1}.").format(
				frappe.bold(doc.custom_territory), frappe.bold(doc.country)
			)
		)
