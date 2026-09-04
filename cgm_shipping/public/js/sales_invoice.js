const CGM_SI_NAMING_SERIES = "INV-.MMYY.-.####";
const CGM_SI_CREDIT_NOTE_NAMING_SERIES = "CR-.MMYY.-.####";

const CGM_SI_DRAFT_STATE = "Draft";
const CGM_SI_PENDING_STATE = "Pending Approval";
const CGM_SI_APPROVED_STATE = "Approved";
const CGM_SI_ACTION_SUBMIT_FOR_REVIEW = "Submit for Review";
const CGM_SI_REJECTION_REASON_FIELD = "custom_rejection_reason";
const CGM_SI_REJECTED_BY_FIELD = "custom_rejected_by";

/** Sales Invoice field -> Project field for project-linked shipment refs. */
const CGM_SI_PROJECT_FETCH_MAP = {
	custom_cgm_reference_no: "custom_cgm_ref_no",
	custom_client_reference_no: "custom_client_refrence_no",
	custom_country_of_origin: "custom_country_of_origin",
};

frappe.ui.form.on("Sales Invoice", {
	setup(frm) {
		cgm_toggle_sales_invoice_project_name(frm);
		cgm_toggle_sales_invoice_project_fetched_fields(frm);
	},

	onload(frm) {
		cgm_toggle_sales_invoice_project_name(frm);
		cgm_toggle_sales_invoice_project_fetched_fields(frm);
		cgm_apply_sales_invoice_naming_series(frm);
		cgm_toggle_sales_invoice_share_fields(frm);
	},

	is_return(frm) {
		cgm_apply_sales_invoice_naming_series(frm);
	},

	refresh(frm) {
		cgm_toggle_sales_invoice_project_name(frm);
		cgm_toggle_sales_invoice_project_fetched_fields(frm);
		cgm_configure_sales_invoice_workflow_ui(frm);
		cgm_configure_sales_invoice_customer_share_ui(frm);
	},

	project(frm) {
		cgm_toggle_sales_invoice_project_name(frm);
		cgm_sync_sales_invoice_fields_from_project(frm);
		cgm_toggle_sales_invoice_project_fetched_fields(frm);
	},

	validate(frm) {
		cgm_validate_sales_invoice_project_reference(frm);
	},

	after_workflow_action(frm) {
		frappe.after_ajax(() => {
			cgm_configure_sales_invoice_workflow_ui(frm);
			cgm_configure_sales_invoice_customer_share_ui(frm);
		});
	},

	before_workflow_action(frm) {
		if (frm.selected_workflow_action === "Reject") {
			return cgm_prompt_sales_invoice_rejection_reason(frm);
		}
	},

	custom_share_with_customer(frm) {
		cgm_toggle_sales_invoice_share_fields(frm);
	},
});

function cgm_apply_sales_invoice_naming_series(frm) {
	if (frm.doc.docstatus !== 0 || frm.doc.amended_from || !frm.fields_dict.naming_series) {
		return;
	}
	const series = frm.doc.is_return
		? CGM_SI_CREDIT_NOTE_NAMING_SERIES
		: CGM_SI_NAMING_SERIES;
	if (frm.doc.naming_series !== series) {
		frm.set_value("naming_series", series);
	}
}

function cgm_get_sales_invoice_project_fetch_fields() {
	return Object.keys(CGM_SI_PROJECT_FETCH_MAP);
}

function cgm_toggle_sales_invoice_project_name(frm) {
	if (!frm.fields_dict.custom_project_name) {
		return;
	}

	const has_project = Boolean(cstr(frm.doc.project).trim());
	// Use display toggle only. Do not set df.hidden or depends_on —
	// those conflict and can leave the field stuck visible.
	frm.toggle_display("custom_project_name", !has_project);
}

function cgm_toggle_sales_invoice_project_fetched_fields(frm) {
	const has_project = Boolean(cstr(frm.doc.project).trim());
	for (const fieldname of cgm_get_sales_invoice_project_fetch_fields()) {
		if (!frm.fields_dict[fieldname]) {
			continue;
		}
		frm.set_df_property(fieldname, "read_only", has_project ? 1 : 0);
	}
}

function cgm_sync_sales_invoice_fields_from_project(frm) {
	const project = cstr(frm.doc.project).trim();
	const si_fields = cgm_get_sales_invoice_project_fetch_fields();

	if (!project) {
		for (const fieldname of si_fields) {
			if (frm.fields_dict[fieldname]) {
				frm.set_value(fieldname, "");
			}
		}
		return;
	}

	const project_fields = Object.values(CGM_SI_PROJECT_FETCH_MAP);
	frappe.db.get_value("Project", project, project_fields).then((r) => {
		if (!r || !r.message) {
			return;
		}
		// Guard against stale async response after project was cleared/changed.
		if (cstr(frm.doc.project).trim() !== project) {
			return;
		}
		const values = r.message;
		for (const [si_field, project_field] of Object.entries(CGM_SI_PROJECT_FETCH_MAP)) {
			if (!frm.fields_dict[si_field]) {
				continue;
			}
			frm.set_value(si_field, values[project_field] || "");
		}
	});
}

