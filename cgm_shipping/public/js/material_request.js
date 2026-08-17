// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("Material Request", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.custom_requested_by) {
			frm.set_value("custom_requested_by", frappe.session.user);
		}
		set_item_code_query(frm);
	},

	refresh(frm) {
		if (frm.fields_dict.material_request_type) {
			frm.set_df_property(
				"material_request_type",
				"description",
				__(
					"How the request is processed. Items describe what is requested and carry the accounting classification."
				)
			);
		}
		set_item_code_query(frm);
		toggle_operational_expense_warehouse(frm);
		setup_funding_actions(frm);
		set_operational_expense_indicator(frm);
	},

	material_request_type(frm) {
		set_item_code_query(frm);
		toggle_operational_expense_warehouse(frm);
	},

	custom_project(frm) {
		if (!frm.doc.custom_project) {
			return;
		}
		(frm.doc.items || []).forEach((item) => {
			if (!item.project) {
				frappe.model.set_value(item.doctype, item.name, "project", frm.doc.custom_project);
			}
		});
	},

	custom_employee(frm) {
		if (!frm.doc.custom_employee || frm.doc.custom_requested_by) {
			return;
		}
		frappe.db.get_value("Employee", frm.doc.custom_employee, "user_id", (r) => {
			if (r && r.user_id) {
				frm.set_value("custom_requested_by", r.user_id);
			}
		});
	},
});

frappe.ui.form.on("Material Request Item", {
	item_code(frm, cdt, cdn) {
		if (frm.doc.material_request_type !== "Operational Expense") {
			return;
		}
		const clear_warehouse = () => {
			if (locals[cdt][cdn] && locals[cdt][cdn].warehouse) {
				frappe.model.set_value(cdt, cdn, "warehouse", "");
			}
		};
		clear_warehouse();
		// ERPNext get_item_details fills warehouse after this event; clear again.
		frappe.after_ajax(clear_warehouse);
	},

	project(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!frm.doc.custom_project && row.project) {
			frm.set_value("custom_project", row.project);
		}
	},
});

function setup_funding_actions(frm) {
	const type = frm.doc.material_request_type;
	const is_oe = type === "Operational Expense";
	const is_purchase = type === "Purchase" || type === "Subcontracting";
	if (!is_oe && !is_purchase) {
		return;
	}

	const approved = [
		"Director Approved",
		"Funding in Progress",
		"Funded",
	].includes(frm.doc.workflow_state);

	const hide_purchase_create = () => {
		const labels = is_oe
			? [
					"Purchase Order",
					"Request for Quotation",
					"Supplier Quotation",
					"Pick List",
					"Work Order",
					"Material Transfer",
					"Material Transfer (In Transit)",
					"Issue Material",
					"Material Receipt",
					"Subcontracted Purchase Order",
				]
			: ["Purchase Order", "Request for Quotation", "Supplier Quotation", "Subcontracted Purchase Order"];
		if (is_purchase && approved) {
			return;
		}
		labels.forEach((label) => frm.remove_custom_button(__(label), __("Create")));
	};
	hide_purchase_create();
	setTimeout(hide_purchase_create, 200);

	if (frm.doc.docstatus !== 1 || frm.doc.status === "Stopped") {
		return;
	}

	if (is_purchase && approved) {
		return;
	}

	frm.dashboard.clear_headline();
	if (frm.doc.custom_funding_request) {
		frm.dashboard.set_headline(
			is_oe
				? __(
						"This request is on Funding Request {0}. Pay the Employee Advance to mark it Funded. It does not go through Purchase Order.",
						[frm.doc.custom_funding_request]
					)
				: approved
					? __(
							"This request is on Funding Request {0}. Director approval is there. The orange Pending badge is ERPNext's submitted status, not approval.",
							[frm.doc.custom_funding_request]
						)
					: __(
							"This request is on Funding Request {0}. Wait for the Director to approve before creating a Purchase Order. The orange Pending badge is ERPNext's submitted status, not approval.",
							[frm.doc.custom_funding_request]
						)
		);
		frm.add_custom_button(__("Open Funding Request"), () => {
			frappe.set_route("Form", "Funding Request", frm.doc.custom_funding_request);
		});
		return;
	}

	frm.dashboard.set_headline(
		is_oe
			? __(
					"Submitted and waiting for funding. Finance adds this to a Funding Request. Status follows the Employee Advance payment, not Purchase Order."
				)
			: __(
					"Director must approve this Purchase request on a Funding Request before a Purchase Order or quotation can be created."
				)
	);
	frm.add_custom_button(__("Add to Funding Request"), () => open_funding_request(frm));
}

function open_funding_request(frm) {
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.funding.make_funding_request",
		args: { material_request: frm.doc.name },
		callback(r) {
			if (!r.message) {
				return;
			}
			const values = r.message;
			delete values.name;
			delete values.naming_series;
			frappe.new_doc("Funding Request", values);
		},
	});
}

function toggle_operational_expense_warehouse(frm) {
	const is_oe = frm.doc.material_request_type === "Operational Expense";
	frm.set_df_property("set_warehouse", "hidden", is_oe);
	if (frm.fields_dict.items && frm.fields_dict.items.grid) {
		frm.fields_dict.items.grid.update_docfield_property("warehouse", "hidden", is_oe);
	}
	if (!is_oe) {
		return;
	}
	if (frm.doc.set_warehouse) {
		frm.set_value("set_warehouse", "");
	}
	(frm.doc.items || []).forEach((item) => {
		if (item.warehouse) {
			frappe.model.set_value(item.doctype, item.name, "warehouse", "");
		}
	});
}

function set_item_code_query(frm) {
	if (frm.doc.material_request_type === "Operational Expense") {
		frm.set_query("item_code", "items", () => ({
			query: "erpnext.controllers.queries.item_query",
			filters: { is_stock_item: 0 },
		}));
		return;
	}
	frm.set_query("item_code", "items", (doc) => {
		let filters = { is_stock_item: 1 };
		if (doc.material_request_type == "Customer Provided") {
			filters.customer = doc.customer;
		} else if (
			doc.material_request_type == "Purchase" ||
			doc.material_request_type == "Subcontracting"
		) {
			filters = { is_purchase_item: 1 };
		} else if (doc.material_request_type == "Manufacture") {
			filters.include_item_in_manufacturing = 1;
		}
		return {
			query: "erpnext.controllers.queries.item_query",
			filters,
		};
	});
}

function set_operational_expense_indicator(frm) {
	if (frm.doc.material_request_type !== "Operational Expense") {
		return;
	}
	const apply = () => {
		if (cint(frm.doc.docstatus) === 2) {
			frm.page.set_indicator(__("Cancelled"), "red");
			return;
		}
		const state =
			frm.doc.workflow_state || (cint(frm.doc.docstatus) === 1 ? "Unfunded" : "Draft");
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
		frm.page.set_indicator(__(state), colors[state] || "blue");
	};
	apply();
	setTimeout(apply, 200);
}
