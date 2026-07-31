const CGM_SI_APPROVED_STATE = "Approved";

frappe.ui.form.on("Sales Invoice", {
	setup(frm) {
		cgm_toggle_sales_invoice_project_name(frm);
	},

	onload(frm) {
		cgm_toggle_sales_invoice_project_name(frm);
	},

	refresh(frm) {
		cgm_toggle_sales_invoice_project_name(frm);
		cgm_configure_sales_invoice_workflow_ui(frm);
	},

	project(frm) {
		cgm_toggle_sales_invoice_project_name(frm);
	},

	validate(frm) {
		cgm_validate_sales_invoice_project_reference(frm);
	},

	after_workflow_action(frm) {
		frappe.after_ajax(() => cgm_configure_sales_invoice_workflow_ui(frm));
	},

	before_workflow_action(frm) {
		if (frm.selected_workflow_action === "Reject") {
			return cgm_prompt_sales_invoice_rejection_reason(frm);
		}
	},
});

function cgm_toggle_sales_invoice_project_name(frm) {
	if (!frm.fields_dict.custom_project_name) {
		return;
	}

	const has_project = Boolean(cstr(frm.doc.project).trim());
	// Use display toggle only. Do not set df.hidden or depends_on —
	// those conflict and can leave the field stuck visible.
	frm.toggle_display("custom_project_name", !has_project);
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

function cgm_configure_sales_invoice_workflow_ui(frm) {
	if (!frm.fields_dict.workflow_state) {
		return;
	}

	if (frm.doc.docstatus === 1) {
		frm.dashboard.clear_headline();
		cgm_add_sales_invoice_payment_button(frm);
		return;
	}

	if (frm.doc.docstatus !== 0) {
		return;
	}

	const state = frm.doc.workflow_state || "Draft";
	const can_submit =
		state === CGM_SI_APPROVED_STATE &&
		!frm.doc.__islocal &&
		!frm.is_dirty() &&
		cint(frm.perm?.[0]?.submit);

	if (can_submit) {
		frm.page.set_primary_action(__("Submit"), () => frm.savesubmit());
	} else {
		frm.page.set_primary_action(__("Save"), () => frm.save());
	}

	if (state === "Pending Finance Approval") {
		cgm_set_sales_invoice_workflow_alert(
			frm,
			__("Waiting for Finance to approve or reject this invoice."),
			"info"
		);
	} else if (state === "Rejected") {
		cgm_set_sales_invoice_workflow_alert(
			frm,
			__(
				"Finance rejected this invoice. Update it, use Return to Draft, or submit again for approval."
			),
			"danger"
		);
	} else if (state === "Draft") {
		cgm_set_sales_invoice_workflow_alert(
			frm,
			__("Save the invoice, then use Actions → Submit for Finance Approval."),
			"brand"
		);
	} else if (state === CGM_SI_APPROVED_STATE) {
		cgm_set_sales_invoice_workflow_alert(
			frm,
			__("Finance approved this invoice. You can now Submit it."),
			"success"
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
	return new Promise((resolve) => {
		const dialog = new frappe.ui.Dialog({
			title: __("Reject Sales Invoice"),
			fields: [
				{
					fieldname: "custom_finance_rejection_reason",
					fieldtype: "Small Text",
					label: __("Rejection Reason"),
					reqd: 1,
				},
			],
			primary_action_label: __("Reject"),
			primary_action(values) {
				frm.set_value(
					"custom_finance_rejection_reason",
					values.custom_finance_rejection_reason
				);
				dialog.hide();
				resolve();
			},
		});
		dialog.show();
	});
}
