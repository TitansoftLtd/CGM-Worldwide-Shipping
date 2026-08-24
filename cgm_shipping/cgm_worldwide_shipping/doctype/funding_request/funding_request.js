// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

const APPROVED_WORKFLOW_STATES = [
	"Approved",
	"Partially Approved",
	"Disbursement in Progress",
	"Disbursed",
	"Completed",
];

const PENDING_APPROVAL_STATE = "Pending Approval";

const MATERIAL_REQUEST_LINK_PLACEHOLDER = __("Material Request");

frappe.ui.form.on("Funding Request", {
	setup(frm) {
		frm.set_query("material_request", "material_requests", () => ({
			filters: {
				docstatus: 1,
				status: ["!=", "Stopped"],
				company: frm.doc.company || undefined,
			},
		}));
	},

	refresh(frm) {
		frm.dashboard.clear_headline();
		const rows = get_valid_material_request_rows(frm);
		if (rows.length) {
			let total_requested = 0;
			let total_approved = 0;
			let total_funded = 0;
			rows.forEach((row) => {
				total_requested += flt(row.requested_amount);
				if (row.decision === "Approved") {
					total_approved += flt(row.approved_amount);
					total_funded += flt(row.funded_amount);
				}
			});
			const recorded = funding_totals_are_recorded(frm);
			frm.dashboard.set_headline(
				__(
					"Total Requests: {0} | Requested: {1} | Approved: {2} | Paid: {3} | Outstanding: {4}",
					[
						rows.length,
						format_currency(total_requested),
						format_currency(recorded ? total_approved : 0),
						format_currency(total_funded),
						format_currency(recorded ? total_approved - total_funded : 0),
					]
				)
			);
		}

		setup_funding_pay_buttons(frm);

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Material Requests"), () => {
				get_material_requests(frm);
			});
		}

		toggle_approval_row_fields(frm);
	},

	company(frm) {
		frm.set_query("material_request", "material_requests", () => ({
			filters: {
				docstatus: 1,
				status: ["!=", "Stopped"],
				company: frm.doc.company || undefined,
			},
		}));
	},
});

frappe.ui.form.on("Funding Request Material Request", {
	material_request(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!is_valid_material_request_row(row)) {
			return;
		}
		frappe.call({
			method: "cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_material_request_details",
			args: { material_request: row.material_request },
			callback(r) {
				if (!r.message) {
					return;
				}
				const details = r.message;
				frappe.model.set_value(cdt, cdn, {
					employee: details.employee,
					employee_name: details.employee_name,
					item_summary: details.item_summary,
					description: details.description,
					project: details.project,
					requested_amount: details.requested_amount,
					approved_amount: details.approved_amount,
					variance: 0,
					decision: details.decision || "Pending",
					status: details.status,
				});
				update_row_variance(frm, cdt, cdn);
				recalc_totals(frm);
			},
		});
	},

	decision(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.decision === "Rejected") {
			frappe.model.set_value(cdt, cdn, {
				approved_amount: 0,
				variance: 0 - flt(row.requested_amount),
			});
		} else if (row.decision === "Approved") {
			const approved = flt(row.approved_amount) || flt(row.requested_amount);
			frappe.model.set_value(cdt, cdn, {
				approved_amount: approved,
				variance: approved - flt(row.requested_amount),
			});
		}
		recalc_totals(frm);
	},

	approved_amount(frm, cdt, cdn) {
		update_row_variance(frm, cdt, cdn);
		recalc_totals(frm);
	},

	material_requests_remove(frm) {
		recalc_totals(frm);
	},
});

function update_row_variance(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(
		cdt,
		cdn,
		"variance",
		flt(row.approved_amount) - flt(row.requested_amount)
	);
}

function get_approved_material_request_rows(frm) {
	return get_valid_material_request_rows(frm).filter((row) => row.decision === "Approved");
}

function is_valid_material_request_row(row) {
	const mr = (row?.material_request || "").trim();
	if (!mr) {
		return false;
	}
	return mr !== MATERIAL_REQUEST_LINK_PLACEHOLDER && mr !== "Material Request";
}

function get_valid_material_request_rows(frm) {
	return (frm.doc.material_requests || []).filter(is_valid_material_request_row);
}

function funding_totals_are_recorded(frm) {
	return APPROVED_WORKFLOW_STATES.includes(frm.doc.workflow_state);
}

function recalc_totals(frm) {
	const rows = get_valid_material_request_rows(frm);
	const approved_rows = get_approved_material_request_rows(frm);
	let total_requested = 0;
	let total_approved = 0;
	let total_variance = 0;
	let total_funded = 0;
	rows.forEach((row) => {
		total_requested += flt(row.requested_amount);
	});
	approved_rows.forEach((row) => {
		total_approved += flt(row.approved_amount);
		total_variance += flt(row.approved_amount) - flt(row.requested_amount);
		total_funded += flt(row.funded_amount);
	});
	const recorded = funding_totals_are_recorded(frm);
	frm.set_value("total_requests", rows.length);
	frm.set_value("total_requested", total_requested);
	frm.set_value("total_approved", recorded ? total_approved : 0);
	if (frm.fields_dict.total_variance) {
		frm.set_value("total_variance", recorded ? total_variance : 0);
	}
	frm.set_value("total_funded", total_funded);
	frm.set_value("outstanding", recorded ? total_approved - total_funded : 0);
}

