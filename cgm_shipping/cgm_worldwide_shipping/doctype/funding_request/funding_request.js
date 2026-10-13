// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

const MATERIAL_REQUEST_LINK_PLACEHOLDER = __("Material Request");

function fundable_material_request_filters(frm) {
	return {
		docstatus: 1,
		status: ["!=", "Stopped"],
		material_request_type: ["in", ["Purchase", "Operational Expense"]],
		workflow_state: ["in", ["Unfunded", "Submitted"]],
		company: frm.doc.company || undefined,
	};
}

frappe.ui.form.on("Funding Request", {
	setup(frm) {
		frm.set_query("material_request", "material_requests", () => ({
			filters: fundable_material_request_filters(frm),
		}));
	},

	refresh(frm) {
		frm.dashboard.clear_headline();
		const rows = get_valid_material_request_rows(frm);
		if (rows.length) {
			const base_currency = frappe.get_doc(":Company", frm.doc.company)?.default_currency;
			let total_requested = 0;
			let total_approved = 0;
			let total_funded = 0;
			// Rows can be in different currencies, so the headline figures are the
			// company-currency twins. Adding `requested_amount` across a mixed
			// request would put KES and USD in one number.
			const per_currency = {};
			rows.forEach((row) => {
				const rate = flt(row.exchange_rate) || 1;
				const currency = row.currency || base_currency;
				const requested = flt(row.requested_amount);
				const approved = row.decision === "Approved" ? flt(row.approved_amount) : 0;
				total_requested += flt(row.base_requested_amount) || requested * rate;
				if (row.decision === "Approved") {
					total_approved += flt(row.base_approved_amount) || approved * rate;
					total_funded += flt(row.base_funded_amount) || flt(row.funded_amount) * rate;
				}
				if (!per_currency[currency]) {
					per_currency[currency] = { requested: 0, approved: 0 };
				}
				per_currency[currency].requested += requested;
				per_currency[currency].approved += approved;
			});
			const recorded = funding_totals_are_recorded(frm);
			let headline = __(
				"Total Requests: {0} | Requested: {1} | Approved: {2} | Paid: {3} | Outstanding: {4}",
				[
					rows.length,
					format_currency(total_requested, base_currency),
					format_currency(recorded ? total_approved : 0, base_currency),
					format_currency(total_funded, base_currency),
					format_currency(recorded ? total_approved - total_funded : 0, base_currency),
				]
			);
			// Only worth a second line when something is not in the company
			// currency; otherwise it would repeat the figures above.
			const currencies = Object.keys(per_currency);
			if (currencies.some((currency) => currency !== base_currency)) {
				const parts = currencies
					.sort((a, b) => (a === base_currency ? -1 : b === base_currency ? 1 : a.localeCompare(b)))
					.map((currency) => {
						const totals = per_currency[currency];
						const value = recorded ? totals.approved : totals.requested;
						return `${currency} ${format_number(value, null, 2)}`;
					});
				headline += `<br>${__(recorded ? "Approved by currency" : "Requested by currency")}: ${parts.join(
					" &nbsp;|&nbsp; "
				)}`;
			}
			// permanent = true. set_headline renders a dismissable block otherwise,
			// and the X it adds removes the node without recording that it was
			// dismissed - so the totals vanished on a click and came back on the
			// next refresh. These are the figures the approval decision is made
			// against, so they stay put and carry no close button.
			frm.dashboard.set_headline(headline, "blue", true);
		}

		setup_funding_pay_buttons(frm);

		if (frm.doc.docstatus === 0) {
			const $get = frm.add_custom_button(__("Get Material Requests"), () => {
				get_material_requests(frm);
			});
			// On an empty draft this is the only thing to do, so it carries the
			// primary weight. Once rows are on the request it steps back to a
			// plain button and Submit becomes the obvious next action.
			const has_rows = get_valid_material_request_rows(frm).length > 0;
			frm.change_custom_button_type(
				__("Get Material Requests"),
				null,
				has_rows ? "default" : "primary"
			);
			$get.prepend(frappe.utils.icon("download", "sm", "cgm-get-mr-icon"));
		}

		toggle_approval_row_fields(frm);
	},

	company(frm) {
		frm.set_query("material_request", "material_requests", () => ({
			filters: fundable_material_request_filters(frm),
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
				const rows = r.message || [];
				if (!rows.length) {
					return;
				}
				// A request holding more than one currency becomes one row per
				// currency: they are approved separately and paid separately,
				// because a Journal Entry leaves one bank account in one currency.
				const [details, ...extra] = rows;
				frappe.model.set_value(cdt, cdn, {
					employee: details.employee,
					employee_name: details.employee_name,
					item_summary: details.item_summary,
					description: details.description,
					project: details.project,
					currency: details.currency,
					exchange_rate: details.exchange_rate,
					requested_amount: details.requested_amount,
					base_requested_amount: details.base_requested_amount,
					approved_amount: details.approved_amount,
					variance: 0,
					decision: details.decision || "Pending",
					status: details.status,
				});
				extra.forEach((row) => add_material_request_row(frm, row));
				if (extra.length) {
					frappe.show_alert({
						message: __("{0} is in {1} currencies, so it was split into {2} rows.", [
							details.material_request,
							rows.length,
							rows.length,
						]),
						indicator: "blue",
					});
				}
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
	return cint(frm.doc.docstatus) === 1;
}

function recalc_totals(frm) {
	const rows = get_valid_material_request_rows(frm);
	const approved_rows = get_approved_material_request_rows(frm);
	let total_requested = 0;
	let total_approved = 0;
	let total_variance = 0;
	let total_funded = 0;
	// The header totals are company currency. A row carries its amounts in its own
	// currency, so each one is taken through its base twin - falling back to the
	// rate for a row the server has not stamped yet. Summing the row figures
	// directly would add KES and USD together on a mixed request.
	const in_base = (row, fieldname) =>
		flt(row[`base_${fieldname}`]) || flt(row[fieldname]) * (flt(row.exchange_rate) || 1);
	rows.forEach((row) => {
		total_requested += in_base(row, "requested_amount");
	});
	approved_rows.forEach((row) => {
		total_approved += in_base(row, "approved_amount");
		total_variance += in_base(row, "approved_amount") - in_base(row, "requested_amount");
		total_funded += in_base(row, "funded_amount");
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
	const grid = frm.fields_dict.material_requests?.grid;
	if (!grid) {
		return;
	}
	const set_read_only = (read_only) => {
		["decision", "approved_amount", "adjustment_reason", "rejection_reason"].forEach((fieldname) => {
			grid.update_docfield_property(fieldname, "read_only", read_only);
		});
	};
	if (!frm.doc.workflow_state) {
		set_read_only(1);
		return;
	}
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.funding.funding_request_is_pending_approval",
		args: { workflow_state: frm.doc.workflow_state },
		callback(r) {
			set_read_only(r.message ? 0 : 1);
		},
	});
}

function get_material_requests(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Get Material Requests"),
		size: "small",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "intro",
				options: `<p class="cgm-dialog-intro">${__(
					"Submitted requests not yet on a Funding Request. Leave the dates blank for all outstanding."
				)}</p>`,
			},
			{
				// Without this the intro shares a column with From Date and the two
				// dates end up on different rows at different heights.
				fieldtype: "Section Break",
				fieldname: "sec_dates",
			},
			{
				fieldname: "from_date",
				fieldtype: "Date",
				label: __("From Date"),
			},
			{
				fieldtype: "Column Break",
				fieldname: "col_dates",
			},
			{
				fieldname: "to_date",
				fieldtype: "Date",
				label: __("To Date"),
			},
		],
		primary_action_label: __("Get Requests"),
		primary_action(values) {
			if (values.from_date && values.to_date && values.from_date > values.to_date) {
				frappe.msgprint({
					title: __("Check the dates"),
					indicator: "orange",
					message: __("From Date is after To Date, so no request can fall between them."),
				});
				return;
			}
			d.get_primary_btn().prop("disabled", true).text(__("Fetching..."));
			frappe.call({
				method: "cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_unfunded_material_requests",
				args: {
					company: frm.doc.company,
					from_date: values.from_date,
					to_date: values.to_date,
				},
				always() {
					d.get_primary_btn().prop("disabled", false).text(__("Get Requests"));
				},
				callback(r) {
					const existing = new Set(
						get_valid_material_request_rows(frm).map((row) => row.material_request)
					);
					const fetched = r.message || [];
					let added = 0;
					fetched.forEach((details) => {
						if (!details.material_request || existing.has(details.material_request)) {
							return;
						}
						existing.add(details.material_request);
						add_material_request_row(frm, details);
						added += 1;
					});
					frm.refresh_field("material_requests");
					recalc_totals(frm);
					// Closing on an empty result looked like a broken button. Say what
					// happened instead, and keep the dialog open so the dates can be
					// widened without reopening it.
					if (!added) {
						frappe.msgprint({
							title: __("Nothing to add"),
							indicator: "orange",
							message: fetched.length
								? __("Every request found is already on this Funding Request.")
								: __(
										"No submitted Material Request is waiting for funding in that date range."
								  ),
						});
						return;
					}
					d.hide();
					frappe.show_alert({
						message: __("{0} request(s) added.", [added]),
						indicator: "green",
					});
				},
			});
		},
	});
	d.show();
	brand_dialog(d);
}

// CGM maroon, the colour used across every CGM print format. Applied to the
// dialog's primary button so an action that pulls real requests into a funding
// document looks like it belongs to CGM rather than to stock Frappe.
const CGM_MAROON = "#8b1a1a";
const CGM_MAROON_DARK = "#6f1515";

function brand_dialog(dialog) {
	const $btn = dialog.get_primary_btn();
	if (!$btn || !$btn.length) {
		return;
	}
	$btn.css({
		"background-color": CGM_MAROON,
		"border-color": CGM_MAROON,
		color: "#fff",
	});
	$btn.on("mouseenter", () =>
		$btn.css({ "background-color": CGM_MAROON_DARK, "border-color": CGM_MAROON_DARK })
	);
	$btn.on("mouseleave", () =>
		$btn.css({ "background-color": CGM_MAROON, "border-color": CGM_MAROON })
	);
	dialog.$wrapper.find(".cgm-dialog-intro").css({
		color: "var(--text-muted)",
		"font-size": "var(--text-sm)",
		"line-height": "1.5",
		margin: "0 0 4px",
		"padding-left": "8px",
		"border-left": `3px solid ${CGM_MAROON}`,
	});
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
		"currency",
		"exchange_rate",
		"requested_amount",
		"base_requested_amount",
		"approved_amount",
		"base_approved_amount",
		"variance",
		"funded_amount",
		"base_funded_amount",
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
	if (frm.is_new() || frm.doc.docstatus !== 1) {
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
						choose_payment_banks(frm, options, (bank_accounts) => {
							create_funding_docs(
								frm,
								"cgm_shipping.cgm_worldwide_shipping.customizations.funding.make_journal_entries",
								"Journal Entry",
								{ bank_accounts: JSON.stringify(bank_accounts) }
							);
						});
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


function choose_payment_banks(frm, options, proceed) {
	const currencies = options.currencies || [];
	const company_currency = options.company_currency;
	const rows = options.operational || [];

	// One account per currency about to be paid. Which account money leaves is a
	// treasury decision taken per payment, so it is asked here rather than
	// configured once and quietly reused.
	const fields = [
		{
			fieldtype: "HTML",
			fieldname: "intro",
			options: `<p class="cgm-dialog-intro">${__(
				"{0} draft entry(s) will be created, one per approved request. Nothing is paid until you submit them.",
				[rows.length]
			)}</p>`,
		},
	];

	currencies.forEach((currency, index) => {
		if (index) {
			fields.push({ fieldtype: "Section Break" });
		}
		const in_currency = rows.filter((row) => row.currency === currency);
		const total = in_currency.reduce((sum, row) => sum + flt(row.remaining), 0);
		fields.push({
			fieldname: `bank_${currency}`,
			fieldtype: "Link",
			options: "Account",
			reqd: 1,
			label:
				currencies.length > 1
					? __("Pay {0} {1} from", [currency, format_number(total, null, 2)])
					: __("Pay from"),
			default: currency === company_currency ? options.default_bank_account : null,
			description:
				currency === company_currency
					? null
					: __("Held in {0} or {1}.", [currency, company_currency]),
			get_query() {
				return {
					filters: {
						company: frm.doc.company,
						is_group: 0,
						account_type: ["in", ["Bank", "Cash"]],
						account_currency: ["in", [currency, company_currency]],
					},
				};
			},
		});
	});

	if (!currencies.length) {
		proceed({});
		return;
	}

	const d = new frappe.ui.Dialog({
		title: __("Create Journal Entry"),
		size: currencies.length > 1 ? "small" : "small",
		fields,
		primary_action_label: __("Create Draft Entries"),
		primary_action(values) {
			const bank_accounts = {};
			let missing = null;
			currencies.forEach((currency) => {
				const account = values[`bank_${currency}`];
				if (!account) {
					missing = missing || currency;
					return;
				}
				bank_accounts[currency] = account;
			});
			if (missing) {
				frappe.msgprint({
					title: __("Choose an account"),
					indicator: "orange",
					message: __("Select the bank account {0} is paid from.", [missing]),
				});
				return;
			}
			d.hide();
			proceed(bank_accounts);
		},
	});
	d.show();
	brand_dialog(d);
}

function create_funding_docs(frm, method, doctype, extra_args) {
	frappe.call({
		method,
		args: Object.assign({ funding_request: frm.doc.name }, extra_args || {}),
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
