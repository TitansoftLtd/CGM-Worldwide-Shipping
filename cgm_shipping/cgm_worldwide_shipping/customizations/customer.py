"""Customer hooks — sync onboarding attachments to linked Projects."""


def on_customer_update(doc, _method=None):
	if doc.is_new():
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		CUSTOMER_ATTACH_TO_DOCUMENT_CODE,
		refresh_projects_for_customer,
	)

	# Re-sync projects when a mapped onboarding attachment changes.
	if not any(
		doc.has_value_changed(fieldname)
		for fieldname in CUSTOMER_ATTACH_TO_DOCUMENT_CODE
		if doc.meta.has_field(fieldname)
	):
		return

	refresh_projects_for_customer(doc.name)
