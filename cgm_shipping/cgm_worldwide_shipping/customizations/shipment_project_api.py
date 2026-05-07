import frappe
from frappe import _


def _default_company():
	company = frappe.defaults.get_user_default("Company")
	if company:
		return company
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if company:
		return company
	names = frappe.get_all("Company", limit=1, pluck="name")
	return names[0] if names else None


def _apply_shipment_meta(project, shipment_type=None, mode=None):
	if shipment_type:
		project.custom_shipment_type = shipment_type
	if mode:
		project.custom_mode_of_transport = mode
	# Sea import workflow initial state (must match Project custom_shipment_status options)
	if frappe.get_meta("Project").has_field("custom_shipment_status"):
		project.custom_shipment_status = "Documents Received"


@frappe.whitelist()
def create_project_from_customer(customer, project_name=None):
	"""Create a shipment Project from Customer. Uses Customer's shipment type / mode if set."""
	frappe.has_permission("Project", ptype="create", throw=True)
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found").format(customer))

	cust = frappe.get_doc("Customer", customer)
	company = _default_company()
	if not company:
		frappe.throw(_("Set a default Company first."))

	proj = frappe.new_doc("Project")
	proj.customer = customer
	proj.company = company
	proj.project_name = project_name or _("Shipment - {0}").format(cust.customer_name or customer)
	_apply_shipment_meta(
		proj,
		shipment_type=cust.get("custom_shipment_type"),
		mode=cust.get("custom_mode_of_transport"),
	)
	if cust.get("lead_name") and frappe.get_meta("Project").has_field("custom_source_lead"):
		proj.custom_source_lead = cust.lead_name

	proj.insert()
	return proj.name


@frappe.whitelist()
def create_project_from_lead(lead, project_name=None):
	"""Lead must be at Lead Ready to Convert; Customer must exist (from conversion)."""
	frappe.has_permission("Project", ptype="create", throw=True)
	lead_doc = frappe.get_doc("Lead", lead)

	if lead_doc.get("custom_cgm_preshipment_status") != "Lead Ready to Convert":
		frappe.throw(_("Lead must be in **Lead Ready to Convert** before creating a Project."))

	customer = frappe.db.get_value("Customer", {"lead_name": lead}, "name")
	if not customer:
		frappe.throw(
			_(
				"No Customer linked to this Lead. Use **Create Customer** from the Lead first, then try again."
			)
		)

	company = _default_company()
	if not company:
		frappe.throw(_("Set a default Company first."))

	proj = frappe.new_doc("Project")
	proj.customer = customer
	proj.company = company
	proj.project_name = project_name or _("Shipment - {0}").format(lead_doc.company_name or lead_doc.lead_name or lead)
	_apply_shipment_meta(
		proj,
		shipment_type=lead_doc.get("custom_shipment_type"),
		mode=lead_doc.get("custom_mode_of_transport"),
	)
	if frappe.get_meta("Project").has_field("custom_source_lead"):
		proj.custom_source_lead = lead

	proj.insert()
	return proj.name


@frappe.whitelist()
def create_project_from_opportunity(opportunity, project_name=None):
	"""Opportunity must be Opp Ready for Project; party must be a Customer."""
	frappe.has_permission("Project", ptype="create", throw=True)
	opp = frappe.get_doc("Opportunity", opportunity)

	if opp.get("custom_cgm_preshipment_status") != "Opp Ready for Project":
		frappe.throw(_("Opportunity must be **Opp Ready for Project** before creating a shipment Project."))

	if opp.opportunity_from != "Customer":
		frappe.throw(_("Opportunity party must be a **Customer** to create a shipment Project."))

	customer = opp.party_name
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found").format(customer))

	company = _default_company() or opp.company
	if not company:
		frappe.throw(_("Set a default Company or set Opportunity company."))

	proj = frappe.new_doc("Project")
	proj.customer = customer
	proj.company = company
	proj.project_name = project_name or _("Shipment - {0}").format(opp.customer_name or opportunity)
	_apply_shipment_meta(
		proj,
		shipment_type=opp.get("custom_shipment_type"),
		mode=opp.get("custom_mode_of_transport"),
	)
	if frappe.get_meta("Project").has_field("custom_source_opportunity"):
		proj.custom_source_opportunity = opportunity

	proj.insert()
	return proj.name
