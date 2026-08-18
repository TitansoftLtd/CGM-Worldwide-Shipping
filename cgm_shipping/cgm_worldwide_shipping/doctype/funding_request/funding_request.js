// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("Funding Request", {
	setup(frm) {
		frm.set_query("material_request", "material_requests", () => {
			return {
				filters: {
					docstatus: 1,
					status: ["!=", "Stopped"],
					company: frm.doc.company || undefined,
				},
			};
		});
	},

	onload(frm) {
		remove_blank_material_request_rows(frm, false);
	},

	before_save(frm) {
		remove_blank_material_request_rows(frm, false);
	},

	refresh(frm) {
		frm.dashboard.clear_headline();
		if (frm.doc.total_requests) {
			frm.dashboard.set_headline(
				__(
					"Total Requests: {0} | Requested: {1} | Approved: {2} | Paid: {3} | Outstanding: {4}",
					[
						frm.doc.total_requests,
						format_currency(frm.doc.total_requested),
						format_currency(frm.doc.total_approved),
						format_currency(frm.doc.total_funded),
						format_currency(frm.doc.outstanding),
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

		toggle_approved_amount_editable(frm);
		remove_blank_material_request_rows(frm, false);
		strip_duplicate_grid_headers(frm);
	},

	company(frm) {
		frm.set_query("material_request", "material_requests", () => {
			return {
				filters: {
					docstatus: 1,
					status: ["!=", "Stopped"],
					company: frm.doc.company || undefined,
				},
			};
		});
	},
});

frappe.ui.form.on("Funding Request Material Request", {
	material_request(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.material_request) {
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
					reduction_amount: 0,
					status: details.status,
				});
			},
		});
	},

	approved_amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const requested = flt(row.requested_amount);
		const approved = flt(row.approved_amount);
		frappe.model.set_value(cdt, cdn, "reduction_amount", requested - approved);
		recalc_totals(frm);
	},

	material_requests_remove(frm) {
		recalc_totals(frm);
	},
});

function recalc_totals(frm) {
	let total_requested = 0;
	let total_approved = 0;
	let total_funded = 0;
	(frm.doc.material_requests || []).forEach((row) => {
		total_requested += flt(row.requested_amount);
		total_approved += flt(row.approved_amount);
		total_funded += flt(row.funded_amount);
	});
	const recorded = [
		"Director Approved",
		"Funding in Progress",
		"Funded",
		"Completed",
	].includes(frm.doc.workflow_state);
	frm.set_value("total_requests", (frm.doc.material_requests || []).length);
	frm.set_value("total_requested", total_requested);
	frm.set_value("total_approved", recorded ? total_approved : 0);
	frm.set_value("total_reduction", recorded ? total_requested - total_approved : 0);
	frm.set_value("total_funded", total_funded);
	frm.set_value("outstanding", recorded ? total_approved - total_funded : 0);
}

function toggle_approved_amount_editable(frm) {
	const editable = frm.doc.workflow_state === "Pending Director Approval";
	const grid = frm.fields_dict.material_requests?.grid;
	if (!grid) {
		return;
	}
	const df = (grid.docfields || []).find((d) => d.fieldname === "approved_amount");
	const want_read_only = editable ? 0 : 1;
	if (df && cint(df.read_only) === want_read_only) {
		return;
	}
	grid.update_docfield_property("approved_amount", "read_only", want_read_only);
	grid.update_docfield_property("reduction_reason", "read_only", want_read_only);
}

function strip_duplicate_grid_headers(frm) {
	const run = () => {
		const grid = frm.fields_dict.material_requests?.grid;
		const $heading = grid?.wrapper?.find(".grid-heading-row");
		if (!$heading?.length) {
			return;
		}
		$heading.find(".grid-row.filter-row").remove();
		$heading.find(".grid-row").slice(1).remove();
		$heading.removeClass("with-filter");
		remove_blank_material_request_rows(frm, false);
	};
	run();
	setTimeout(run, 50);
	setTimeout(run, 250);
	setTimeout(run, 600);
}

function remove_blank_material_request_rows(frm, refresh) {
	const rows = frm.doc.material_requests || [];
	const drop = rows.filter((row) => !row.material_request);
	if (!drop.length) {
		return;
	}
	drop.forEach((row) => {
		if (row.doctype && row.name) {
			frappe.model.clear_doc(row.doctype, row.name);
		}
	});
	frm.doc.material_requests = rows.filter((row) => row.material_request);
	(frm.doc.material_requests || []).forEach((row, i) => {
		row.idx = i + 1;
	});
	if (refresh !== false) {
		frm.refresh_field("material_requests");
	}
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
					remove_blank_material_request_rows(frm, false);
					const existing = new Set(
						(frm.doc.material_requests || [])
							.map((row) => row.material_request)
							.filter(Boolean)
					);
					(r.message || []).forEach((details) => {
						if (!details.material_request || existing.has(details.material_request)) {
							return;
						}
						existing.add(details.material_request);
						add_material_request_row(frm, details);
					});
					frm.refresh_field("material_requests");
					strip_duplicate_grid_headers(frm);
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
		"employee",
		"employee_name",
		"item_summary",
		"description",
		"project",
		"requested_amount",
		"approved_amount",
		"reduction_amount",
		"funded_amount",
		"status",
		"reduction_reason",
	].forEach((field) => {
		if (details[field] !== undefined && details[field] !== null) {
			row[field] = details[field];
		}
	});
	if (row.approved_amount === undefined || row.approved_amount === null) {
		row.approved_amount = 0;
	}
	if (row.reduction_amount === undefined || row.reduction_amount === null) {
		row.reduction_amount = 0;
	}
}

function setup_funding_pay_buttons(frm) {
	const approved_states = [
		"Director Approved",
		"Funding in Progress",
		"Funded",
		"Completed",
	];
	if (frm.is_new() || frm.doc.docstatus !== 1 || !approved_states.includes(frm.doc.workflow_state)) {
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