function cgm_validate_sales_invoice_project_reference(frm) {
	const project = cstr(frm.doc.project).trim();
	const project_name = cstr(frm.doc.custom_project_name).trim();
	if (!project && !project_name) {
		frappe.throw(__("Please select a Project or enter a Project Name."));
	}
}

function cgm_set_sales_invoice_workflow_alert(frm, text, tone = "brand") {
	frm.dashboard.clear_headline();
	if (!text) {
		return;
	}

	const styles = {
		brand:
			"background:linear-gradient(135deg, #fff8f9 0%, #ffebef 55%, #fff4f6 100%);border:1px solid rgba(227, 24, 55, 0.2);color:#b8122c;",
		info: "background:#eff6ff;border:1px solid #bfdbfe;color:#1d4ed8;",
		danger: "background:#fff1f2;border:1px solid #fecdd3;color:#b8122c;",
		success: "background:#ecfdf5;border:1px solid #bbf7d0;color:#15803d;",
	};

	frm.dashboard.set_headline(
		`<div class="cgm-si-workflow-alert" style="${styles[tone] || styles.brand}padding:10px 12px;border-radius:6px;font-size:12px;font-weight:500;line-height:1.45;">${frappe.utils.escape_html(
			text
		)}</div>`,
		"white",
		true
	);
}

function cgm_sales_invoice_status_tone(status) {
	const value = (status || "").trim();
	if (value === "Paid") {
		return "green";
	}
	if (value.includes("Overdue")) {
		return "red";
	}
	if (["Unpaid", "Partly Paid", "Submitted"].includes(value)) {
		return "orange";
	}
	return "blue";
}

function cgm_configure_sales_invoice_workflow_ui(frm) {
	if (!frm.fields_dict.workflow_state) {
		return;
	}

	if (frm.doc.docstatus === 1) {
		const payment_status = (frm.doc.status || "").trim();
		const approval_state = (frm.doc.workflow_state || CGM_SI_APPROVED_STATE).trim();
		if (payment_status) {
			frm.page.set_indicator(payment_status, cgm_sales_invoice_status_tone(payment_status));
		}
		if (frm.fields_dict.workflow_state) {
			frm.toggle_display("workflow_state", true);
		}
		cgm_set_sales_invoice_workflow_alert(
			frm,
			__("Approval status: {0}", [approval_state]),
			approval_state === CGM_SI_APPROVED_STATE ? "success" : "info"
		);
		cgm_add_sales_invoice_payment_button(frm);
		return;
	}

	if (frm.fields_dict.workflow_state) {
		frm.toggle_display("workflow_state", true);
	}

	if (frm.doc.docstatus === 2) {
		frm.dashboard.clear_headline();
		return;
	}

	const state = frm.doc.workflow_state || CGM_SI_DRAFT_STATE;
	frm.page.set_primary_action(__("Save"), () => frm.save());

	if (state === CGM_SI_APPROVED_STATE) {
		cgm_set_sales_invoice_workflow_alert(
			frm,
			__(
				"This invoice is approved but not submitted yet. Save or use Actions → Approve again — it will submit and show as Unpaid for the customer."
			),
			"danger"
		);
	} else if (state === CGM_SI_PENDING_STATE) {
		cgm_set_sales_invoice_workflow_alert(
			frm,
			__(
				"Pending manager approval. The invoice is locked for editing by the preparer until approved or rejected."
			),
			"info"
		);
	} else if (state === CGM_SI_DRAFT_STATE && frm.doc[CGM_SI_REJECTED_BY_FIELD]) {
		cgm_set_sales_invoice_workflow_alert(
			frm,
			__(
				"Returned to Draft after rejection. Correct the invoice, then use Actions → {0}.",
				[CGM_SI_ACTION_SUBMIT_FOR_REVIEW]
			),
			"danger"
		);
	} else if (state === CGM_SI_DRAFT_STATE) {
		cgm_set_sales_invoice_workflow_alert(
			frm,
			__("Save the invoice, then use Actions → {0}.", [CGM_SI_ACTION_SUBMIT_FOR_REVIEW]),
			"brand"
		);
	} else {
		frm.dashboard.clear_headline();
	}
}

function cgm_add_sales_invoice_payment_button(frm) {
	if (
		frm.doc.docstatus !== 1 ||
		!flt(frm.doc.outstanding_amount) ||
		!frappe.model.can_create("Payment Entry")
	) {
		return;
	}

	const label = __("Payment");
	if (frm.custom_buttons?.[label]) {
		return;
	}

	frm.add_custom_button(label, () => cgm_open_sales_invoice_payment_entry(frm), __("Create"));
	frm.page.set_inner_btn_group_as_primary(__("Create"));
}

