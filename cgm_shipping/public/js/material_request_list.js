// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

const cgm_mr_list_settings = frappe.listview_settings["Material Request"] || {};
const cgm_mr_erpnext_indicator = cgm_mr_list_settings.get_indicator;

frappe.listview_settings["Material Request"] = Object.assign(cgm_mr_list_settings, {
	add_fields: Array.from(
		new Set([...(cgm_mr_list_settings.add_fields || []), "workflow_state", "material_request_type"])
	),
	get_indicator(doc) {
		if (doc.material_request_type === "Operational Expense") {
			return cgm_operational_expense_indicator(doc);
		}
		if (cgm_mr_erpnext_indicator) {
			return cgm_mr_erpnext_indicator(doc);
		}
		return undefined;
	},
});

function cgm_operational_expense_indicator(doc) {
	if (cint(doc.docstatus) === 2 || doc.workflow_state === "Cancelled") {
		return [__("Cancelled"), "red", "docstatus,=,2"];
	}
	const state = doc.workflow_state || (cint(doc.docstatus) === 1 ? "Unfunded" : "Draft");
	const colors = {
		Draft: "gray",
		Unfunded: "orange",
		"On Funding Request": "blue",
		"Pending Director Approval": "orange",
		"Director Approved": "blue",
		Funded: "green",
		Rejected: "red",
		Submitted: "blue",
	};
	return [__(state), colors[state] || "gray", `workflow_state,=,${state}`];
}
