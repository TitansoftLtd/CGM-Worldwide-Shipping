"""
Seed end-to-end test data for CGM Worldwide Shipping (Project + Task model).

Usage:
bench --site <site> execute cgm_shipping.cgm_worldwide_shipping.test_data.seed_e2e_test_data.seed

Re-run safe: skips records that already exist (matched by client ref).
"""
from __future__ import annotations

import frappe
from frappe.utils import add_days, today

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	build_project_name_seed,
	ensure_unique_project_name,
)

TEST_MARKER = "E2E-TEST-2026"


def seed():
	frappe.only_for("System Manager")
	customer = _ensure_customer()
	supplier = _ensure_supplier()
	employee = _ensure_employee()
	project_sea = _ensure_sea_fcl_project(customer, supplier, employee)
	project_air = _ensure_air_import_project(customer, employee)
	_link_sea_records(project_sea, supplier)
	_daily_status_red()
	frappe.db.commit()
	_print_summary(project_sea, project_air, customer)


def _ensure_customer():
	existing = frappe.get_all("Customer", filters={"disabled": 0}, pluck="name", limit=1)
	if existing:
		return existing[0]
	name = "Abyssinia Iron Steel Ltd (Test)"
	if frappe.db.exists("Customer", name):
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {}, "name") or "All Customer Groups",
			"territory": frappe.db.get_value("Territory", {}, "name") or "All Territories",
		}
	)
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_supplier():
	name = "Siginon Freight (Test)"
	if frappe.db.exists("Supplier", name):
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": name,
			"supplier_group": frappe.db.get_value("Supplier Group", {}, "name") or "All Supplier Groups",
			"supplier_type": "Company",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_employee():
	name = "Test Agent Felix"
	if frappe.db.exists("Employee", {"employee_name": name}):
		return frappe.db.get_value("Employee", {"employee_name": name}, "name")
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": "Felix",
			"employee_name": name,
			"company": company,
			"status": "Active",
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": today(),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _doc_type_for_code(code: str) -> str | None:
	return frappe.db.get_value("Document Type", {"code": code}, "name")


def _append_intake_docs(project):
	for code in ("CI", "PKL"):
		dt = _doc_type_for_code(code)
		if not dt:
			continue
		if any(
			frappe.db.get_value("Document Type", r.document_type, "code") == code
			for r in project.get("custom_shipment_documents") or []
			if r.document_type
		):
			continue
		project.append(
			"custom_shipment_documents",
			{"document_type": dt, "status": "Uploaded", "remarks": f"E2E placeholder {code}"},
		)


def _append_demo_permits(project):
	for permit_type, agency in (("KEBS", "KEBS"), ("Port Health", "Port Health")):
		if any(r.permit_type == permit_type for r in project.get("custom_permit_register") or []):
			continue
		project.append(
			"custom_permit_register",
			{
				"permit_type": permit_type,
				"agency": agency,
				"status": "Pending",
				"remarks": "E2E regulatory permit row",
			},
		)


def _ensure_sea_fcl_project(customer, supplier, employee):
	ref = f"{TEST_MARKER}-SEA-FCL"
	existing = frappe.db.get_value("Project", {"custom_client_ref_no": ref}, "name")
	if existing:
		return existing
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	seed = build_project_name_seed(ref, shipment_type="Sea FCL", mode="Sea")
	doc = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": ensure_unique_project_name(seed),
			"customer": customer,
			"company": company,
			"custom_client_ref_no": ref,
			"custom_shipment_type": "Sea FCL",
			"custom_mode_of_transport": "Sea",
			"custom_shipment_status": "Draft",
			"custom_bl_number": "SIGMOMB24051234",
			"notes": "E2E sea FCL — attach CI/PKL files, then Receive Client Documents. Entry 26NBOIM409252569",
		}
	)
	_append_intake_docs(doc)
	_append_demo_permits(doc)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_air_import_project(customer, employee):
	ref = f"{TEST_MARKER}-AIR"
	existing = frappe.db.get_value("Project", {"custom_client_ref_no": ref}, "name")
	if existing:
		return existing
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	seed = build_project_name_seed(ref, shipment_type="Air Import", mode="Air")
	doc = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": ensure_unique_project_name(seed),
			"customer": customer,
			"company": company,
			"custom_client_ref_no": ref,
			"custom_shipment_type": "Air Import",
			"custom_mode_of_transport": "Air",
			"custom_shipment_status": "Draft",
			"custom_bl_number": "176-12345678",
			"notes": "E2E air — workflow starts at Documents Received after seed",
		}
	)
	_append_intake_docs(doc)
	doc.insert(ignore_permissions=True)
	frappe.db.set_value(
		"Project",
		doc.name,
		"custom_shipment_status",
		"Documents Received",
		update_modified=False,
	)
	return doc.name


