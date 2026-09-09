"""Server context for the public CGM job application form.

The county list and the vacancy options are rendered into the page rather than
fetched from the browser, so the form needs no guest-callable endpoint of its own
and costs no extra round trip.
"""
from __future__ import annotations

import json

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.recruitment import (
	get_county_options,
	get_open_job_openings,
)

OPENING_FIELDS = (
	"name",
	"job_title",
	"designation",
	"department",
	"location",
	"employment_type",
	"status",
	"publish",
)


def get_context(context):
	context.cgm_county_options = json.dumps(get_county_options())

	opening = _get_job_opening(frappe.form_dict.get("job_title"))
	context.cgm_job_opening = json.dumps(opening)
	_scope_job_opening_field(context, opening)

	return context


def _scope_job_opening_field(context, opening: dict | None) -> None:
	"""Offer only vacancies that are actually open, and insist on one being picked.

	`load_form_data` has already turned the Link into an Autocomplete carrying every
	Job Opening, including closed and unpublished ones, so the options are replaced
	here.

	Arriving from a vacancy locks the field to it; arriving cold leaves it a choice.
	Either way it is required while there is something to pick, so an application
	cannot land unattached - without the link `designation` never fetches through.
	A spell with no open vacancies drops the requirement rather than blocking the
	form outright.
	"""
	options = [{"value": row.name, "label": row.job_title} for row in get_open_job_openings()]

	for field in context.web_form_doc.web_form_fields:
		if field.get("fieldname") != "job_title":
			continue
		field["options"] = options
		field["reqd"] = 1 if options else 0
		field["read_only"] = 1 if opening else 0
		if opening:
			field["default"] = opening.name


def _get_job_opening(name) -> dict | None:
	"""Resolve the vacancy in the query string, if it is one an applicant may apply to."""
	if not name or not isinstance(name, str):
		return None

	opening = frappe.db.get_value("Job Opening", name, OPENING_FIELDS, as_dict=True)
	if not opening or opening.status != "Open" or not opening.publish:
		return None

	return opening