function cgm_open_sales_invoice_payment_entry(frm) {
	if (typeof frm.cscript?.make_payment_entry === "function") {
		frm.cscript.make_payment_entry();
		return;
	}

	const method =
		frm.doc.__onload?.make_payment_via_journal_entry &&
		["Sales Invoice", "Purchase Invoice"].includes(frm.doc.doctype)
			? "erpnext.accounts.doctype.journal_entry.journal_entry.get_payment_entry_against_invoice"
			: "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry";

	frappe.call({
		method,
		args: {
			dt: frm.doc.doctype,
			dn: frm.doc.name,
		},
		callback(r) {
			if (!r.message) {
				return;
			}
			const doclist = frappe.model.sync(r.message);
			frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
		},
	});
}

function cgm_prompt_sales_invoice_rejection_reason(frm) {
	// Workflow freezes the page before before_workflow_action runs.
	// Unfreeze so the rejection dialog is readable.
	frappe.dom.unfreeze();

	return new Promise((resolve, reject) => {
		let settled = false;
		const settle = (fn) => {
			if (settled) {
				return;
			}
			settled = true;
			fn();
		};

		const dialog = new frappe.ui.Dialog({
			title: __("Reject Sales Invoice"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "rejection_help",
					options: `<p class="text-muted" style="margin:0 0 8px;">
						${frappe.utils.escape_html(
							__(
								"Enter why this invoice is being rejected. The creator can update it and send it for review again."
							)
						)}
					</p>`,
				},
				{
					fieldname: CGM_SI_REJECTION_REASON_FIELD,
					fieldtype: "Small Text",
					label: __("Rejection Reason"),
					reqd: 1,
				},
			],
			primary_action_label: __("Reject"),
			primary_action(values) {
				const reason = (values[CGM_SI_REJECTION_REASON_FIELD] || "").trim();
				if (!reason) {
					frappe.msgprint(__("Please enter a Rejection Reason."));
					return;
				}

				// Persist before workflow apply — set_value alone is lost on reload.
				frappe.call({
					method: "frappe.client.set_value",
					args: {
						doctype: frm.doctype,
						name: frm.doc.name,
						fieldname: CGM_SI_REJECTION_REASON_FIELD,
						value: reason,
					},
					callback(r) {
						if (r.exc) {
							settle(() => {
								frm.selected_workflow_action = null;
								reject();
							});
							return;
						}
						frm.doc[CGM_SI_REJECTION_REASON_FIELD] = reason;
						settle(() => {
							dialog.hide();
							frappe.dom.freeze();
							resolve();
						});
					},
					error() {
						settle(() => {
							frm.selected_workflow_action = null;
							reject();
						});
					},
				});
			},
			secondary_action_label: __("Cancel"),
			secondary_action() {
				settle(() => {
					frm.selected_workflow_action = null;
					dialog.hide();
					reject();
				});
			},
		});

		dialog.$wrapper.on("hidden.bs.modal", () => {
			settle(() => {
				frm.selected_workflow_action = null;
				reject();
			});
		});

		dialog.show();
		dialog.get_primary_btn().addClass("btn-danger");
	});
}

function cgm_toggle_sales_invoice_share_fields(frm) {
	if (!frm.fields_dict.custom_shared_with_customer_on) {
		return;
	}
	frm.toggle_display(
		"custom_shared_with_customer_on",
		cint(frm.doc.custom_share_with_customer)
	);
}

function cgm_configure_sales_invoice_customer_share_ui(frm) {
	if (!frm.fields_dict.custom_share_with_customer) {
		return;
	}
	cgm_toggle_sales_invoice_share_fields(frm);
	if (frm.doc.docstatus !== 1 || frm.doc.is_return) {
		return;
	}
	if (cint(frm.doc.custom_share_with_customer)) {
		return;
	}

	frm.add_custom_button(__("Share with Customer"), () => {
		frappe.confirm(
			__(
				"Share this invoice on the customer portal? They will see that they owe {0}. When you record payment, they will see it as Paid.",
				[format_currency(frm.doc.outstanding_amount || frm.doc.grand_total, frm.doc.currency)]
			),
			() => cgm_share_sales_invoice_with_customer(frm)
		);
	}, __("CGM"));
}

function cgm_share_sales_invoice_with_customer(frm) {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.customer_invoice_share.share_sales_invoice_with_customer",
		args: { sales_invoice: frm.doc.name },
		freeze: true,
		freeze_message: __("Sharing with customer…"),
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			frappe.show_alert({
				message: __("Invoice shared. The customer can now see it on their portal."),
				indicator: "green",
			});
			frm.reload_doc();
		},
	});
}