function toggle_approval_row_fields(frm) {
	const pending = frm.doc.workflow_state === PENDING_APPROVAL_STATE;
	const grid = frm.fields_dict.material_requests?.grid;
	if (!grid) {
		return;
	}
	["decision", "approved_amount", "adjustment_reason", "rejection_reason"].forEach((fieldname) => {
		grid.update_docfield_property(fieldname, "read_only", pending ? 0 : 1);
	});
}

function get_material_requests(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Get Material Requests"),
		fields: [
			{
				fieldname: "from_date",
				fieldtype: "Date",
				label: __("From Date"),
			},
			{
				fieldname: "to_date",
				fieldtype: "Date",
				label: __("To Date"),
			},
		],
		primary_action_label: __("Get Requests"),
		primary_action(values) {
			frappe.call({
				method: "cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_unfunded_material_requests",
				args: {
					company: frm.doc.company,
					from_date: values.from_date,
					to_date: values.to_date,
				},
				callback(r) {
					d.hide();
					const existing = new Set(
						get_valid_material_request_rows(frm).map((row) => row.material_request)
					);
					(r.message || []).forEach((details) => {
						if (!details.material_request || existing.has(details.material_request)) {
							return;
						}
						existing.add(details.material_request);
						add_material_request_row(frm, details);
					});
					frm.refresh_field("material_requests");
					recalc_totals(frm);
				},
			});
		},
	});
	d.show();
}

function add_material_request_row(frm, details) {
	const row = frm.add_child("material_requests");
	[
		"material_request",
		"decision",
		"employee",
		"employee_name",
		"item_summary",
		"description",
		"project",
		"requested_amount",
		"approved_amount",
		"variance",
		"funded_amount",
		"status",
		"adjustment_reason",
		"rejection_reason",
	].forEach((field) => {
		if (details[field] !== undefined && details[field] !== null) {
			row[field] = details[field];
		}
	});
	if (row.approved_amount === undefined || row.approved_amount === null) {
		row.approved_amount = 0;
	}
	if (!row.decision) {
		row.decision = "Pending";
	}
	if (row.variance === undefined || row.variance === null) {
		row.variance = flt(row.approved_amount) - flt(row.requested_amount);
	}
}

function setup_funding_pay_buttons(frm) {
	if (frm.is_new() || frm.doc.docstatus !== 1 || !APPROVED_WORKFLOW_STATES.includes(frm.doc.workflow_state)) {
		return;
	}
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_funding_pay_options",
		args: { funding_request: frm.doc.name },
		callback(r) {
			const options = r.message || {};
			const has_operational = (options.operational || []).length;
			const has_purchase = (options.purchase || []).length;
			if (!has_operational && !has_purchase) {
				return;
			}
			const register_actions = () => {
				if (has_operational) {
					frm.page.add_action_item(__("Create Journal Entry"), () => {
						create_funding_docs(
							frm,
							"cgm_shipping.cgm_worldwide_shipping.customizations.funding.make_journal_entries",
							"Journal Entry"
						);
					}, true);
				}
				if (has_purchase) {
					frm.page.add_action_item(__("Create Purchase Order"), () => {
						create_funding_docs(
							frm,
							"cgm_shipping.cgm_worldwide_shipping.customizations.funding.make_purchase_orders",
							"Purchase Order"
						);
					}, true);
				}
				frm.page.show_actions_menu();
			};
			register_funding_action_after_workflow(frm, register_actions);
		},
	});
}

function register_funding_action_after_workflow(frm, register_action) {
	const schedule_register = () => {
		const append_action = () => setTimeout(register_action, 50);
		if (frappe.workflow.get_state_fieldname(frm.doctype) && !frm.doc.__islocal) {
			frappe.workflow.get_transitions(frm.doc).then(append_action);
			return;
		}
		register_action();
	};
	schedule_register();
	$(frm.wrapper)
		.off("render_complete.cgm_funding_pay")
		.on("render_complete.cgm_funding_pay", schedule_register);
}

function create_funding_docs(frm, method, doctype) {
	frappe.call({
		method,
		args: { funding_request: frm.doc.name },
		freeze: true,
		callback(r) {
			const names = r.message || [];
			if (!names.length) {
				return;
			}
			frappe.show_alert({
				message: __("Created {0} {1}", [names.length, __(doctype)]),
				indicator: "green",
			});
			frm.reload_doc();
		},
	});
}
