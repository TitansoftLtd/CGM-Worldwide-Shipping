// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

const OE_ITEM_GRID_FIELDS = {
	show: ["item_code", "qty", "uom", "rate", "amount"],
	hide: ["warehouse", "from_warehouse", "schedule_date"],
	columns: {
		item_code: 3,
		qty: 1,
		uom: 1,
		rate: 2,
		amount: 2,
	},
};

// Matches local Customize Form: Item Code first so selecting the item can
// populate warehouse. Staging GridView settings put Required By first.
const STANDARD_ITEM_GRID_FIELDS = {
	show: ["item_code", "qty", "uom", "rate", "amount", "schedule_date", "warehouse"],
	hide: [],
	columns: {
		item_code: 2,
		qty: 1,
		uom: 1,
		rate: 1,
		amount: 1,
		schedule_date: 2,
		warehouse: 2,
	},
};

frappe.ui.form.on("Material Request", {
	setup(frm) {
		patch_material_request_set_warehouse_label();
	},

	onload(frm) {
		patch_material_request_set_warehouse_label();
		if (frm.is_new() && !frm.doc.custom_requested_by) {
			frm.set_value("custom_requested_by", frappe.session.user);
		}
		frm._cgm_layout_type = frm.doc.material_request_type;
		set_item_code_query(frm);
		set_employee_from_user(frm);
	},

	refresh(frm) {
		set_item_code_query(frm);
		apply_material_request_form_layout(frm);
		setup_funding_actions(frm);
		set_funding_workflow_indicator(frm);
		if (frm.fields_dict.workflow_state && is_funding_request_type(frm)) {
			frm.set_df_property("workflow_state", "read_only", 1);
		}
	},

	material_request_type(frm) {
		frm._cgm_layout_type = frm.doc.material_request_type;
		set_item_code_query(frm);
		apply_material_request_form_layout(frm, { type_changed: true });
		set_employee_from_user(frm);
	},

	custom_requested_by(frm) {
		set_employee_from_user(frm);
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
		const row = locals[cdt][cdn];
		if (row.warehouse) {
			row.warehouse = null;
		}
		if (row.from_warehouse) {
			row.from_warehouse = null;
		}
		clear_copied_operational_expense_description(cdt, cdn);
		if (typeof frappe.after_ajax === "function") {
			frappe.after_ajax(() => clear_copied_operational_expense_description(cdt, cdn));
		} else {
			setTimeout(() => clear_copied_operational_expense_description(cdt, cdn), 400);
		}
	},

	items_add(frm) {
		apply_item_grid_layout(frm);
	},
});

function patch_material_request_set_warehouse_label() {
	if (frappe.cgm__mr_set_warehouse_label_patched) {
		return;
	}
	const handlers = frappe.ui.form.handlers["Material Request"]?.set_warehouse_label;
	if (!handlers?.length) {
		return;
	}
	const original_handlers = handlers.slice();
	handlers.length = 0;
	handlers.push((frm) => {
		if (is_operational_expense(frm)) {
			apply_item_grid_layout(frm);
			toggle_operational_expense_warehouse(frm);
			return;
		}
		original_handlers.forEach((fn) => fn(frm));
		apply_item_grid_layout(frm);
	});
	frappe.cgm__mr_set_warehouse_label_patched = true;
}

function is_operational_expense(frm) {
	return frm.doc.material_request_type === "Operational Expense";
}

function is_funding_request_type(frm) {
	const type = frm.doc.material_request_type;
	return (
		type === "Operational Expense" || type === "Purchase" || type === "Subcontracting"
	);
}

function set_employee_from_user(frm) {
	if (!is_operational_expense(frm) || frm.doc.custom_employee) {
		return;
	}
	const user = frm.doc.custom_requested_by || frappe.session.user;
	frappe.db.get_value("Employee", { user_id: user, status: "Active" }, "name", (r) => {
		if (r && r.name) {
			frm.set_value("custom_employee", r.name);
		}
	});
}

function apply_material_request_form_layout(frm, opts = {}) {
	const is_oe = is_operational_expense(frm);
	const type_changed = Boolean(opts.type_changed);

	apply_item_grid_layout(frm);

	if (is_oe) {
		if (type_changed) {
			toggle_operational_expense_warehouse(frm);
		}
		["scan_barcode", "set_warehouse", "set_from_warehouse"].forEach((field) => {
			if (frm.fields_dict[field]) {
				frm.toggle_display(field, false);
			}
		});
	} else {
		["scan_barcode", "set_warehouse", "set_from_warehouse"].forEach((field) => {
			if (frm.fields_dict[field]) {
				frm.toggle_display(field, true);
			}
		});
		if (frm.fields_dict.set_warehouse) {
			frm.set_df_property("set_warehouse", "hidden", 0);
		}
	}

	if (frm.fields_dict.buying_price_list) {
		frm.toggle_display("buying_price_list", !is_oe);
	}

	if (frm.fields_dict.custom_request_description) {
		frm.toggle_display("custom_request_description", false);
	}
}

