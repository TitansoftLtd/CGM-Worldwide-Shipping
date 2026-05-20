"""
Seed end-to-end test data for CGM Worldwide Shipping module.

Usage:
bench --site <site> execute cgm_shipping.cgm_worldwide_shipping.test_data.seed_e2e_test_data.seed

Re-run safe: skips records that already exist (matched by client_reference).
"""
from __future__ import annotations

import frappe
from frappe.utils import add_days, today


TEST_MARKER = "E2E-TEST-2026"


def seed():
	frappe.only_for("System Manager")
	customer = _ensure_customer()
	supplier = _ensure_supplier()
	employee = _ensure_employee()
	dossier_sea = _ensure_sea_fcl_dossier(customer, supplier, employee)
	dossier_air = _ensure_air_import_dossier(customer, employee)
	_link_sea_records(dossier_sea, supplier)
	_daily_status_red()
	frappe.db.commit()
	_print_summary(dossier_sea, dossier_air, customer)


def _ensure_customer():
	"""Prefer an existing Customer (CGM CRM may require KRA PIN attachment on new ones)."""
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


def _ensure_sea_fcl_dossier(customer, supplier, employee):
	ref = f"{TEST_MARKER}-SEA-FCL"
	existing = frappe.db.get_value("Shipment Dossier", {"client_reference": ref}, "name")
	if existing:
		return existing
	cfs = frappe.db.get_value("CFS Master", {"cfs_name": "Siginon"}, "name") or frappe.db.get_value(
		"CFS Master", {}, "name"
	)
	doc = frappe.get_doc(
		{
			"doctype": "Shipment Dossier",
			"naming_series": "CGM/FCL-.YYYY.-.MM.-.###",
			"shipment_type": "Sea FCL",
			"status": "Draft",
			"client": customer,
			"client_reference": ref,
			"consignee": "Abyssinia Iron Steel Ltd",
			"awb_bl_number": "SIGMOMB24051234",
			"entry_no": "26NBOIM409252569",
			"cfs": cfs,
			"cfs_code": "SIG",
			"weight_nw": 18500,
			"weight_gw": 19200,
			"eta": add_days(today(), 7),
			"vessel_flight": "MV CGM TESTER",
			"shipping_line": supplier,
			"agent_allocated": employee,
			"handling_charges": 45000,
			"breakbulk_charges": 12000,
			"kebs_charges": 8500,
			"charge_notes": "HAN+STOR",
			"description": "Steel coils — 2x40HC test shipment",
			"remarks": "E2E sea FCL — start workflow from Draft",
			"permits": [
				{
					"permit_type": "KEBS",
					"stage": "Pre-clearance",
					"application_date": today(),
					"status": "Applied",
					"issuing_body": "KEBS",
				},
				{
					"permit_type": "Port Health",
					"stage": "Post-clearance",
					"status": "Applied",
					"issuing_body": "Port Health",
				},
			],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_air_import_dossier(customer, employee):
	ref = f"{TEST_MARKER}-AIR"
	existing = frappe.db.get_value("Shipment Dossier", {"client_reference": ref}, "name")
	if existing:
		return existing
	cfs = frappe.db.get_value("CFS Master", {"cfs_name": "FedEx"}, "name") or frappe.db.get_value(
		"CFS Master", {}, "name"
	)
	doc = frappe.get_doc(
		{
			"doctype": "Shipment Dossier",
			"naming_series": "CGM/IM-.YYYY.-.MM.-.###",
			"shipment_type": "Air Import",
			"status": "Draft",
			"client": customer,
			"client_reference": ref,
			"consignee": "Onelife Rally (Test)",
			"awb_bl_number": "176-12345678",
			"cfs": cfs,
			"cfs_code": "MAT",
			"weight_nw": 420,
			"weight_gw": 485,
			"eta": add_days(today(), 2),
			"vessel_flight": "KQ 102",
			"agent_allocated": employee,
			"description": "Pharma samples — air import E2E",
			"remarks": "After seed: apply Receive Documents to reach Documents Received",
		}
	)
	doc.insert(ignore_permissions=True)
	from frappe.model.workflow import apply_workflow

	apply_workflow(doc, "Receive Documents")
	doc.reload()
	return doc.name


def _link_sea_records(dossier, supplier):
	if frappe.db.exists("IDF UCR Record", {"shipment_dossier": dossier}):
		return
	frappe.get_doc(
		{
			"doctype": "IDF UCR Record",
			"shipment_dossier": dossier,
			"idf_number": "IDF-TEST-26001",
			"ucr_number": "UCR-TEST-26001",
			"application_date": today(),
			"ucr_payment_status": "Pending",
			"remarks": "Finance should pay UCR after IDF Open workflow step",
		}
	).insert(ignore_permissions=True)

	if not frappe.db.exists("Container Tracker", {"container_number": "TESTU1234567"}):
		discharge = add_days(today(), -10)
		gate_out = add_days(today(), -5)
		frappe.get_doc(
			{
				"doctype": "Container Tracker",
				"shipment_dossier": dossier,
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
				"shipment_dossier": dossier,
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

	if not frappe.db.exists("Shipping Line Charges", {"shipment_dossier": dossier}):
		frappe.get_doc(
			{
				"doctype": "Shipping Line Charges",
				"shipment_dossier": dossier,
				"shipping_line": supplier,
				"local_import_charges": 95000,
				"cfs_code": "SIG",
				"indemnity_form_status": "Pending",
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Port Charges KPA Invoice", {"shipment_dossier": dossier}):
		frappe.get_doc(
			{
				"doctype": "Port Charges KPA Invoice",
				"shipment_dossier": dossier,
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
	print(f"Sea FCL dossier (Draft): {sea}")
	print(f"Air import dossier (Documents Received): {air}")
	print(f"Container: TESTU1234567")
	print(f"Filter dossiers by Client Reference containing: {TEST_MARKER}")
	print("See apps/cgm_shipping/TEST_E2E.md for the manual test walkthrough.\n")
