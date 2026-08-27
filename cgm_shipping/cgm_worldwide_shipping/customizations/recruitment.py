"""Recruitment support for the public CGM job application.

The County / Notice Period fields on Job Applicant and the Territory Type field on
Territory are *not* defined here: they live in the Customize Form exports at
`custom/job_applicant.json` and `custom/territory.json`, which `sync_customizations`
applies on every migrate. This module owns the data and behaviour around them - the
county seed, the link queries, and the validation - and its installer is idempotent
and runs from `install.after_migrate`, after those exports have been applied.
"""
from __future__ import annotations

import frappe
from frappe import _

# Territory Type values, as defined by the Customize Form export for Territory.
COUNTY = "County"
COUNTRY = "Country"

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


def ensure_recruitment_schema() -> None:
	"""Entry point called from install.after_migrate.

	Runs after `sync_customizations` has applied the Customize Form exports, so the
	Territory Type field it writes to is already in place.
	"""
	seed_kenyan_counties()
	point_job_openings_at_cgm_form()


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
	if kenya.get("custom_territory_type") != COUNTRY:
		kenya.custom_territory_type = COUNTRY
		changed = True
	if changed:
		kenya.save(ignore_permissions=True)

	for county in KENYAN_COUNTIES:
		if frappe.db.exists("Territory", county):
			if frappe.db.get_value("Territory", county, "custom_territory_type") != COUNTY:
				frappe.db.set_value("Territory", county, "custom_territory_type", COUNTY)
			continue

		doc = frappe.new_doc("Territory")
		doc.territory_name = county
		doc.parent_territory = KENYA
		doc.is_group = 0
		doc.custom_territory_type = COUNTY
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
		{"name": country, "custom_territory_type": COUNTRY},
		["name", "lft", "rgt"],
		as_dict=True,
	)


def get_open_job_openings() -> list:
	"""Vacancies an applicant may actually apply to, newest first."""
	return frappe.get_all(
		"Job Opening",
		filters={"status": "Open", "publish": 1},
		fields=["name", "job_title"],
		order_by="posted_on desc, creation desc",
	)


def validate_job_applicant_opening(doc, method=None) -> None:
	"""Public applications must name a vacancy that is open and published.

	The careers form offers nothing else and marks the field required, but the
	endpoint accepts any payload. HR stays free to log desk applications with no
	opening, or against an unpublished one.
	"""
	if not frappe.flags.in_web_form:
		return

	if not doc.get("job_title"):
		# Without the link, `designation` never fetches through and the application
		# lands unattached. Only insist while there is something to choose.
		if get_open_job_openings():
			frappe.throw(_("Select the job opening you are applying for."))
		return

	opening = frappe.db.get_value(
		"Job Opening", doc.job_title, ["status", "publish"], as_dict=True
	)
	if not opening or opening.status != "Open" or not opening.publish:
		frappe.throw(_("This vacancy is no longer open for applications."))


def get_county_options() -> list[dict]:
	"""Counties for the careers form, each tagged with the country it sits under.

	Lets the browser narrow the list to the chosen Country of Residence without a
	round trip.
	"""
	rows = frappe.get_all(
		"Territory",
		filters={"custom_territory_type": COUNTY},
		fields=["name", "lft", "rgt"],
		order_by="name asc",
	)
	countries = frappe.get_all(
		"Territory",
		filters={"custom_territory_type": COUNTRY},
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
		"custom_territory_type": COUNTY,
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
	if not territory or territory.custom_territory_type != COUNTY:
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