function clear_copied_operational_expense_description(cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row) {
		return;
	}
	const raw = $("<div>")
		.html(row.description || "")
		.text()
		.trim();
	if (!raw) {
		return;
	}
	const name = (row.item_name || "").trim();
	const code = (row.item_code || "").trim();
	if (raw === name || raw === code) {
		frappe.model.set_value(cdt, cdn, "description", "");
	}
}

function set_grid_df_property(grid, fieldname, property, value) {
	if (!grid.get_docfield(fieldname)) {
		return;
	}
	try {
		grid.update_docfield_property(fieldname, property, value);
	} catch (e) {
		const df = grid.get_docfield(fieldname);
		if (df) {
			df[property] = value;
		}
	}
}

function get_item_grid_layout(frm) {
	return is_operational_expense(frm) ? OE_ITEM_GRID_FIELDS : STANDARD_ITEM_GRID_FIELDS;
}

function apply_item_grid_layout(frm) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) {
		return;
	}

	const layout = get_item_grid_layout(frm);
	const other = layout === OE_ITEM_GRID_FIELDS ? STANDARD_ITEM_GRID_FIELDS : OE_ITEM_GRID_FIELDS;

	other.hide.forEach((fieldname) => {
		set_grid_df_property(grid, fieldname, "hidden", 0);
	});
	["description", "expense_account"].forEach((fieldname) => {
		set_grid_df_property(grid, fieldname, "hidden", 0);
		if (!layout.show.includes(fieldname)) {
			set_grid_df_property(grid, fieldname, "in_list_view", 0);
		}
	});

	layout.hide.forEach((fieldname) => {
		set_grid_df_property(grid, fieldname, "hidden", 1);
		set_grid_df_property(grid, fieldname, "in_list_view", 0);
	});
	layout.show.forEach((fieldname) => {
		set_grid_df_property(grid, fieldname, "hidden", 0);
		set_grid_df_property(grid, fieldname, "in_list_view", 1);
		const width = layout.columns[fieldname];
		if (width) {
			set_grid_df_property(grid, fieldname, "columns", width);
		}
	});

	// Staging/user GridView settings override Customize Form. Force the app
	// column order so Item Code stays first on every site.
	if (!grid._cgm_columns_patched) {
		grid.setup_user_defined_columns = function () {
			this.user_defined_columns = build_grid_columns(this, get_item_grid_layout(frm));
		};
		grid._cgm_columns_patched = true;
	}

	const signature = `${is_operational_expense(frm) ? "oe" : "std"}:${layout.show.join(",")}`;
	if (grid._cgm_layout_signature !== signature) {
		if (typeof grid.reset_grid === "function") {
			grid.reset_grid();
		} else if (typeof grid.refresh === "function") {
			grid.refresh();
		}
		grid._cgm_layout_signature = signature;
	}
}

function build_grid_columns(grid, layout) {
	return layout.show
		.map((fieldname) => {
			const df = grid.get_docfield(fieldname);
			if (!df) {
				return null;
			}
			const width = layout.columns[fieldname] || df.columns || 1;
			return Object.assign({}, df, {
				in_list_view: 1,
				hidden: 0,
				columns: width,
				colsize: width,
			});
		})
		.filter(Boolean);
}

function setup_funding_actions(frm) {
	const type = frm.doc.material_request_type;
	const is_oe = type === "Operational Expense";
	const is_purchase = type === "Purchase" || type === "Subcontracting";
	if (!is_oe && !is_purchase) {
		return;
	}

	const approved = [
		"Approved",
		"Partially Approved",
		"Disbursement in Progress",
		"Disbursed",
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
						"This request is on Funding Request {0}. Submit the Journal Entry to mark it Disbursed. It does not go through Purchase Order.",
						[frm.doc.custom_funding_request]
					)
				: approved
					? __(
							"This request is on Funding Request {0}. Funding Approver approval is recorded. The orange Pending badge is ERPNext's submitted status, not approval.",
							[frm.doc.custom_funding_request]
						)
					: __(
							"This request is on Funding Request {0}. Wait for the Funding Approver to approve before creating a Purchase Order. The orange Pending badge is ERPNext's submitted status, not approval.",
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
					"Submitted and waiting for funding. Finance adds this to a Funding Request. Status follows the Journal Entry, not Purchase Order."
				)
			: __(
					"Submitted and waiting for funding. Finance adds this to a Funding Request."
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
	frm.set_df_property("set_warehouse", "hidden", 1);
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (grid) {
		grid.update_docfield_property("warehouse", "hidden", 1);
		grid.update_docfield_property("from_warehouse", "hidden", 1);
	}
	frm.doc.set_warehouse = null;
	frm.doc.set_from_warehouse = null;
	(frm.doc.items || []).forEach((item) => {
		item.warehouse = null;
		item.from_warehouse = null;
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

function set_funding_workflow_indicator(frm) {
	if (!is_funding_request_type(frm)) {
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
			Submitted: "blue",
			"On Funding Request": "blue",
			"Pending Approval": "orange",
			Pending: "orange",
			Approved: "blue",
			"Partially Approved": "orange",
			"Disbursement in Progress": "blue",
			Disbursed: "green",
			Rejected: "red",
		};
		frm.page.set_indicator(__(state), colors[state] || "blue");
	};
	apply();
	setTimeout(apply, 200);
}