def _link_sea_records(project, supplier):
	if frappe.db.exists("IDF UCR Record", {"project": project}):
		return
	frappe.get_doc(
		{
			"doctype": "IDF UCR Record",
			"project": project,
			"idf_number": "IDF-TEST-26001",
			"ucr_number": "UCR-TEST-26001",
			"application_date": today(),
			"ucr_payment_status": "Pending",
			"remarks": "Finance pays UCR after Create UCR Application workflow step",
		}
	).insert(ignore_permissions=True)

	if not frappe.db.exists("Container Tracker", {"container_number": "TESTU1234567"}):
		discharge = add_days(today(), -10)
		gate_out = add_days(today(), -5)
		frappe.get_doc(
			{
				"doctype": "Container Tracker",
				"project": project,
				"container_number": "TESTU1234567",
				"batch_bl_no": "SIGMOMB24051234",
				"container_mode": "Mombasa Port",
				"discharging_date": discharge,
				"gate_out_date_port": gate_out,
				"free_days": 5,
				"daily_demurrage_rate": 150,
				"transporter": supplier,
				"truck_number": "KCF 999T",
				"driver_name": "John Test Driver",
				"driver_contact": "+254700000001",
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Customs Entry", {"entry_number": "26NBOIM409252569"}):
		frappe.get_doc(
			{
				"doctype": "Customs Entry",
				"project": project,
				"entry_number": "26NBOIM409252569",
				"e_slip_reference": "ESLIP-TEST-001",
				"idf_tax": 15000,
				"vat": 320000,
				"duty": 180000,
				"excise": 0,
				"payment_status": "Pending",
				"kra_verification_status": "Pending",
				"kebs_verification_status": "Pending",
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Shipping Line Charges", {"project": project}):
		frappe.get_doc(
			{
				"doctype": "Shipping Line Charges",
				"project": project,
				"shipping_line": supplier,
				"local_import_charges": 95000,
				"cfs_code": "SIG",
				"indemnity_form_status": "Pending",
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Port Charges KPA Invoice", {"project": project}):
		frappe.get_doc(
			{
				"doctype": "Port Charges KPA Invoice",
				"project": project,
				"kpa_invoice_number": "KPA-INV-TEST-99",
				"kpa_invoice_amount": 42000,
				"port_compliance_status": "Pending",
			}
		).insert(ignore_permissions=True)


def _daily_status_red():
	if frappe.db.exists("Daily Status Update", {"delays_issues": ["like", f"%{TEST_MARKER}%"]}):
		return
	doc = frappe.get_doc(
		{
			"doctype": "Daily Status Update",
			"date": today(),
			"group_team": "Transport",
			"shipments_dispatched": 3,
			"deliveries_completed": 2,
			"empty_containers_pending": 4,
			"containers_returned_today": 1,
			"delays_issues": f"{TEST_MARKER}: Truck breakdown at port gate — expect 24h delay",
			"outstanding_actions": "Follow up KPA gate pass for TESTU1234567",
			"rag_status": "Red",
		}
	)
	doc.flags.ignore_permissions = True
	doc.submit()


def _print_summary(sea, air, customer):
	print("\n=== CGM Worldwide Shipping E2E test data ===")
	print(f"Customer: {customer}")
	print(f"Sea FCL Project (Draft): {sea}")
	print(f"Air import Project (Documents Received): {air}")
	print(f"Container: TESTU1234567")
	print(f"Filter Projects by Client Ref containing: {TEST_MARKER}")
	print("Workflow: CGM Sea Import Workflow on Project → custom_shipment_status")
	print("See apps/cgm_shipping/TEST_E2E.md for the manual test walkthrough.\n")
