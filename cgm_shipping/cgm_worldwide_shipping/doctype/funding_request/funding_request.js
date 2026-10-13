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

	before_workflow_action(frm) {
		const action = frm.selected_workflow_action;
		if (PAYING_ACTIONS.includes(action)) {
			return prepare_disbursement(frm, action);
		}
		if (PURCHASE_ORDER_ACTIONS.includes(action)) {
			return open_pending_purchase_orders(frm);
		}
		if (is_cancelling_action(frm, action)) {
			return confirm_cancellation(frm, action);
		}
	},

	after_workflow_action(frm) {
		if (frm.__cgm_disbursing) {
			frm.__cgm_disbursing = false;
			show_last_disbursement(frm);
		}
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
					// A request raised in two currencies comes back as two rows, one per
					// currency. Matching on the request alone kept the first and dropped
					// the second as a duplicate, so the USD half of a mixed request never
					// reached the Funding Request from here.
					const row_key = (row) => `${row.material_request}|${row.currency || ""}`;
					const existing = new Set(get_valid_material_request_rows(frm).map(row_key));
					const fetched = r.message || [];
					let added = 0;
					fetched.forEach((details) => {
						if (!details.material_request || existing.has(row_key(details))) {
							return;
						}
						existing.add(row_key(details));
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
// The Disburse dialogs are blue: paying out is a different kind of step from
// pulling requests in, and it should not look like the same dialog.
const DISBURSE_BLUE = "#2563eb";
const DISBURSE_BLUE_DARK = "#1d4ed8";
const DISBURSE_BLUE_SOFT = "#eff6ff";
const DISBURSE_BLUE_LINE = "#bfdbfe";
const DISBURSE_BLUE_TEXT = "#1e3a8a";

function brand_dialog(dialog, colour = CGM_MAROON, colour_dark = CGM_MAROON_DARK) {
	const $btn = dialog.get_primary_btn();
	if (!$btn || !$btn.length) {
		return;
	}
	$btn.css({
		"background-color": colour,
		"border-color": colour,
		color: "#fff",
	});
	$btn.on("mouseenter", () =>
		$btn.css({ "background-color": colour_dark, "border-color": colour_dark })
	);
	$btn.on("mouseleave", () =>
		$btn.css({ "background-color": colour, "border-color": colour })
	);
	dialog.$wrapper.find(".cgm-dialog-intro").css({
		color: "var(--text-muted)",
		"font-size": "var(--text-sm)",
		"line-height": "1.5",
		margin: "0 0 4px",
		"padding-left": "8px",
		"border-left": `3px solid ${colour}`,
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
	// Payment is the Disburse workflow action, which the workflow itself lists in
	// the Actions menu; nothing is added here any more. What is left is removing
	// the handler earlier versions of this form bound, which kept re-adding a
	// dead payment action to a Completed request.
	$(frm.wrapper).off("render_complete.cgm_funding_pay");
}

function choose_payment_banks(frm, options, proceed) {
	const currencies = options.currencies || [];
	const company_currency = options.company_currency;
	// Rows with a draft entry already have their bank account on the draft.
	const rows = (options.operational || []).filter((row) => !row.draft_entry);

	// One account per currency about to be paid. Which account money leaves is a
	// treasury decision taken per payment, so it is asked here rather than
	// configured once and quietly reused.
	const fields = [
		{
			fieldtype: "HTML",
			fieldname: "intro",
			options: `<p class="cgm-dialog-intro">${__(
				"Choose the account each payment leaves. You will be asked to confirm before anything is posted."
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
		title: __("Disburse"),
		size: "small",
		fields,
		primary_action_label: __("Continue"),
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
	brand_dialog(d, DISBURSE_BLUE, DISBURSE_BLUE_DARK);
}

// The workflow offers one of these at a time, named after what the request is
// waiting on (Funding Request.pending_step). The first three create or post the
// payment documents. The last two are done on the Purchase Order itself, so the
// action takes the user to it and leaves the request as it is.
const PAYING_ACTIONS = ["Disburse", "Create Purchase Order", "Submit Journal Entry"];
const PURCHASE_ORDER_ACTIONS = ["Submit Purchase Order", "Record Purchase Payment"];

// Cancelling is the one step that undoes postings, so it is red.
const CANCEL_RED = "#dc2626";
const CANCEL_RED_DARK = "#b91c1c";
const CANCEL_RED_SOFT = "#fef2f2";
const CANCEL_RED_LINE = "#fecaca";
const CANCEL_RED_TEXT = "#7f1d1d";

function is_cancelling_action(frm, action) {
	// By where the action leads, not by its name: the name can be changed in Desk.
	const workflow = (frappe.workflow.workflows || {})[frm.doctype];
	const transition = ((workflow && workflow.transitions) || []).find(
		(t) => t.state === frm.doc.workflow_state && t.action === action
	);
	const target = transition && (workflow.states || []).find((st) => st.state === transition.next_state);
	if (target) {
		return cint(target.doc_status) === 2;
	}
	return /cancel/i.test(action || "");
}

function confirm_cancellation(frm, action) {
	// Cancelling a request now takes its entries and orders with it. That reverses
	// ledger postings, so the person is shown each document and what happens to it
	// before anything is touched.
	frappe.dom.unfreeze();
	return new Promise((resolve) => {
		frappe.call({
			method: "cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_funding_cancel_impact",
			args: { funding_request: frm.doc.name },
			callback(r) {
				const impact = r.message || {};
				const esc = frappe.utils.escape_html;
				const link = (doctype, name) =>
					`<a href="${frappe.utils.get_form_link(doctype, name)}" target="_blank" rel="noopener" style="color:${CANCEL_RED};text-decoration:underline;">${esc(name)}</a>`;
				const cell = `padding:9px 12px;border-top:1px solid ${CANCEL_RED_LINE};vertical-align:top;`;
				const head = `padding:7px 12px;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:${CANCEL_RED_TEXT};text-align:left;`;
				const section = (title, rows) => `
					<div style="border:1px solid ${CANCEL_RED_LINE};border-radius:10px;margin:0 0 12px;overflow:hidden;">
						<div style="padding:10px 12px;background:${CANCEL_RED_SOFT};color:${CANCEL_RED_TEXT};display:flex;justify-content:space-between;align-items:center;">
							<span style="font-weight:600;">${title}</span>
							<span style="font-size:12px;font-weight:600;background:${CANCEL_RED};color:#fff;border-radius:999px;min-width:22px;text-align:center;padding:1px 7px;">${rows.length}</span>
						</div>
						<table style="width:100%;border-collapse:collapse;font-size:13px;">
							<thead><tr>
								<th style="${head}">${__("Document")}</th>
								<th style="${head}">${__("Request")}</th>
								<th style="${head}text-align:right;">${__("Amount")}</th>
							</tr></thead>
							<tbody>${rows
								.map(
									(row) => `<tr>
										<td style="${cell}font-weight:600;">${link(row.doctype, row.name)}<div class="text-muted" style="font-size:12px;font-weight:400;">${__(row.doctype)}</div></td>
										<td style="${cell}">${(row.material_request || "")
											.split(", ")
											.filter(Boolean)
											.map((name) => link("Material Request", name))
											.join(", ")}</td>
										<td style="${cell}text-align:right;white-space:nowrap;font-weight:600;color:${CANCEL_RED_TEXT};">${esc(impact.currency || "")} ${format_number(row.amount, null, 2)}</td>
									</tr>`
								)
								.join("")}</tbody>
						</table>
					</div>`;

				let html = "";
				if ((impact.cancel || []).length) {
					html += section(__("Submitted, will be cancelled"), impact.cancel);
				}
				if ((impact.delete || []).length) {
					html += section(__("Drafts, will be deleted"), impact.delete);
				}
				const requests = (impact.material_requests || []).map((name) => link("Material Request", name)).join(", ");
				html += `<p style="margin:4px 2px 0;font-size:13px;">${__("Released to be funded again: {0}", [requests || "-"])}</p>`;

				const d = new frappe.ui.Dialog({
					title: `${__(action)} ${frm.doc.name}`,
					fields: [{ fieldtype: "HTML", fieldname: "impact", options: html }],
					primary_action_label: __(action),
					primary_action() {
						d.hide();
						frappe.dom.freeze(__("Cancelling..."));
						resolve();
					},
					secondary_action_label: __("Go Back"),
					secondary_action() {
						d.hide();
					},
				});
				d.show();
				brand_dialog(d, CANCEL_RED, CANCEL_RED_DARK);
				d.$wrapper.find(".modal-header").css({ background: CANCEL_RED, "border-bottom-color": CANCEL_RED });
				d.$wrapper.find(".modal-title").css({ color: "#fff" });
				d.$wrapper.find(".modal-header .btn-modal-close, .modal-header .modal-actions .btn").css({ color: "#fff" });
				d.$wrapper.find(".modal-header svg").css({ stroke: "#fff" });
			},
		});
	});
}

function open_pending_purchase_orders(frm) {
	frappe.dom.unfreeze();
	// Never resolved: nothing changes on the request, so the workflow call that
	// would follow is deliberately not made.
	return new Promise(() => {
		frappe.call({
			method: "cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_funding_pay_options",
			args: { funding_request: frm.doc.name },
			callback(r) {
				const orders = [
					...new Set(((r.message || {}).purchase || []).map((row) => row.existing_order).filter(Boolean)),
				];
				// Say why the user has landed on another document: the step is done
				// there, not on the request.
				const hint = () =>
					frappe.show_alert(
						{
							message: __("{0} is waiting on this Purchase Order. Complete it here.", [frm.doc.name]),
							indicator: "blue",
						},
						8
					);
				if (orders.length === 1) {
					frappe.set_route("Form", "Purchase Order", orders[0]).then(hint);
				} else if (orders.length) {
					frappe.set_route("List", "Purchase Order", { name: ["in", orders] }).then(hint);
				} else {
					frm.reload_doc();
				}
			},
		});
	});
}

function prepare_disbursement(frm, action) {
	// Disburse is a standard workflow action, and a workflow action takes no
	// input. So before Frappe applies it: ask which account each currency is paid
	// from, show exactly what will be created, and only let the action through on
	// a yes. Leaving either dialog leaves the request untouched.
	frappe.dom.unfreeze();
	return new Promise((resolve) => {
		frappe.call({
			method: "cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_funding_pay_options",
			args: { funding_request: frm.doc.name },
			callback(r) {
				const options = r.message || {};
				const operational = options.operational || [];
				const purchase = options.purchase || [];
				if (!operational.length && !purchase.length) {
					frappe.msgprint({
						title: __("Nothing to disburse"),
						indicator: "orange",
						message: __("Every approved row on this request is already paid."),
					});
					return;
				}
				// No Operational Expense row means no account to choose.
				if (!operational.length) {
					confirm_disbursement(frm, options, {}, resolve, action);
					return;
				}
				choose_payment_banks(frm, options, (bank_accounts) => {
					confirm_disbursement(frm, options, bank_accounts, resolve, action);
				});
			},
		});
	});
}

function confirm_disbursement(frm, options, bank_accounts, proceed, workflow_action) {
	// Disbursing posts to the ledger, so the person doing it is shown exactly what
	// will be created and has to agree. Nothing exists before that. A plain Yes/No
	// box said the same thing but read like a system prompt; this lays the
	// documents out as a list and names the button after what it does.
	const esc = frappe.utils.escape_html;
	const operational = options.operational || [];
	const purchase = options.purchase || [];
	const fresh_orders = purchase.filter((row) => !row.existing_order);
	const raised_orders = purchase.filter((row) => row.existing_order);

	// Opens in a new tab, so checking a document does not lose the dialog.
	const link = (doctype, name) =>
		`<a href="${frappe.utils.get_form_link(doctype, name)}" target="_blank" rel="noopener" style="color:${DISBURSE_BLUE};text-decoration:underline;">${esc(name)}</a>`;
	const cell = `padding:9px 12px;border-top:1px solid ${DISBURSE_BLUE_LINE};vertical-align:top;`;
	const head = `padding:7px 12px;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:${DISBURSE_BLUE_TEXT};text-align:left;`;
	const amount = (row) =>
		`<span style="white-space:nowrap;font-weight:600;color:${DISBURSE_BLUE_TEXT};">${esc(row.currency)} ${format_number(row.remaining, null, 2)}</span>`;
	const table = (rows, detail_label, detail) => `
		<table style="width:100%;border-collapse:collapse;font-size:13px;">
			<thead><tr>
				<th style="${head}">${__("Request")}</th>
				<th style="${head}">${detail_label}</th>
				<th style="${head}text-align:right;">${__("Amount")}</th>
			</tr></thead>
			<tbody>${rows
				.map(
					(row) => `<tr>
						<td style="${cell}font-weight:600;">${link("Material Request", row.material_request)}</td>
						<td style="${cell}">${detail(row)}</td>
						<td style="${cell}text-align:right;">${amount(row)}</td>
					</tr>`
				)
				.join("")}</tbody>
		</table>`;
	const section = (title, count, body, note) => `
		<div style="border:1px solid ${DISBURSE_BLUE_LINE};border-radius:10px;margin:0 0 12px;overflow:hidden;">
			<div style="padding:10px 12px;background:${DISBURSE_BLUE_SOFT};color:${DISBURSE_BLUE_TEXT};display:flex;justify-content:space-between;align-items:center;">
				<span style="font-weight:600;">${title}</span>
				<span style="font-size:12px;font-weight:600;background:${DISBURSE_BLUE};color:#fff;border-radius:999px;min-width:22px;text-align:center;padding:1px 7px;">${count}</span>
			</div>
			${body}
			${note ? `<div style="padding:9px 12px;border-top:1px solid ${DISBURSE_BLUE_LINE};font-size:12px;color:var(--text-muted);line-height:1.5;">${note}</div>` : ""}
		</div>`;

	let html = "";
	if (operational.length) {
		html += section(
			__("Journal Entries to create and submit"),
			operational.length,
			table(operational, __("Paid from"), (row) =>
				row.draft_entry
					? `${link("Journal Entry", row.draft_entry)} <span class="text-muted">(${__("existing draft")})</span>`
					: esc(bank_accounts[row.currency] || "")
			),
			__("Submitting posts each entry to the ledger and records the payment. To reverse it, the entry has to be cancelled.")
		);
	}
	if (fresh_orders.length) {
		html += section(
			__("Purchase Orders to create"),
			fresh_orders.length,
			table(fresh_orders, __("Created as"), () => __("Draft")),
			__("A Purchase Order pays nothing yet. The row is paid against the supplier's invoice, and the request stays in Disbursement in Progress until then.")
		);
	}
	if (raised_orders.length) {
		html += section(
			__("Purchase Orders already raised"),
			raised_orders.length,
			table(raised_orders, __("Purchase Order"), (row) => link("Purchase Order", row.existing_order))
		);
	}

	let action = __("Disburse");
	if (!operational.length) {
		action = fresh_orders.length
			? fresh_orders.length === 1
				? __("Create Purchase Order")
				: __("Create {0} Purchase Orders", [fresh_orders.length])
			: __("Continue");
	} else if (!purchase.length) {
		action =
			operational.length === 1
				? __("Submit Journal Entry")
				: __("Submit {0} Journal Entries", [operational.length]);
	}

	const d = new frappe.ui.Dialog({
		title: `${__(workflow_action || "Disburse")} ${frm.doc.name}`,
		fields: [{ fieldtype: "HTML", fieldname: "summary", options: html }],
		primary_action_label: action,
		primary_action() {
			d.get_primary_btn().prop("disabled", true);
			frappe.call({
				method: "cgm_shipping.cgm_worldwide_shipping.customizations.funding.set_disbursement_accounts",
				args: { funding_request: frm.doc.name, bank_accounts: JSON.stringify(bank_accounts) },
				callback(r) {
					if (r.exc) {
						d.get_primary_btn().prop("disabled", false);
						return;
					}
					d.hide();
					frm.__cgm_disbursing = true;
					frappe.dom.freeze(__("Disbursing..."));
					proceed();
				},
				error() {
					d.get_primary_btn().prop("disabled", false);
				},
			});
		},
		secondary_action_label: __("Go Back"),
		secondary_action() {
			d.hide();
		},
	});
	d.show();
	brand_dialog(d, DISBURSE_BLUE, DISBURSE_BLUE_DARK);
	d.$wrapper.find(".modal-header").css({
		background: DISBURSE_BLUE,
		"border-bottom-color": DISBURSE_BLUE,
	});
	d.$wrapper.find(".modal-title").css({ color: "#fff" });
	d.$wrapper.find(".modal-header .btn-modal-close, .modal-header .modal-actions .btn").css({ color: "#fff" });
	d.$wrapper.find(".modal-header svg").css({ stroke: "#fff" });
}

function show_last_disbursement(frm) {
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_last_disbursement",
		args: { funding_request: frm.doc.name },
		callback(r) {
			const created = r.message || {};
			const entries = created.journal_entries || [];
			const orders = created.purchase_orders || [];
			const existing = created.existing_purchase_orders || [];
			if (entries.length || orders.length || existing.length) {
				show_disbursed_documents(frm, entries, orders, existing);
			}
		},
	});
}

function show_disbursed_documents(frm, entries, orders, existing) {
	const esc = frappe.utils.escape_html;
	const links = (doctype, names) =>
		names.map((name) => `<li><a href="${frappe.utils.get_form_link(doctype, name)}">${esc(name)}</a></li>`).join("");
	let message = "";
	if (entries.length) {
		message += `<p>${__("{0} Journal Entry(s) submitted:", [entries.length])}</p><ul>${links("Journal Entry", entries)}</ul>`;
	}
	if (orders.length) {
		message += `<p>${__("{0} draft Purchase Order(s) created:", [orders.length])}</p><ul>${links("Purchase Order", orders)}</ul>`;
	}
	if (existing.length) {
		message += `<p>${__("{0} Purchase Order(s) already raised, now linked to this request. Continue there:", [existing.length])}</p><ul>${links("Purchase Order", existing)}</ul>`;
	}
	// One button, for the document Finance is most likely to open next.
	const doctype = entries.length ? "Journal Entry" : "Purchase Order";
	const names = entries.length ? entries : orders.concat(existing);
	frappe.msgprint({
		title: entries.length ? __("Disbursed") : __("Continue on the Purchase Order"),
		indicator: "green",
		message,
		primary_action: {
			label: names.length === 1 ? __("View {0}", [__(doctype)]) : __("View {0} list", [__(doctype)]),
			action() {
				frappe.hide_msgprint();
				if (names.length === 1) {
					frappe.set_route("Form", doctype, names[0]);
				} else {
					frappe.set_route("List", doctype, { custom_funding_request: frm.doc.name });
				}
			},
		},
	});
}
