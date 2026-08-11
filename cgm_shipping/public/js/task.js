const LEGACY_INVOICE_DOCUMENT_TYPES = new Set([
	"UCR Invoice",
	"UCR_DOC",
	"UCR_INV",
	"SUP_INV",
	"Supplier Invoice",
]);

const CGM_ACTION_GROUP = __("Actions");

const UCR_LEGACY_FIELDNAMES = [
	"custom_section_ucr_payment",
	"custom_ucr_invoice_verified",
	"custom_ucr_payment_receipt",
	"custom_ucr_receipt_verified",
];

function showWorkflowNotifyResult(r, fallbackMessage) {
	if (r.exc) {
		return;
	}
	const data = r.message || {};
	const text = data.message || fallbackMessage || __("Notification sent");
	const indicator = data.emails_sent ? "green" : data.email_error ? "orange" : "blue";
	frappe.show_alert({ message: text, indicator });
}

function strip_legacy_invoice_clearance_rows(frm) {
	const rows = frm.doc.custom_task_documents || [];
	const filtered = rows.filter((row) => !LEGACY_INVOICE_DOCUMENT_TYPES.has(row.document_type));
	if (filtered.length !== rows.length) {
		frm.doc.custom_task_documents = filtered;
	}
}

frappe.ui.form.on("Task", {
	onload(frm) {
		frm.__loaded_status = frm.doc.status;
		if (
			localStorage.getItem("cgm_pe_for_task") !== "1" &&
			localStorage.getItem("cgm_pi_for_task") !== "1"
		) {
			localStorage.removeItem("cgm_return_task");
		}
		reset_cgm_task_sea_ui_state_if_needed(frm);
		frm._cgm_declarant_status = null;
		frm._cgm_declarant_status_loading = false;
		frm._cgm_declarant_status_loaded = false;
		frm._cgm_entry_declarant_status = null;
		frm._cgm_entry_declarant_status_loading = false;
		frm._cgm_entry_declarant_status_loaded = false;
		frm._cgm_shipping_line_declarant_status = null;
		frm._cgm_shipping_line_declarant_status_loading = false;
		frm._cgm_shipping_line_declarant_status_loaded = false;
		frm._cgm_kpa_declarant_status = null;
		frm._cgm_kpa_declarant_status_loading = false;
		frm._cgm_kpa_declarant_status_loaded = false;
		frm._cgm_finance_lines_ensuring = false;
		frm._cgm_checkpoint_seed_requested = false;
		frm.set_query("department", () => ({
			filters: { parent_department: ["like", "Operations%"] },
		}));
		ensure_cgm_finance_department_loaded(frm);
	},

	before_save(frm) {
		strip_legacy_invoice_clearance_rows(frm);
	},

	refresh(frm) {
		reset_cgm_task_sea_ui_state_if_needed(frm);
		ensure_cgm_finance_department_loaded(frm);
		const ui = get_sea_task_ui(frm);

		// Layout + grid config once per form load (re-running on every refresh closes Action menus).
		// Wait until the async sea-sequence config has loaded, otherwise the layout
		// runs against the empty config and leaves finance lines / permits hidden.
		if (!frm._cgm_sea_layout_ready && (!is_sea_clearance_task(frm) || frm._cgm_sea_seq_config)) {
			apply_sea_task_form_layout(frm, ui);
			frm._cgm_sea_layout_ready = true;
		}
		if (ui.show_permits) {
			configure_permit_grid(frm);
		}
		cgm_configure_task_status_fields(frm);
		// Status-grid badge wiring once per form — re-running on every refresh
		// schedules multi-paint timeouts and makes Attach/Clear flicker.
		if (!frm._cgm_status_grids_ready) {
			cgm_configure_document_status_grids(frm);
			cgm_configure_permit_status_grids(frm);
			frm._cgm_status_grids_ready = true;
		}
		if (frm.fields_dict.custom_journal_entry) {
			// Per-row JE on Invoices & Receipts / Permits is the source of truth.
			frm.set_df_property(
				"custom_journal_entry",
				"hidden",
				is_sea_clearance_task(frm) ? 1 : 0
			);
		}
		configure_client_paid_field(frm, ui);
		if (ui.show_documents) {
			configure_task_document_version_grid(frm, ui);
		}

		frm.set_df_property("status", "read_only", 1);
		const show_completion_meta = frm.doc.status === "Completed";
		frm.set_df_property("completed_by", "read_only", 1);
		frm.set_df_property("completed_on", "read_only", 1);
		frm.set_df_property("completed_by", "hidden", show_completion_meta ? 0 : 1);
		frm.set_df_property("completed_on", "hidden", show_completion_meta ? 0 : 1);

		if (ui.auto_intake_intro) {
			set_task_intro(
				frm,
				__(
					"Completed automatically at Project creation. Documents were copied from the Project file (approved on Lead/Opportunity)."
				)
			);
		} else if (ui.is_sea_task && frm.doc.project) {
			let intro = __(
				"Use <b>Invoices & Receipts</b> for supplier invoices and payment proofs. " +
					"<b>Clearance Documents</b> for IDF/UCR certificates and customs papers (synced to Project)."
			);
			let intro_set = false;
			if (ui.show_permits) {
				const seq = sea_task_sequence(frm);
				if (is_permit_finance_step(frm, seq)) {
					if (frm.doc.custom_client_paid_directly) {
						intro = __(
							"<b>Client will pay</b> is selected — no company Journal Entry. " +
								"<b>1</b> Verify invoices · <b>2</b> <b>Share Invoice with Client</b> (optional). " +
								"Receipt attachment is optional. Both tasks complete when invoices are verified " +
								"(and certificates are attached on the application task)."
						);
					} else {
						const appLabel = permit_application_task_label(
							frm,
							get_paired_permit_application_seq(frm, seq)
						);
						intro = __(
							"<b>1 Finance:</b> Verify permit invoices (tick <b>Invoice Verified</b> or <b>Verify Invoices</b>) · " +
								"<b>2</b> Use <b>Make Payment</b> on each permit row (or tick <b>Client will pay</b>) · " +
								"<b>3</b> Receipt attachment is optional. Both tasks complete after payment. " +
								"Declarant attaches certificates on <b>{0}</b>.",
							[appLabel]
						);
					}
				} else if (frm.doc.custom_client_paid_directly) {
					intro = __(
						"<b>Finance selected: Client will pay</b> (no company Journal Entry). " +
							"Attach invoices as usual; Finance verifies. After the client pays, upload their receipt " +
							"on the finance task (same department that attached the invoices). " +
							"Attach <b>Permit Certificate</b> on each row; this task completes when receipts and certificates are in."
					);
				} else if (frm.doc.custom_permit_invoices_submitted) {
					const finLabel = permit_finance_task_label(
						frm,
						get_paired_permit_finance_seq(frm, seq)
					);
					intro = __(
						"<b>After invoices go to Finance:</b> Finance verifies invoices and pays on <b>{0}</b>. " +
							"Then upload payment receipts on that finance task (same department that attached the invoices). " +
							"Attach <b>Permit Certificate</b> on each row; this task completes when receipts and certificates are in. " +
							"You can still add more permits later — Finance will reopen to verify and pay.",
						[finLabel]
					);
				} else {
					intro = __(
						"<b>Declaration:</b> Attach <b>Permit Invoice (for Finance)</b> on every permit row and save - " +
							"Finance is notified automatically when all invoices are attached."
					);
				}
			} else if (ui.is_ucr_application) {
				if (frm._cgm_declarant_status_loaded && frm._cgm_declarant_status) {
					apply_ucr_application_intro(frm, frm._cgm_declarant_status);
					intro_set = true;
				}
			} else if (ui.is_entry_application) {
				if (frm._cgm_entry_declarant_status_loaded && frm._cgm_entry_declarant_status) {
					apply_entry_application_intro(frm, frm._cgm_entry_declarant_status);
					intro_set = true;
				}
			} else if (ui.is_shipping_line_application) {
				if (
					frm._cgm_shipping_line_declarant_status_loaded &&
					frm._cgm_shipping_line_declarant_status
				) {
					apply_app_finance_application_intro(frm, frm._cgm_shipping_line_declarant_status, "shipping_line");
					intro_set = true;
				}
			} else if (ui.is_kpa_application) {
				if (frm._cgm_kpa_declarant_status_loaded && frm._cgm_kpa_declarant_status) {
					apply_app_finance_application_intro(frm, frm._cgm_kpa_declarant_status, "kpa");
					intro_set = true;
				}
			} else if (ui.is_ucr_finance) {
				intro = form_has_client_paid_invoice_line(frm)
					? __(
							"<b>Client will pay</b> on one or more invoice rows — no company Journal Entry for those. " +
								"<b>1</b> Verify invoices · <b>2</b> <b>Share Invoice with Client</b> (optional) · " +
								"<b>3</b> Attach <b>UCR Receipt</b> · <b>4</b> Verify the receipt. " +
								"Task completes only after the receipt is verified. " +
								"Declarant attaches the IDF certificate on <b>Create UCR (IDF)</b>."
						)
					: __(
							"<b>1 Finance:</b> Verify each <b>UCR Invoice</b> · " +
								"<b>2</b> Use <b>Actions → Make Payment</b> (or tick <b>Client will pay</b> on the invoice row) · " +
								"<b>3</b> Attach <b>UCR Receipt</b> · <b>4</b> Verify the receipt. " +
								"Task completes only after the receipt is verified. " +
								"Declarant attaches the IDF certificate on <b>Create UCR (IDF)</b>."
						);
				intro_set = true;
			} else if (ui.is_entry_finance) {
				const inv = get_finance_line(frm, "Invoice");
				const clientReported = cint(inv?.client_reported_paid);
				intro = form_has_client_paid_invoice_line(frm)
					? __(
							"<b>Client will pay</b> on one or more invoice rows — no company Journal Entry for those. " +
								"<b>1</b> Verify <b>Entry Slip Invoice</b> (Create Entry completes on verify) · " +
								"<b>2</b> <b>Share Invoice with Client</b> (optional). " +
								"<b>Entry Slip Receipt</b> is optional."
						)
					: __(
							"<b>1 Finance:</b> Verify <b>Entry Slip Invoice</b> (Create Entry completes on verify) · " +
								"<b>2</b> Use <b>Actions → Make Payment</b> (or tick <b>Client will pay</b> on the invoice row). " +
								"This finance task completes after payment — <b>Entry Slip Receipt</b> is optional."
						);
				if (clientReported) {
					intro +=
						" " +
						__(
							"<b>Client reported paid</b> on the portal — check <b>Client Reported Paid</b> on the invoice row; receipt may still be attached."
						);
				}
				intro_set = true;
			} else if (ui.is_shipping_line_finance) {
				intro = form_has_client_paid_invoice_line(frm)
					? __(
							"<b>Client will pay</b> on one or more invoice rows — no company Journal Entry for those. " +
								"<b>1</b> Verify invoices · <b>2</b> <b>Share Invoice with Client</b>. " +
								"<b>3</b> Client uploads <b>POP</b> on the portal (or Finance attaches it). " +
								"<b>4</b> Documentation attaches the <b>Shipping Line Receipt</b> using the POP. " +
								"<b>5</b> Finance verifies the receipt — then this task completes."
						)
					: __(
							"<b>1 Finance:</b> Verify <b>Shipping Line Invoice</b> · " +
								"<b>2</b> Use <b>Actions → Make Payment</b> (or tick <b>Client will pay</b> on the invoice row). " +
								"<b>3</b> Attach bank <b>POP</b> (or client shares POP via portal). " +
								"<b>4</b> Documentation attaches the <b>Shipping Line Receipt</b> using the POP. " +
								"<b>5</b> Finance verifies the receipt — then this task completes."
						);
				intro_set = true;
			} else if (ui.is_kpa_finance) {
				intro = form_has_client_paid_invoice_line(frm)
					? __(
							"<b>Client will pay</b> on one or more invoice rows — no company Journal Entry for those. " +
								"<b>1</b> Verify invoices · <b>2</b> <b>Share Invoice with Client</b> (optional) · " +
								"<b>3</b> Attach <b>KPA Receipt</b> · <b>4</b> Verify the receipt. " +
								"Task completes only after the receipt is verified."
						)
					: __(
							"<b>1 Finance:</b> Verify <b>KPA Invoice</b> · " +
								"<b>2</b> Use <b>Actions → Make Payment</b> (or tick <b>Client will pay</b> on the invoice row) · " +
								"<b>3</b> Attach <b>KPA Receipt</b> · <b>4</b> Verify the receipt. " +
								"Task completes only after the receipt is verified."
						);
				intro_set = true;
			} else if (ui.is_document_checkpoint) {
				intro = __(
					"<b>Initial documents</b> were copied from the Project (read-only). " +
						"Attach each <b>Final Document</b> here — finals sync to the Project when you save."
				);
				intro_set = true;
			} else if (ui.show_payments) {
				intro = __(
					"Use <b>Make Payment</b> to record a Journal Entry, or tick <b>Client will pay</b> " +
						"if the client settles this fee — then verify the invoice and upload their receipt (no JE)."
				);
			}
			if (!intro_set) {
				set_task_intro(frm, intro);
			}
		}

		if (ui.is_ucr_application && frm.doc.project) {
			ensure_ucr_finance_lines_on_form(frm);
			if (!frm._cgm_declarant_status_loaded) {
				load_ucr_declarant_workflow_status(frm);
			}
		}

		if (ui.is_entry_application && frm.doc.project) {
			ensure_entry_finance_lines_on_form(frm);
			if (!frm._cgm_entry_declarant_status_loaded) {
				load_entry_declarant_workflow_status(frm);
			}
			configure_entry_arrival_mirror_grid(frm);
		}

		if (ui.is_shipping_line_application && frm.doc.project) {
			ensure_app_finance_lines_on_form(frm, "shipping_line");
			configure_shipping_line_deposit_grid(frm);
			if (!frm._cgm_shipping_line_declarant_status_loaded) {
				load_app_finance_declarant_status(frm, "shipping_line");
			}
		}

		if (ui.is_kpa_application && frm.doc.project) {
			ensure_app_finance_lines_on_form(frm, "kpa");
			if (!frm._cgm_kpa_declarant_status_loaded) {
				load_app_finance_declarant_status(frm, "kpa");
			}
		}

		if (ui.is_ucr_finance && frm.doc.status !== "Completed") {
			ensure_ucr_finance_task_completed_on_form(frm);
		}

		if (ui.is_entry_finance && frm.doc.status !== "Completed") {
			ensure_entry_finance_task_completed_on_form(frm);
		}

		if (ui.is_shipping_line_finance && frm.doc.status !== "Completed") {
			ensure_app_finance_lines_on_form(frm, "shipping_line");
			ensure_app_finance_task_completed_on_form(frm, "shipping_line");
		}

		if (ui.is_kpa_finance && frm.doc.status !== "Completed") {
			sync_app_finance_receipt_on_form(frm, "kpa");
			ensure_app_finance_task_completed_on_form(frm, "kpa");
		}

	if (ui.show_permits && is_permit_finance_step(frm) && frm.doc.project) {
		ensure_finance_permit_rows_on_form(frm);
	}

	if (
		ui.show_permits &&
		is_permit_finance_step(frm) &&
		frm.doc.status === "Completed" &&
		!frm.is_new()
	) {
		ensure_permit_finance_reopened_for_pending(frm);
	}

	if (ui.show_permits && is_permit_finance_step(frm) && frm.doc.status !== "Completed") {
		ensure_finance_permit_task_completed_on_form(frm);
	}

		if (ui.is_document_checkpoint && frm.doc.name && !frm.is_new()) {
			ensure_checkpoint_task_documents_on_form(frm);
		}

		schedule_cgm_task_toolbar_buttons(frm);
		if (is_sea_clearance_task(frm) && !frm._cgm_sea_seq_config && !frm._cgm_sea_seq_loading) {
			load_cgm_sea_ui_sequences(frm);
		}
	},

	validate(frm) {
		if (frm.doc.status === "Completed") {
			if (!frm.doc.completed_by) {
				frm.set_value("completed_by", frappe.session.user);
			}
			if (!frm.doc.completed_on) {
				frm.set_value("completed_on", frappe.datetime.now_datetime());
			}
		}
	},

	after_save(frm) {
		const just_completed = frm.doc.status === "Completed" && frm.__loaded_status !== "Completed";
		frm.__loaded_status = frm.doc.status;

		if (!just_completed) {
			return;
		}
		open_next_task_prompt(frm);
	},

	custom_client_paid_directly(frm) {
		// Share Invoice with Client only shows on the client-pays path.
		schedule_cgm_task_toolbar_buttons(frm);
	},
});

const SEA_FLOW_KEY = "SEA_IMPORT_E2E";
const SEA_IMPORT_TEMPLATE = "Sea Import Workflow";
const SEA_FLOW_KEYS_EXPR = "['SEA_IMPORT_E2E','Sea Import Workflow'].includes(doc.custom_task_flow_key)";

function isSeaImportFlowKey(flowKey) {
	const key = (flowKey || "").trim();
	return key === SEA_FLOW_KEY || key === SEA_IMPORT_TEMPLATE;
}

function get_task_flow_key(frm) {
	return (frm.doc.custom_task_flow_key || "").trim();
}

/** Empty shell until get_sea_task_ui_sequences returns (no hardcoded business rules). */
const CGM_SEA_UI_SEQUENCES_EMPTY = {
	payment_seqs: [],
	auto_complete_seqs: [],
	permit_application_seqs: [],
	light_proof_seqs: [],
	ucr_application_seqs: [],
	entry_application_seqs: [],
	shipping_line_application_seqs: [],
	kpa_application_seqs: [],
	finance_document_seqs: [],
	permit_finance_seqs: [],
	ucr_finance_seqs: [],
	entry_finance_seqs: [],
	shipping_line_finance_seqs: [],
	kpa_finance_seqs: [],
	permit_stage_by_seq: {},
	permissions: {},
};

function sea_task_permits_depends_on(frm) {
	const cfg = get_cgm_sea_seq_config(frm);
	const seqs = [
		...new Set([
			...(cfg.permit_application_seqs || []),
			...(cfg.permit_finance_seqs || []),
		]),
	].sort((a, b) => a - b);
	if (!seqs.length) {
		return `eval:${SEA_FLOW_KEYS_EXPR}`;
	}
	return `eval:${SEA_FLOW_KEYS_EXPR} && [${seqs.join(",")}].includes(doc.custom_sequence_no)`;
}

const CGM_TASK_PERMISSIONS_FALLBACK = {
	can_make_payment: ["Finance Manager", "Finance User", "Accounts User", "Accounts Manager"],
	can_upload_receipt: [
		"Finance Manager",
		"Finance User",
		"Accounts User",
		"Accounts Manager",
		"System Manager",
		"CGM Documentation",
		"Documentation",
	],
	can_upload_pop: [
		"Finance Manager",
		"Finance User",
		"Accounts User",
		"Accounts Manager",
		"System Manager",
	],
	can_verify_invoice: ["Finance Manager", "Finance User", "Accounts User", "Accounts Manager"],
	can_upload_invoice: [
		"Declaration User",
		"Declarant",
		"Operations Manager",
		"Operations User",
		"System Manager",
		"CGM Documentation",
		"Documentation",
	],
	can_upload_certificate: [
		"Declaration User",
		"Declarant",
		"Operations Manager",
		"Operations User",
		"System Manager",
	],
	can_confirm_client_paid: ["Finance Manager", "Finance User", "Accounts User", "Accounts Manager"],
	can_upload_document: [
		"Declaration User",
		"Declarant",
		"Operations Manager",
		"Operations User",
		"System Manager",
	],
	can_record_purchase_invoice: [
		"Finance Manager",
		"Finance User",
		"Accounts User",
		"Accounts Manager",
		"Purchase Manager",
		"Purchase User",
	],
};

// Desk-session cache: sequence lists are settings, not per-task. Avoid re-hitting
// get_sea_task_ui_sequences on every Task open (that endpoint walks CGM Settings).
let CGM_SEA_UI_SEQUENCES_CACHE = null;

function apply_cached_sea_ui_sequences(frm, config) {
	frm._cgm_sea_seq_config = config;
	frm._cgm_finance_department = config?.finance_department || null;
	frm._cgm_sea_seq_load_failed = false;
	frm._cgm_sea_layout_ready = false;
	frm._cgm_finance_grid_ready = false;
	frm.trigger("refresh");
}

function load_cgm_sea_ui_sequences(frm) {
	if (!is_sea_clearance_task(frm) || frm._cgm_sea_seq_loading) {
		return;
	}
	if (frm._cgm_sea_seq_config && !frm._cgm_sea_seq_load_failed) {
		return;
	}
	if (CGM_SEA_UI_SEQUENCES_CACHE) {
		apply_cached_sea_ui_sequences(frm, CGM_SEA_UI_SEQUENCES_CACHE);
		return;
	}
	frm._cgm_sea_seq_loading = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.task.get_sea_task_ui_sequences",
		callback(r) {
			frm._cgm_sea_seq_loading = false;
			CGM_SEA_UI_SEQUENCES_CACHE = r.message || CGM_SEA_UI_SEQUENCES_EMPTY;
			apply_cached_sea_ui_sequences(frm, CGM_SEA_UI_SEQUENCES_CACHE);
		},
		error() {
			frm._cgm_sea_seq_loading = false;
			frm._cgm_sea_seq_load_failed = true;
			frappe.msgprint({
				title: __("CGM Settings"),
				message: __(
					"Sea task requirements could not be loaded. Configure CGM Shipping Settings → Sea clearance task requirements."
				),
				indicator: "red",
			});
			// Still keep any already-confirmed client-paid fields visible from the doc.
			configure_client_paid_field(frm, get_sea_task_ui(frm));
			schedule_cgm_task_toolbar_buttons(frm);
		},
	});
}

function get_cgm_sea_seq_config(frm) {
	return frm._cgm_sea_seq_config || CGM_SEA_UI_SEQUENCES_EMPTY;
}

function get_cgm_permissions(frm) {
	const perms = get_cgm_sea_seq_config(frm).permissions;
	if (perms && Object.keys(perms).length) {
		return perms;
	}
	const roles = frappe.user_roles || [];
	const from_fallback = (key) =>
		(CGM_TASK_PERMISSIONS_FALLBACK[key] || []).some((r) => roles.includes(r));
	return {
		can_make_payment: from_fallback("can_make_payment"),
		can_upload_receipt: from_fallback("can_upload_receipt"),
		can_upload_pop: from_fallback("can_upload_pop"),
		can_verify_invoice: from_fallback("can_verify_invoice"),
		can_upload_invoice: from_fallback("can_upload_invoice"),
		can_upload_certificate: from_fallback("can_upload_certificate"),
		can_confirm_client_paid: from_fallback("can_confirm_client_paid"),
		can_upload_document: from_fallback("can_upload_document"),
		can_record_purchase_invoice: from_fallback("can_record_purchase_invoice"),
	};
}

function seq_in_list(seq, list) {
	return (list || []).includes(seq);
}

function is_ucr_application_step(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return seq_in_list(s, get_cgm_sea_seq_config(frm).ucr_application_seqs);
}

function is_ucr_finance_step(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return seq_in_list(s, get_cgm_sea_seq_config(frm).ucr_finance_seqs);
}

function is_entry_application_step(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return seq_in_list(s, get_cgm_sea_seq_config(frm).entry_application_seqs);
}

function is_entry_finance_step(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return seq_in_list(s, get_cgm_sea_seq_config(frm).entry_finance_seqs);
}

function is_shipping_line_application_step(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return seq_in_list(s, get_cgm_sea_seq_config(frm).shipping_line_application_seqs);
}

function is_shipping_line_finance_step(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return seq_in_list(s, get_cgm_sea_seq_config(frm).shipping_line_finance_seqs);
}

const CGM_APP_FINANCE_PROFILES = {
	shipping_line: {
		application_seqs_key: "shipping_line_application_seqs",
		finance_seqs_key: "shipping_line_finance_seqs",
		upload_role: __("Documentation"),
	},
	kpa: {
		application_seqs_key: "kpa_application_seqs",
		finance_seqs_key: "kpa_finance_seqs",
		upload_role: __("Supervisor"),
	},
};

function is_app_finance_application_step(frm, seq, profileKey) {
	const profile = CGM_APP_FINANCE_PROFILES[profileKey];
	if (!profile) {
		return false;
	}
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return seq_in_list(s, get_cgm_sea_seq_config(frm)[profile.application_seqs_key] || []);
}

function is_app_finance_finance_step(frm, seq, profileKey) {
	const profile = CGM_APP_FINANCE_PROFILES[profileKey];
	if (!profile) {
		return false;
	}
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return seq_in_list(s, get_cgm_sea_seq_config(frm)[profile.finance_seqs_key] || []);
}

function is_kpa_application_step(frm, seq) {
	return is_app_finance_application_step(frm, seq, "kpa");
}

function is_kpa_finance_step(frm, seq) {
	return is_app_finance_finance_step(frm, seq, "kpa");
}

function is_permit_application_step(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return seq_in_list(s, get_cgm_sea_seq_config(frm).permit_application_seqs);
}

function is_permit_finance_step(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return seq_in_list(s, get_cgm_sea_seq_config(frm).permit_finance_seqs);
}

function is_permit_payment_pattern(frm) {
	return (
		is_permit_finance_step(frm) &&
		(frm.doc.custom_task_permits || []).some((r) => r.permit_type)
	);
}

function permit_finance_rows_on_form(frm) {
	return (frm.doc.custom_task_permits || []).filter(
		(r) => r.permit_type && (r.origin || "Local") !== "Foreign"
	);
}

function permit_rows_all_have_journal_entry(frm) {
	const rows = permit_finance_rows_on_form(frm);
	return (
		rows.length > 0 &&
		rows.every(
			(r) =>
				r.journal_entry || cint(r.client_reported_paid) || cint(r.client_paid_directly)
		)
	);
}

function get_permit_stage_for_seq(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	const map = get_cgm_sea_seq_config(frm).permit_stage_by_seq || {};
	return map[String(s)] || map[s] || null;
}

function is_pre_clearance_permit_application_step(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return (
		is_permit_application_step(frm, s) &&
		get_permit_stage_for_seq(frm, s) === "Pre-clearance"
	);
}

function is_post_clearance_permit_application_step(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return (
		is_permit_application_step(frm, s) &&
		get_permit_stage_for_seq(frm, s) === "Post-clearance"
	);
}

function is_permit_application_step_for_stage(frm, seq) {
	return (
		is_pre_clearance_permit_application_step(frm, seq) ||
		is_post_clearance_permit_application_step(frm, seq)
	);
}

function get_paired_permit_application_seq(frm, financeSeq) {
	const stage = get_permit_stage_for_seq(frm, financeSeq);
	if (!stage) {
		return null;
	}
	const cfg = get_cgm_sea_seq_config(frm);
	return (cfg.permit_application_seqs || []).find(
		(seq) => get_permit_stage_for_seq(frm, seq) === stage
	);
}

function get_paired_permit_finance_seq(frm, applicationSeq) {
	const stage = get_permit_stage_for_seq(frm, applicationSeq);
	if (!stage) {
		return null;
	}
	const cfg = get_cgm_sea_seq_config(frm);
	return (cfg.permit_finance_seqs || []).find(
		(seq) => get_permit_stage_for_seq(frm, seq) === stage
	);
}

function permit_application_task_label(frm, seq) {
	const stage = get_permit_stage_for_seq(frm, seq);
	if (stage === "Post-clearance") {
		return __("Prepare Post-Clearance Permits");
	}
	return __("Apply for Pre-Clearance Permits");
}

function permit_finance_task_label(frm, financeSeq) {
	const stage = get_permit_stage_for_seq(frm, financeSeq);
	if (stage === "Post-clearance") {
		return __("Finance pays for Post-Clearance Permits");
	}
	return __("Finance pays Pre-Clearance Permits");
}

const SEA_TASK_HIDDEN_FIELDS = [
	"is_template",
	"issue",
	"type",
	"color",
	"is_milestone",
	"task_weight",
	"exp_start_date",
	"exp_end_date",
	"expected_time",
	"duration",
	"progress",
	"total_costing_amount",
	"total_billing_amount",
	"total_expense_claim",
	"review_date",
	"closing_date",
];

function is_sea_clearance_task(frm) {
	return isSeaImportFlowKey(get_task_flow_key(frm));
}

function sea_task_sequence(frm) {
	return Number(frm.doc.custom_sequence_no || 0);
}

function get_sea_task_ui(frm) {
	const seq = sea_task_sequence(frm);
	const cfg = get_cgm_sea_seq_config(frm);
	if (!is_sea_clearance_task(frm)) {
		return {
			is_sea_task: false,
			show_documents: true,
			documents_read_only: false,
			show_permits: false,
			show_payments: false,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: false,
		};
	}
	if (seq_in_list(seq, cfg.auto_complete_seqs)) {
		const completed = frm.doc.status === "Completed";
		return {
			is_sea_task: true,
			show_documents: true,
			// Allow correcting intake docs after an explicit Re-open.
			documents_read_only: completed,
			show_permits: false,
			show_payments: false,
			show_external_ref: false,
			show_description: true,
			auto_intake_intro: completed,
			hide_mark_complete: completed,
		};
	}
	if (seq_in_list(seq, cfg.ucr_application_seqs)) {
		return {
			is_sea_task: true,
			is_ucr_application: true,
			is_ucr_finance: false,
			is_entry_application: false,
			is_entry_finance: false,
			show_finance_lines: true,
			show_documents: true,
			documents_read_only: false,
			show_permits: false,
			show_payments: false,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: true,
		};
	}
	if (seq_in_list(seq, cfg.entry_application_seqs)) {
		return {
			is_sea_task: true,
			is_ucr_application: false,
			is_ucr_finance: false,
			is_entry_application: true,
			is_entry_finance: false,
			is_shipping_line_application: false,
			is_shipping_line_finance: false,
			show_finance_lines: true,
			show_documents: true,
			documents_read_only: false,
			show_permits: false,
			show_payments: false,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: true,
		};
	}
	if (seq_in_list(seq, cfg.shipping_line_application_seqs)) {
		return {
			is_sea_task: true,
			is_ucr_application: false,
			is_ucr_finance: false,
			is_entry_application: false,
			is_entry_finance: false,
			is_shipping_line_application: true,
			is_shipping_line_finance: false,
			is_kpa_application: false,
			is_kpa_finance: false,
			show_finance_lines: true,
			show_documents: false,
			documents_read_only: false,
			show_permits: false,
			show_payments: false,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: true,
		};
	}
	if (seq_in_list(seq, cfg.kpa_application_seqs)) {
		return {
			is_sea_task: true,
			is_ucr_application: false,
			is_ucr_finance: false,
			is_entry_application: false,
			is_entry_finance: false,
			is_shipping_line_application: false,
			is_shipping_line_finance: false,
			is_kpa_application: true,
			is_kpa_finance: false,
			show_finance_lines: true,
			show_documents: false,
			documents_read_only: false,
			show_permits: false,
			show_payments: false,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: true,
		};
	}
	if (seq_in_list(seq, cfg.permit_application_seqs)) {
		return {
			is_sea_task: true,
			is_ucr_application: false,
			is_ucr_finance: false,
			show_documents: false,
			documents_read_only: false,
			show_permits: true,
			show_payments: false,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: true,
		};
	}
	if (seq_in_list(seq, cfg.payment_seqs)) {
		const ucr_finance = seq_in_list(seq, cfg.ucr_finance_seqs);
		const entry_finance = seq_in_list(seq, cfg.entry_finance_seqs);
		const shipping_line_finance = seq_in_list(seq, cfg.shipping_line_finance_seqs);
		const kpa_finance = seq_in_list(seq, cfg.kpa_finance_seqs);
		return {
			is_sea_task: true,
			is_ucr_application: false,
			is_ucr_finance: ucr_finance,
			is_entry_application: false,
			is_entry_finance: entry_finance,
			is_shipping_line_application: false,
			is_shipping_line_finance: shipping_line_finance,
			is_kpa_application: false,
			is_kpa_finance: kpa_finance,
			show_finance_lines: ucr_finance || entry_finance || shipping_line_finance || kpa_finance,
			show_documents: seq_in_list(seq, cfg.finance_document_seqs),
			documents_read_only: false,
			show_permits: seq_in_list(seq, cfg.permit_finance_seqs),
			show_payments: true,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: true,
		};
	}
	if (seq_in_list(seq, cfg.light_proof_seqs)) {
		return {
			is_sea_task: true,
			show_documents: false,
			documents_read_only: false,
			show_permits: false,
			show_payments: false,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: false,
		};
	}
	if (seq_in_list(seq, cfg.document_checkpoint_seqs)) {
		return {
			is_sea_task: true,
			is_document_checkpoint: true,
			show_documents: true,
			documents_read_only: false,
			documents_versioned: true,
			documents_initial_read_only: true,
			show_permits: false,
			show_payments: false,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: false,
		};
	}
	return {
		is_sea_task: true,
		show_documents: true,
		documents_read_only: false,
		show_permits: false,
		show_payments: false,
		show_external_ref: seq >= 3,
		show_description: true,
		auto_intake_intro: false,
		hide_mark_complete: false,
	};
}

function apply_sea_task_form_layout(frm, ui) {
	ui = ui || get_sea_task_ui(frm);

	const toggle = (fieldname, visible) => {
		if (frm.fields_dict[fieldname]) {
			frm.set_df_property(fieldname, "hidden", visible ? 0 : 1);
		}
	};

	if (!ui.is_sea_task) {
		return;
	}

	SEA_TASK_HIDDEN_FIELDS.forEach((f) => toggle(f, false));
	const show_finance = Boolean(ui.show_finance_lines && frm.fields_dict.custom_task_finance_lines);
	toggle("custom_section_task_finance", show_finance);
	toggle("custom_task_finance_lines", show_finance);
	if (show_finance) {
		configure_finance_line_grid(frm, ui);
		if (frm.fields_dict.custom_section_task_finance) {
			frm.set_df_property("custom_section_task_finance", "description", "");
		}
	}
	toggle("custom_section_break_0gs4o", ui.show_documents);
	toggle("custom_task_documents", ui.show_documents);
	if (ui.show_documents && frm.fields_dict.custom_task_documents) {
		frm.set_df_property("custom_task_documents", "read_only", ui.documents_read_only ? 1 : 0);
		configure_task_document_version_grid(frm, ui);
		if (frm.fields_dict.custom_section_break_0gs4o) {
			frm.set_df_property("custom_section_break_0gs4o", "label", __("Clearance Documents"));
		}
	}
	["custom_section_task_permits", "custom_task_permits"].forEach((fieldname) => {
		if (!frm.fields_dict[fieldname]) {
			return;
		}
		if (ui.show_permits) {
			frm.set_df_property(fieldname, "depends_on", sea_task_permits_depends_on(frm));
		}
		toggle(fieldname, ui.show_permits);
	});
	if (ui.show_permits) {
		configure_permit_grid(frm);
		frm.refresh_field("custom_task_permits");
	}
	toggle("custom_payment_entry", ui.show_payments);
	toggle("custom_purchase_invoice", ui.show_payments);
	toggle(
		"custom_journal_entry",
		ui.show_payments && !is_permit_finance_step(frm, sea_task_sequence(frm))
	);
	configure_ucr_finance_fields(frm, ui);
	toggle("custom_external_ref_no", ui.show_external_ref);
	toggle("description", ui.show_description);
	apply_field_officer_task_fields(frm);
	apply_client_inspection_task_fields(frm);
	toggle("sb_timeline", false);
	toggle("sb_costing", false);
	toggle("depends_on_tab", false);
}

function apply_field_officer_task_fields(frm) {
	const seq = sea_task_sequence(frm);
	const show = is_sea_clearance_task(frm) && seq === 18;
	const fields = [
		"custom_section_field_clearance",
		"custom_verification_type",
		"custom_verification_status",
		"custom_customs_issue",
		"custom_delivery_note_status",
		"custom_coc_status",
		"custom_verification_report_attached",
	];
	fields.forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.set_df_property(fieldname, "hidden", show ? 0 : 1);
		}
	});
}

const CLIENT_INSPECTION_TASK_SEQ = 7;

function is_client_inspection_task(frm) {
	return is_sea_clearance_task(frm) && sea_task_sequence(frm) === CLIENT_INSPECTION_TASK_SEQ;
}

function apply_client_inspection_task_fields(frm) {
	const show = is_client_inspection_task(frm);
	const fields = [
		"custom_section_client_inspection",
		"custom_client_notified_on",
		"custom_client_notified_by",
		"custom_inspection_confirmed_on",
		"custom_inspection_confirmed_by",
	];
	fields.forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.set_df_property(fieldname, "hidden", show ? 0 : 1);
		}
	});
}

function setup_client_inspection_buttons(frm) {
	if (!is_client_inspection_task(frm) || frm.is_new()) {
		return;
	}
	if (frm.doc.custom_inspection_confirmed_on) {
		const when = frappe.datetime.str_to_user(frm.doc.custom_inspection_confirmed_on);
		const by = frm.doc.custom_inspection_confirmed_by || "";
		set_task_intro(
			frm,
			__("Inspection confirmed on {0}{1}", [
				when,
				by ? ` (${frappe.utils.escape_html(by)})` : "",
			]),
			"green"
		);
		return;
	}
	if (frm.doc.custom_client_notified_on) {
		const when = frappe.datetime.str_to_user(frm.doc.custom_client_notified_on);
		const by = frm.doc.custom_client_notified_by || "";
		set_task_intro(frm, __("Notified on {0} by {1}", [when, by]), "blue");
		add_cgm_toolbar_button(frm, __("Notify Again"), () => notify_client_for_inspection_from_form(frm));
		add_cgm_toolbar_button(
			frm,
			__("Client Has Completed Inspection"),
			() => confirm_client_inspection_from_task_form(frm)
		);
		return;
	}
	add_cgm_toolbar_button(
		frm,
		__("Notify Client for Inspection"),
		() => notify_client_for_inspection_from_form(frm),
		{ primary: true }
	);
}

function finance_task_has_shareable_invoice(frm) {
	return (
		finance_task_has_unshared_verified_invoice(frm) ||
		finance_task_has_already_shared_invoice(frm)
	);
}

function finance_task_has_unshared_verified_invoice(frm) {
	const lines = frm.doc.custom_task_finance_lines || [];
	const has_fin = lines.some(
		(r) =>
			(r.line_type || "Invoice") === "Invoice" &&
			r.attachment &&
			cint(r.verified) &&
			!cint(r.shared_with_client)
	);
	if (has_fin) {
		return true;
	}
	return (frm.doc.custom_task_permits || []).some(
		(r) =>
			r.permit_type &&
			(r.origin || "Local") !== "Foreign" &&
			r.payment_invoice &&
			cint(r.invoice_verified) &&
			!cint(r.shared_with_client)
	);
}

function finance_task_has_already_shared_invoice(frm) {
	const lines = frm.doc.custom_task_finance_lines || [];
	if (
		lines.some(
			(r) =>
				(r.line_type || "Invoice") === "Invoice" &&
				r.attachment &&
				cint(r.shared_with_client)
		)
	) {
		return true;
	}
	return (frm.doc.custom_task_permits || []).some(
		(r) => r.payment_invoice && cint(r.shared_with_client)
	);
}

function share_invoices_with_client_from_form(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint({
			title: __("Save first"),
			message: __("Save the task, then share the invoice with the client."),
			indicator: "orange",
		});
		return;
	}
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.client_invoice_share.share_invoices_with_client",
		args: { task_name: frm.doc.name, notify: 1 },
		freeze: true,
		freeze_message: __("Sharing invoice…"),
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			frappe.show_alert({
				message: r.message.message || __("Shared with client."),
				indicator: "green",
			});
			frm.reload_doc();
		},
	});
}

function notify_client_for_inspection_from_form(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint({
			title: __("Save first"),
			message: __("Save the task, then notify the client."),
			indicator: "orange",
		});
		return;
	}
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.inspection.notify_client_for_inspection",
		args: { task_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Notifying client…"),
		callback(r) {
			showWorkflowNotifyResult(r, __("Client notified for inspection."));
			if (!r.exc) {
				frm.reload_doc();
			}
		},
	});
}

function confirm_client_inspection_from_task_form(frm) {
	frappe.confirm(__("Record that the client has completed inspection for this shipment?"), () => {
		frappe.call({
			method:
				"cgm_shipping.cgm_worldwide_shipping.customizations.inspection.confirm_client_inspection_from_task",
			args: { task_name: frm.doc.name },
			freeze: true,
			callback(r) {
				if (r.exc) {
					return;
				}
				frappe.show_alert({
					message: r.message?.message || __("Inspection marked as complete."),
					indicator: "green",
				});
				frm.reload_doc();
			},
		});
	});
}

function permit_rows_have_invoices(frm) {
	const rows = frm.doc.custom_task_permits || [];
	if (!rows.length) {
		return false;
	}
	return rows.every((r) => {
		if (!r.permit_type) {
			return false;
		}
		if ((r.origin || "Local") === "Foreign") {
			return Boolean(r.permit_document);
		}
		return Boolean(r.payment_invoice);
	});
}

function permit_rows_pending_invoice_verification(frm) {
	return (frm.doc.custom_task_permits || []).filter(
		(r) =>
			r.permit_type &&
			(r.origin || "Local") !== "Foreign" &&
			r.payment_invoice &&
			!cint(r.invoice_verified)
	);
}

function permit_rows_pending_receipt_verification(frm) {
	return (frm.doc.custom_task_permits || []).filter(
		(r) =>
			r.permit_type &&
			(r.origin || "Local") !== "Foreign" &&
			r.payment_receipt &&
			!r.receipt_verified
	);
}

function client_paid_settlement_ready_on_form(frm) {
	if (!frm.doc.custom_client_paid_directly) {
		return false;
	}
	if (is_permit_payment_pattern(frm)) {
		const rows = permit_finance_rows_on_form(frm);
		if (!rows.length) {
			return true;
		}
		return rows.every((r) => cint(r.invoice_verified));
	}
	// App-finance settlement is confirmed server-side; client-pays alone is not enough.
	return false;
}

function task_has_recorded_payment_on_form(frm) {
	if (frm.doc.custom_client_paid_directly) {
		return client_paid_settlement_ready_on_form(frm);
	}
	if (is_permit_payment_pattern(frm)) {
		return permit_rows_all_have_journal_entry(frm);
	}
	const invoices = get_invoice_finance_lines(frm).filter((r) => r.attachment);
	if (invoices.length > 1 || invoices.some((r) => cint(r.is_amendment))) {
		return invoices.length > 0 && invoices.every((r) => invoice_line_settled_on_form(r, frm));
	}
	return Boolean(frm.doc.custom_journal_entry || frm.doc.custom_payment_entry);
}

function complete_permit_application_task_from_form(frm) {
	if (frm._cgm_completing_permit_application || frm.is_new()) {
		return;
	}
	if (frm.is_dirty()) {
		frappe.msgprint({
			title: __("Unsaved changes"),
			message: __(
				"Save your changes first, then click Complete again. " +
					"Completing from an unsaved form causes conflicts."
			),
			indicator: "orange",
		});
		return;
	}
	frm._cgm_completing_permit_application = true;
	frm._cgm_task_action_busy = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.complete_permit_application_task",
		args: { task_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Completing permit task…"),
		callback(r) {
			if (r.exc || !r.message) {
				frm._cgm_completing_permit_application = false;
				frm._cgm_task_action_busy = false;
				schedule_cgm_task_toolbar_buttons(frm);
				return;
			}
			frappe.show_alert({
				message: __(r.message.message || "Permit application task completed."),
				indicator: "green",
			});
			frm.reload_doc().always(() => {
				frm._cgm_completing_permit_application = false;
				frm._cgm_task_action_busy = false;
			});
		},
		error() {
			frm._cgm_completing_permit_application = false;
			frm._cgm_task_action_busy = false;
			schedule_cgm_task_toolbar_buttons(frm);
		},
	});
}

function verify_all_permit_invoices_from_form(frm) {
	if (frm._cgm_verifying_permit_invoices) {
		return;
	}
	if (frm.is_dirty()) {
		frappe.msgprint({
			title: __("Unsaved changes"),
			message: __("Save the task, then click Verify Invoices again."),
			indicator: "orange",
		});
		return;
	}
	frm._cgm_verifying_permit_invoices = true;
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.workflow.verify_all_permit_invoices",
		args: { task_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Verifying permit invoices…"),
		callback(r) {
			frm._cgm_verifying_permit_invoices = false;
			if (r.exc || !r.message) {
				return;
			}
			frappe.show_alert({
				message: r.message.message || __("Invoices verified"),
				indicator: "green",
			});
			frm.reload_doc();
		},
		error() {
			frm._cgm_verifying_permit_invoices = false;
		},
	});
}

function verify_all_permit_receipts_from_form(frm) {
	if (frm._cgm_verifying_permit_receipts) {
		return;
	}
	if (frm.is_dirty()) {
		frappe.msgprint({
			title: __("Save first"),
			message: __("Save the task, then click Verify Receipt again."),
			indicator: "orange",
		});
		return;
	}
	frm._cgm_verifying_permit_receipts = true;
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.workflow.verify_all_permit_receipts",
		args: { task_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Verifying permit receipts…"),
		callback(r) {
			frm._cgm_verifying_permit_receipts = false;
			if (r.exc) {
				return;
			}
			const data = r.message || {};
			frappe.show_alert({
				message:
					data.message ||
					__(
						"Permit receipts verified — Finance pays Pre-Clearance Permits and Apply for Pre-Clearance Permits are completed."
					),
				indicator: data.auto_completed ? "green" : "blue",
			});
			frm.reload_doc();
		},
		error() {
			frm._cgm_verifying_permit_receipts = false;
		},
	});
}

function ensure_permit_finance_reopened_for_pending(frm) {
	if (frm._cgm_permit_finance_reopen_checking || frm.is_new()) {
		return;
	}
	if (!is_permit_finance_step(frm) || frm.doc.status !== "Completed") {
		return;
	}
	const pending = (frm.doc.custom_task_permits || []).filter(
		(r) =>
			r.permit_type &&
			(r.origin || "Local") !== "Foreign" &&
			r.payment_invoice &&
			(!cint(r.invoice_verified) ||
				(!frm.doc.custom_client_paid_directly && !r.journal_entry))
	);
	if (!pending.length) {
		return;
	}
	frm._cgm_permit_finance_reopen_checking = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.reopen_permit_finance_for_pending_payments",
		args: { task_name: frm.doc.name },
		callback(r) {
			frm._cgm_permit_finance_reopen_checking = false;
			if (r.exc || !r.message) {
				return;
			}
			const names = (r.message.pending_permits || []).join(", ");
			if (r.message.status === "Open" || (r.message.reopened || []).length) {
				frappe.show_alert({
					message: names
						? __(
								"Task reopened for unpaid permits: {0}. Verify invoices, then Make Payment.",
								[names]
						  )
						: __(
								"Task reopened for additional permit payments. Verify invoices, then Make Payment."
						  ),
					indicator: "orange",
				});
				frm.reload_doc();
			}
		},
		error() {
			frm._cgm_permit_finance_reopen_checking = false;
		},
	});
}

function ensure_finance_permit_task_completed_on_form(frm) {
	if (frm._cgm_permit_finance_complete_checking) {
		return;
	}
	if (!is_permit_finance_step(frm) || frm.doc.status === "Completed") {
		return;
	}
	if (!task_has_recorded_payment_on_form(frm)) {
		return;
	}
	const rows = permit_finance_rows_on_form(frm);
	const client_paid = Boolean(frm.doc.custom_client_paid_directly);
	if (
		!rows.length ||
		rows.some(
			(r) =>
				!cint(r.invoice_verified) ||
				(!client_paid && !r.journal_entry)
		)
	) {
		return;
	}
	frm._cgm_permit_finance_complete_checking = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.ensure_permit_finance_task_completed",
		args: { task_name: frm.doc.name },
		callback(r) {
			frm._cgm_permit_finance_complete_checking = false;
			if (r.exc || !r.message?.auto_completed) {
				return;
			}
			frappe.show_alert({
				message: __(
					"Permit receipts uploaded — Finance and declarant pre-clearance tasks completed."
				),
				indicator: "green",
			});
			frm.reload_doc();
		},
		error() {
			frm._cgm_permit_finance_complete_checking = false;
		},
	});
}

function get_finance_line(frm, line_type) {
	return (frm.doc.custom_task_finance_lines || []).find((r) => r.line_type === line_type);
}

function get_invoice_finance_lines(frm) {
	return (frm.doc.custom_task_finance_lines || []).filter(
		(r) => (r.line_type || "Invoice") === "Invoice"
	);
}

function is_app_finance_payment_step(frm, ui) {
	ui = ui || get_sea_task_ui(frm);
	return Boolean(
		ui.is_ucr_finance ||
			ui.is_entry_finance ||
			ui.is_shipping_line_finance ||
			ui.is_kpa_finance
	);
}

function form_has_client_paid_invoice_line(frm) {
	if (cint(frm.doc.custom_client_paid_directly)) {
		return true;
	}
	return get_invoice_finance_lines(frm).some(
		(r) => r.attachment && cint(r.client_paid_directly)
	);
}

function invoice_line_settled_on_form(row, frm) {
	if (!row || !row.attachment) {
		return false;
	}
	if (row.journal_entry) {
		return true;
	}
	if (cint(row.client_paid_directly) || cint(row.client_reported_paid)) {
		return true;
	}
	// Legacy primary: task-level JE / client-pays (only when JE is not on an amendment).
	if (!cint(row.is_amendment)) {
		const taskJe = frm.doc.custom_journal_entry || frm.doc.custom_payment_entry;
		if (taskJe) {
			const onAmendment = get_invoice_finance_lines(frm).some(
				(r) => cint(r.is_amendment) && r.journal_entry === taskJe
			);
			if (!onAmendment) {
				return true;
			}
		}
		if (cint(frm.doc.custom_client_paid_directly) && cint(row.verified)) {
			return true;
		}
	}
	return false;
}

function unpaid_verified_invoice_lines_on_form(frm) {
	return get_invoice_finance_lines(frm).filter(
		(r) =>
			r.attachment &&
			cint(r.verified) &&
			!invoice_line_settled_on_form(r, frm) &&
			!cint(r.client_paid_directly)
	);
}

function unverified_invoice_lines_on_form(frm) {
	return get_invoice_finance_lines(frm).filter(
		(r) => r.attachment && !cint(r.verified)
	);
}

function unverified_receipt_line_on_form(frm) {
	const rec = get_finance_line(frm, "Receipt");
	if (rec?.attachment && !cint(rec.verified)) {
		return rec;
	}
	return null;
}

function finance_line_display_label(row) {
	return (
		row.charge_item ||
		row.line_label ||
		(cint(row.is_amendment) ? __("Invoice (amendment)") : __("Invoice"))
	);
}

function ucr_finance_ready_on_form(frm) {
	const inv = get_finance_line(frm, "Invoice");
	const rec = get_finance_line(frm, "Receipt");
	return Boolean(inv && inv.verified && rec && rec.attachment && rec.verified);
}

function configure_task_document_version_grid(frm, ui) {
	const grid = frm.fields_dict.custom_task_documents?.grid;
	if (!grid) {
		return;
	}
	ui = ui || get_sea_task_ui(frm);

	if (cgm_has_shipment_document_versioning() && cgm_hydrate_legacy_document_rows(frm, "custom_task_documents")) {
		frm.refresh_field("custom_task_documents");
	}

	const checkpoint = Boolean(ui.is_document_checkpoint);
	const versioned = checkpoint || Boolean(ui.documents_versioned);
	cgm_configure_shipment_document_grid(grid, {
		initial_read_only: versioned && ui.documents_initial_read_only,
	});
	cgm_sync_shipment_document_rows_on_refresh(frm, "custom_task_documents");
}

function ensure_checkpoint_task_documents_on_form(frm) {
	const rows = frm.doc.custom_task_documents || [];
	if (rows.length || frm._cgm_checkpoint_seed_requested || frm.doc.__unsaved) {
		return;
	}
	frm._cgm_checkpoint_seed_requested = true;
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.documents.ensure_checkpoint_task_documents",
		args: { task_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Loading clearance documents from Project…"),
		callback(r) {
			if (r.exc) {
				return;
			}
			if (r.message?.seeded || r.message?.backfilled) {
				frm.reload_doc();
			}
		},
	});
}

function configure_finance_line_grid(frm, ui) {
	const grid = frm.fields_dict.custom_task_finance_lines?.grid;
	if (!grid || frm._cgm_finance_grid_ready) {
		return;
	}
	const is_finance = user_can_make_payment(frm);
	const can_receipt = user_can_upload_receipt(frm);
	const can_pop = user_can_upload_pop(frm);
	const seq = sea_task_sequence(frm);
	const is_app_step =
		is_ucr_application_step(frm, seq) ||
		is_entry_application_step(frm, seq) ||
		is_shipping_line_application_step(frm, seq) ||
		is_kpa_application_step(frm, seq);
	const is_fin_step =
		is_ucr_finance_step(frm, seq) ||
		is_entry_finance_step(frm, seq) ||
		is_shipping_line_finance_step(frm, seq) ||
		is_kpa_finance_step(frm, seq);

	// Set docfield properties directly - avoid toggle_enable() which re-renders the grid
	// and can collapse the toolbar while the user clicks action buttons.
	const verified_df = grid.get_docfield("verified");
	if (verified_df) {
		verified_df.read_only = is_app_step ? 1 : is_finance ? 0 : 1;
	}
	// Item links to Clearance Charge Item master (UCR Invoice, UCR Receipt, …).
	grid.update_docfield_property("charge_item", "read_only", 0);
	if (grid.get_docfield("line_label")) {
		grid.update_docfield_property("line_label", "hidden", 1);
	}
	const charge_field = grid.get_field("charge_item");
	if (charge_field && !charge_field._cgm_charge_query) {
		charge_field._cgm_charge_query = true;
		charge_field.get_query = (_doc, cdt, cdn) => {
			const row = locals[cdt][cdn] || {};
			const filters = { is_active: 1 };
			if (row.line_type) {
				filters.line_type = row.line_type;
			}
			if (row.payment_item) {
				filters.payment_kind = row.payment_item;
			}
			return { filters };
		};
	}

	if (is_app_step) {
		// Invoice editable even after completion (additional / replacement docs).
		frm.set_df_property("custom_task_finance_lines", "read_only", 0);
		grid.update_docfield_property("attachment", "read_only", 0);
		grid.update_docfield_property("item_code", "read_only", 0);
		grid.update_docfield_property("item_code", "hidden", 0);
		if (grid.get_docfield("client_paid_directly")) {
			grid.update_docfield_property("client_paid_directly", "read_only", 1);
		}
		if (grid.get_docfield("journal_entry")) {
			grid.update_docfield_property("journal_entry", "read_only", 1);
		}
	} else if (is_fin_step) {
		// Invoice copied from application; POP / receipt by role (row-level in form_render).
		grid.update_docfield_property(
			"attachment",
			"read_only",
			can_receipt || can_pop ? 0 : 1
		);
		grid.update_docfield_property("item_code", "read_only", 0);
		grid.update_docfield_property("item_code", "hidden", 0);
		// Per-invoice Client will pay (e.g. amendment after company paid the first).
		if (grid.get_docfield("client_paid_directly")) {
			grid.update_docfield_property(
				"client_paid_directly",
				"read_only",
				is_finance ? 0 : 1
			);
		}
		if (grid.get_docfield("journal_entry")) {
			grid.update_docfield_property("journal_entry", "read_only", 1);
		}
	}

	frm._cgm_finance_grid_ready = true;
	if (cgm_shipping.status_field?.attach_grid_formatters) {
		cgm_shipping.status_field.attach_grid_formatters(
			grid,
			"verified",
			(value) => cgm_shipping.status_field.tone_for_verified(value)
		);
		cgm_shipping.status_field.paint_grid?.(
			grid,
			"verified",
			(value) => cgm_shipping.status_field.tone_for_verified(value)
		);
	}
}

function reset_cgm_task_sea_ui_state_if_needed(frm) {
	if (!frm.doc?.name || frm._cgm_sea_ui_task === frm.docname) {
		return;
	}
	frm._cgm_sea_ui_task = frm.docname;
	// Reuse desk-session cache instead of nulling and re-fetching from the server.
	frm._cgm_sea_seq_config = CGM_SEA_UI_SEQUENCES_CACHE || null;
	frm._cgm_sea_seq_loading = false;
	frm._cgm_sea_seq_load_failed = false;
	frm._cgm_sea_layout_ready = false;
	frm._cgm_finance_grid_ready = false;
	frm._cgm_status_grids_ready = false;
	frm._cgm_shipping_line_deposit_grid_ready = false;
	frm._cgm_toolbar_fingerprint = null;
	frm._cgm_shipping_line_finance_lines_ensured = false;
	frm._cgm_kpa_finance_lines_ensured = false;
	frm._cgm_ucr_finance_ensure_done = false;
	frm._cgm_entry_finance_ensure_done = false;
	frm._cgm_shipping_line_finance_ensure_done = false;
	frm._cgm_kpa_finance_ensure_done = false;
	frm._cgm_finance_department = CGM_SEA_UI_SEQUENCES_CACHE?.finance_department;
	if (is_sea_clearance_task(frm) && !frm._cgm_sea_seq_config) {
		load_cgm_sea_ui_sequences(frm);
	}
}

function ensure_cgm_finance_department_loaded(frm) {
	if (frm._cgm_finance_department !== undefined) {
		return;
	}
	if (frm._cgm_sea_seq_config?.finance_department) {
		frm._cgm_finance_department = frm._cgm_sea_seq_config.finance_department;
		return;
	}
	if (frm._cgm_finance_department_loading) {
		return;
	}
	frm._cgm_finance_department_loading = true;
	frappe.db
		.get_single_value("CGM Shipping Settings", "custom_finance_department")
		.then((dept) => {
			frm._cgm_finance_department_loading = false;
			frm._cgm_finance_department = dept || null;
			if (frm.doc.name === frm.docname && !frm.is_new()) {
				schedule_cgm_task_toolbar_buttons(frm);
			}
		})
		.catch(() => {
			frm._cgm_finance_department_loading = false;
			frm._cgm_finance_department = null;
		});
}

function get_finance_department(frm) {
	if (frm._cgm_finance_department) {
		return frm._cgm_finance_department;
	}
	return get_cgm_sea_seq_config(frm).finance_department || null;
}

function register_task_toolbar_after_render(frm, eventKey, register_action) {
	// Keep a single render_complete binding — rebinding on every schedule caused
	// stacked timeouts and visible button flicker.
	if (frm[`_cgm_${eventKey}_bound`]) {
		return;
	}
	frm[`_cgm_${eventKey}_bound`] = true;
	$(frm.wrapper)
		.off(`render_complete.${eventKey}`)
		.on(`render_complete.${eventKey}`, () => {
			register_action();
		});
}

function schedule_cgm_task_toolbar_buttons(frm) {
	if (frm.is_new() || !frm.doc.name) {
		return;
	}
	if (frm._cgm_task_action_busy || frm._cgm_completing_permit_application) {
		return;
	}
	clearTimeout(frm._cgm_toolbar_timer);
	const mount = () => {
		if (frm.is_new() || frm.doc.name !== frm.docname) {
			return;
		}
		if (frm._cgm_task_action_busy || frm._cgm_completing_permit_application) {
			return;
		}
		if (is_sea_clearance_task(frm) && !frm._cgm_sea_seq_config && !frm._cgm_sea_seq_loading) {
			load_cgm_sea_ui_sequences(frm);
		}
		mount_cgm_task_toolbar_buttons(frm);
	};
	// Debounce stacked refresh remounts. Do not re-bind render_complete — that
	// remounted on every child-grid paint and made Open Shipment Project flicker.
	frm._cgm_toolbar_timer = setTimeout(mount, 80);
}

function cgm_task_toolbar_fingerprint(frm) {
	const ui = get_sea_task_ui(frm);
	const inv = get_finance_line(frm, "Invoice");
	const rec = get_finance_line(frm, "Receipt");
	const invoice_sig = get_invoice_finance_lines(frm)
		.map(
			(r) =>
				`${r.name || ""}:${cint(r.verified)}:${r.attachment ? 1 : 0}:${r.journal_entry || ""}:${cint(r.is_amendment)}:${cint(r.client_paid_directly)}`
		)
		.join(",");
	return [
		frm.doc.name,
		frm.doc.status,
		cint(frm.doc.custom_client_paid_directly),
		ui.is_shipping_line_finance ? 1 : 0,
		ui.is_shipping_line_application ? 1 : 0,
		ui.is_ucr_finance ? 1 : 0,
		ui.is_entry_finance ? 1 : 0,
		ui.is_kpa_finance ? 1 : 0,
		inv?.verified ? 1 : 0,
		inv?.attachment ? 1 : 0,
		rec?.verified ? 1 : 0,
		rec?.attachment ? 1 : 0,
		invoice_sig,
		user_can_make_payment(frm) ? 1 : 0,
		user_can_verify_invoice(frm) ? 1 : 0,
	].join("|");
}

function mount_cgm_task_toolbar_buttons(frm) {
	if (frm.is_new() || !frm.doc.name) {
		return;
	}
	if (frm._cgm_task_action_busy || frm._cgm_completing_permit_application) {
		return;
	}
	const fingerprint = cgm_task_toolbar_fingerprint(frm);
	const has_buttons =
		frm.custom_buttons && Object.keys(frm.custom_buttons || {}).length > 0;
	if (frm._cgm_toolbar_fingerprint === fingerprint && has_buttons) {
		return;
	}
	// Settlement / status changed — allow ensure-complete to run again once.
	if (frm._cgm_toolbar_fingerprint !== fingerprint) {
		frm._cgm_ucr_finance_ensure_done = false;
		frm._cgm_entry_finance_ensure_done = false;
		frm._cgm_shipping_line_finance_ensure_done = false;
		frm._cgm_kpa_finance_ensure_done = false;
	}

	const ui = get_sea_task_ui(frm);
	frm.clear_custom_buttons();
	frm._cgm_toolbar_fingerprint = fingerprint;

	// Only Open Shipment Project stays top-level — everything else under Actions.
	if ((ui.is_sea_task || is_entry_application_step(frm)) && frm.doc.project) {
		const openProjectBtn = frm.add_custom_button(__("Open Shipment Project"), () => {
			frappe.set_route("Form", "Project", frm.doc.project);
		});
		openProjectBtn?.addClass?.("btn-primary");
	}

	if (ui.is_ucr_finance && frm.doc.status !== "Completed") {
		if (user_can_make_payment(frm) || user_can_verify_invoice(frm)) {
			unverified_invoice_lines_on_form(frm).forEach((inv) => {
				add_cgm_toolbar_button(
					frm,
					__("Verify {0}", [finance_line_display_label(inv)]),
					() => verify_ucr_finance_line(frm, "Invoice", inv.name)
				);
			});
			const rec = unverified_receipt_line_on_form(frm);
			if (rec) {
				add_cgm_toolbar_button(frm, __("Verify UCR Receipt"), () => {
					verify_ucr_finance_line(frm, "Receipt", rec.name);
				});
			}
		}
	}

	if (ui.is_entry_finance && frm.doc.status !== "Completed") {
		if (user_can_make_payment(frm) || user_can_verify_invoice(frm)) {
			unverified_invoice_lines_on_form(frm).forEach((inv) => {
				add_cgm_toolbar_button(
					frm,
					__("Verify {0}", [finance_line_display_label(inv)]),
					() => verify_entry_finance_line(frm, "Invoice", inv.name)
				);
			});
			const rec = unverified_receipt_line_on_form(frm);
			if (rec) {
				add_cgm_toolbar_button(frm, __("Verify Entry Slip Receipt"), () => {
					verify_entry_finance_line(frm, "Receipt", rec.name);
				});
			}
		}
	}

	if (ui.is_shipping_line_finance && frm.doc.status !== "Completed") {
		if (user_can_verify_invoice(frm) || user_can_make_payment(frm)) {
			unverified_invoice_lines_on_form(frm).forEach((inv) => {
				add_cgm_toolbar_button(
					frm,
					__("Verify {0}", [finance_line_display_label(inv)]),
					() => verify_app_finance_line(frm, "shipping_line", "Invoice", inv.name)
				);
			});
			const rec = unverified_receipt_line_on_form(frm);
			if (rec) {
				add_cgm_toolbar_button(frm, __("Verify Shipping Line Receipt"), () => {
					verify_app_finance_line(frm, "shipping_line", "Receipt");
				});
			}
		}
	}

	if (ui.is_kpa_finance && frm.doc.status !== "Completed") {
		if (user_can_make_payment(frm) || user_can_verify_invoice(frm)) {
			unverified_invoice_lines_on_form(frm).forEach((inv) => {
				add_cgm_toolbar_button(
					frm,
					__("Verify {0}", [finance_line_display_label(inv)]),
					() => verify_app_finance_line(frm, "kpa", "Invoice", inv.name)
				);
			});
			const rec = unverified_receipt_line_on_form(frm);
			if (rec) {
				add_cgm_toolbar_button(frm, __("Verify KPA Receipt"), () => {
					verify_app_finance_line(frm, "kpa", "Receipt", rec.name);
				});
			}
		}
	}

	if (
		frm.doc.docstatus === 0 &&
		frm.doc.status !== "Completed" &&
		frm.doc.status !== "Cancelled" &&
		!ui.hide_mark_complete &&
		!ui.show_payments &&
		!ui.show_permits
	) {
		add_cgm_toolbar_button(frm, __("Mark Completed"), async () => {
			await frm.set_value("completed_by", frappe.session.user);
			await frm.set_value("completed_on", frappe.datetime.now_datetime());
			await frm.set_value("status", "Completed");
			await frm.save();
		});
	}

	add_client_paid_application_mark_complete_button(frm, ui);

	// On completed permit / app↔finance application tasks the dedicated
	// "Add more…" buttons already reopen and unlock docs — skip generic Re-open.
	const has_dedicated_add_more =
		(ui.show_permits && is_permit_application_step(frm)) ||
		ui.is_ucr_application ||
		ui.is_entry_application ||
		ui.is_shipping_line_application ||
		ui.is_kpa_application;

	if (
		frm.doc.status === "Completed" &&
		!frm.is_new() &&
		(is_sea_clearance_task(frm) || frm.doc.custom_sequence_no) &&
		!has_dedicated_add_more
	) {
		add_cgm_toolbar_button(frm, __("Re-open Task"), () => {
			frappe.confirm(
				__(
					"Re-open this completed task so you can attach or replace documents? " +
						"You will need to mark it complete again when finished."
				),
				() => {
					frappe.call({
						method:
							"cgm_shipping.cgm_worldwide_shipping.customizations.task.reopen_completed_task",
						args: {
							task_name: frm.doc.name,
							reason: "Reopened to correct or replace attachments",
						},
						freeze: true,
						freeze_message: __("Re-opening task…"),
						callback(r) {
							if (r.exc || !r.message) {
								return;
							}
							frappe.show_alert({
								message: __(r.message.message || "Task reopened."),
								indicator: r.message.reopened ? "orange" : "blue",
							});
							frm.reload_doc();
						},
					});
				}
			);
		});
	}

	if (
		is_permit_application_step(frm) &&
		frm.doc.status !== "Completed" &&
		frm.doc.custom_client_paid_directly
	) {
		add_cgm_toolbar_button(frm, __("Mark Completed"), async () => {
			await frm.set_value("completed_by", frappe.session.user);
			await frm.set_value("completed_on", frappe.datetime.now_datetime());
			await frm.set_value("status", "Completed");
			await frm.save();
		});
	}

	if (
		is_pre_clearance_permit_application_step(frm) &&
		frm.doc.status !== "Completed" &&
		!frm.doc.custom_client_paid_directly &&
		frm.doc.custom_permit_invoices_submitted
	) {
		add_cgm_toolbar_button(frm, __("Complete Pre-Clearance Permits Task"), () => {
			complete_permit_application_task_from_form(frm);
		});
	}

	if (
		is_post_clearance_permit_application_step(frm) &&
		frm.doc.status !== "Completed" &&
		!frm.doc.custom_client_paid_directly &&
		frm.doc.custom_permit_invoices_submitted
	) {
		add_cgm_toolbar_button(frm, __("Complete Post-Clearance Permits Task"), () => {
			complete_permit_application_task_from_form(frm);
		});
	}

	if (ui.show_permits && is_permit_application_step(frm) && frm.doc.status === "Completed") {
		add_cgm_toolbar_button(frm, __("Add more permits / invoices"), () => {
			frappe.call({
				method: "cgm_shipping.cgm_worldwide_shipping.customizations.task.reopen_task_for_permit_attachments",
				args: { task_name: frm.doc.name },
				callback(r) {
					if (!r.exc) {
						const fin = r.message?.finance_task;
						frappe.show_alert({
							message: fin
								? __(
										"Task re-opened. Add a new Local row (tick <b>Amendment</b> to keep the first payment) with the new invoice and save — Finance will verify and pay on {0}.",
										[fin]
								  )
								: __(
										"Task re-opened. Add a new Local row (tick <b>Amendment</b> for an extra invoice on the same permit type) and save — Finance will be notified."
								  ),
							indicator: "orange",
						});
						frm.reload_doc();
					}
				},
			});
		});
	}

	const is_app_finance_application =
		ui.is_ucr_application ||
		ui.is_entry_application ||
		ui.is_shipping_line_application ||
		ui.is_kpa_application;
	if (is_app_finance_application && frm.doc.status !== "Cancelled") {
		const has_primary_invoice = get_invoice_finance_lines(frm).some(
			(r) => r.attachment && !cint(r.is_amendment)
		);
		if (has_primary_invoice || frm.doc.status === "Completed") {
			show_add_amendment_invoice_button(frm);
		}
	}
	if (is_app_finance_application && frm.doc.status === "Completed") {
		add_cgm_toolbar_button(frm, __("Replace primary invoice"), () => {
			frappe.call({
				method:
					"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.reopen_application_task_for_more_documents",
				args: { task_name: frm.doc.name },
				callback(r) {
					if (!r.exc) {
						frappe.show_alert({
							message: __(
								"Task re-opened. Replace the primary invoice attachment and save — Finance will verify and pay. " +
									"To keep the first payment and add another invoice, use <b>Add amendment invoice</b> instead."
							),
							indicator: "orange",
						});
						frm.reload_doc();
					}
				},
			});
		});
	}

	if (is_permit_payment_pattern(frm)) {
		show_permit_finance_journal_entry_view_buttons(frm);
	} else {
		get_invoice_finance_lines(frm).forEach((row) => {
			if (row.journal_entry) {
				add_cgm_toolbar_button(
					frm,
					__("View Journal Entry — {0}", [finance_line_display_label(row)]),
					() => frappe.set_route("Form", "Journal Entry", row.journal_entry)
				);
			}
		});
		if (
			frm.doc.custom_journal_entry &&
			!get_invoice_finance_lines(frm).some((r) => r.journal_entry === frm.doc.custom_journal_entry)
		) {
			add_cgm_toolbar_button(frm, __("View Journal Entry"), () => {
				frappe.set_route("Form", "Journal Entry", frm.doc.custom_journal_entry);
			});
		}
	}

	const permit_finance_has_unpaid =
		is_permit_payment_pattern(frm) &&
		permit_finance_rows_on_form(frm).some(
			(r) =>
				r.permit_type &&
				r.payment_invoice &&
				!r.journal_entry &&
				!cint(r.client_reported_paid) &&
				!cint(r.client_paid_directly)
		);
	const app_finance_unpaid_lines = unpaid_verified_invoice_lines_on_form(frm);
	const app_finance_needs_payment =
		(ui.is_ucr_finance ||
			ui.is_entry_finance ||
			ui.is_shipping_line_finance ||
			ui.is_kpa_finance) &&
		app_finance_unpaid_lines.length > 0;

	if (
		is_finance_department_task(frm) &&
		user_can_make_payment(frm) &&
		frm.doc.status !== "Cancelled" &&
		(frm.doc.status !== "Completed" || permit_finance_has_unpaid || app_finance_needs_payment)
	) {
		if (is_permit_payment_pattern(frm)) {
			if (!frm.doc.custom_client_paid_directly) {
				setup_permit_finance_make_payment_buttons(frm);
			}
		} else if (is_app_finance_payment_step(frm, ui)) {
			if (app_finance_unpaid_lines.length) {
				setup_app_finance_make_payment_buttons(frm, app_finance_unpaid_lines);
				setup_app_finance_client_will_pay_buttons(frm, app_finance_unpaid_lines);
			}
		} else if (!frm.doc.custom_journal_entry && !frm.doc.custom_client_paid_directly) {
			add_cgm_toolbar_button(frm, __("Make Payment"), () =>
				open_journal_entry_payment_dialog(frm)
			);
		}
	}

	setup_client_inspection_buttons(frm);

	const line_client_pays = form_has_client_paid_invoice_line(frm);
	if (
		is_finance_department_task(frm) &&
		frm.doc.project &&
		frm.doc.status !== "Cancelled" &&
		line_client_pays &&
		(user_can_verify_invoice(frm) ||
			user_can_make_payment(frm) ||
			user_can_confirm_client_paid(frm)) &&
		finance_task_has_shareable_invoice(frm)
	) {
		const already =
			finance_task_has_already_shared_invoice(frm) &&
			!finance_task_has_unshared_verified_invoice(frm);
		add_cgm_toolbar_button(
			frm,
			already ? __("Notify Client Again") : __("Share Invoice with Client"),
			() => share_invoices_with_client_from_form(frm)
		);
	}

	if (
		is_permit_finance_step(frm) &&
		frm.doc.status !== "Cancelled" &&
		(frm.doc.status !== "Completed" || permit_rows_pending_invoice_verification(frm).length) &&
		user_can_verify_invoice(frm) &&
		permit_rows_pending_invoice_verification(frm).length
	) {
		add_cgm_toolbar_button(frm, __("Verify Invoices"), () => {
			verify_all_permit_invoices_from_form(frm);
		});
	}
}

function add_cgm_toolbar_button(frm, label, fn, opts = {}) {
	const btn = frm.add_custom_button(label, fn, CGM_ACTION_GROUP);
	if (btn) {
		frm.page.set_inner_btn_group_as_primary(CGM_ACTION_GROUP);
	}
	return btn;
}

function hide_ucr_legacy_fields(frm) {
	UCR_LEGACY_FIELDNAMES.forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.set_df_property(fieldname, "hidden", 1);
		}
	});
}

function configure_ucr_finance_fields(frm, ui) {
	if (
		ui.is_ucr_finance ||
		ui.is_entry_finance ||
		ui.is_shipping_line_finance ||
		ui.is_kpa_finance ||
		ui.show_finance_lines
	) {
		hide_ucr_legacy_fields(frm);
	}
}

function ensure_finance_permit_rows_on_form(frm) {
	if (frm._cgm_finance_permit_rows_ensuring) {
		return;
	}
	if ((frm.doc.custom_task_permits || []).length) {
		return;
	}
	frm._cgm_finance_permit_rows_ensuring = true;
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.workflow.ensure_finance_permit_rows",
		args: { task_name: frm.doc.name },
		callback(r) {
			frm._cgm_finance_permit_rows_ensuring = false;
			if (!r.exc && r.message?.rows) {
				frm.reload_doc();
			}
		},
		error() {
			// Reset the guard so a transient failure doesn't block future retries.
			frm._cgm_finance_permit_rows_ensuring = false;
		},
	});
}

function ensure_ucr_finance_lines_on_form(frm) {
	if (get_finance_line(frm, "Receipt") || frm._cgm_finance_lines_ensuring) {
		return;
	}
	frm._cgm_finance_lines_ensuring = true;
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.workflow.ensure_ucr_finance_lines",
		args: { task_name: frm.doc.name },
		callback(r) {
			frm._cgm_finance_lines_ensuring = false;
			if (!r.exc && r.message?.added) {
				frm.reload_doc();
			}
		},
		error() {
			frm._cgm_finance_lines_ensuring = false;
		},
	});
}

function set_task_intro(frm, message, color = "blue") {
	// set_intro() appends a message block on every call, so clear first then set
	// once. Routing all intro updates through here keeps exactly one banner across
	// repeated refreshes and async callbacks.
	frm.set_intro("");
	if (message) {
		frm.set_intro(message, color);
	}
}

function load_ucr_declarant_workflow_status(frm) {
	if (frm._cgm_declarant_status_loading || frm._cgm_declarant_status_loaded) {
		return;
	}
	frm._cgm_declarant_status_loading = true;
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.workflow.get_ucr_declarant_workflow_status",
		args: { task_name: frm.doc.name },
		callback(r) {
			frm._cgm_declarant_status_loading = false;
			if (r.exc || !r.message) {
				set_task_intro(
					frm,
					__(
						"Could not load UCR workflow status. Refresh the page or contact support if this persists."
					),
					"orange"
				);
				return;
			}
			frm._cgm_declarant_status = r.message;
			frm._cgm_declarant_status_loaded = true;
			if (r.message.task_status === "Completed" && frm.doc.status !== "Completed") {
				frappe.show_alert({
					message: __("Create UCR (IDF) task completed"),
					indicator: "green",
				});
				frm.reload_doc();
				return;
			}
			apply_ucr_application_intro(frm, r.message);
		},
		error() {
			frm._cgm_declarant_status_loading = false;
			set_task_intro(
				frm,
				__(
					"Could not load UCR workflow status. Refresh the page or contact support if this persists."
				),
				"orange"
			);
		},
	});
}

function apply_ucr_application_intro(frm, status) {
	if (!is_ucr_application_step(frm) || !frm.doc.project) {
		return;
	}
	status = status || {};
	let intro;
	if (status.task_status === "Completed" || frm.doc.status === "Completed") {
		intro = __("<b>All declarant documents are in place.</b> This task is <b>Completed</b>.");
	} else if (status.client_paid_directly && !status.idf_certificate_attached) {
		intro = __(
			"<b>Finance selected: Client will pay</b> (no company Journal Entry). " +
				"Finance verifies the invoice and uploads the client's receipt. " +
				"Attach the <b>IDF/UCR certificate</b> under <b>Clearance Documents</b> to complete this task."
		);
	} else if (status.application_ready_to_complete) {
		intro = __("<b>All declarant documents are in place.</b> Completing this task…");
	} else if (status.receipt_attached && !status.idf_certificate_attached) {
		intro = __(
			"<b>Attach the IDF/UCR certificate</b> under <b>Clearance Documents</b> to finish this task."
		);
	} else if (status.receipt_attached) {
		intro = __(
			"<b>UCR receipt uploaded by Finance.</b> Attach the IDF/UCR certificate under <b>Clearance Documents</b> to complete this task."
		);
	} else if (status.payment_made) {
		intro = __(
			"<b>Finance has paid the UCR invoice.</b> Upload the supplier <b>UCR Receipt</b> on the finance payment task " +
				"(same department that attached the invoice). " +
				"When the certificate is issued, attach it under <b>Clearance Documents</b>."
		);
	} else if (status.invoice_verified) {
		intro = __(
			"<b>UCR invoice verified by Finance.</b> Waiting for payment. After payment, Finance uploads the " +
				"<b>UCR Receipt</b>; attach the certificate under <b>Clearance Documents</b> when issued."
		);
	} else if (status.invoice_submitted) {
		intro = __(
			"<b>UCR invoice submitted to Finance.</b> Waiting for Finance to verify and pay. " +
				"After payment, Finance uploads the supplier receipt on the finance task."
		);
	} else {
		intro = __(
			"<b>Declarant:</b> Attach <b>UCR Invoice</b> and save on " +
				"<b>Invoices & Receipts</b> - Finance is notified automatically. After payment, Finance uploads the " +
				"supplier receipt; attach the IDF/UCR certificate under <b>Clearance Documents</b> when issued."
		);
	}
	set_task_intro(frm, intro);
}

function toggle_permit_invoice_fields_for_origin(grid) {
	if (!grid) {
		return;
	}
	const payment_fields = [
		"payment_invoice",
		"invoice_amount",
		"invoice_uploaded_on",
		"invoice_uploaded_by",
		"invoice_verified",
		"payment_receipt",
		"receipt_verified",
		"journal_entry",
		"payment_entry",
		"payment_date",
		"payment_reference",
	];
	payment_fields.forEach((fn) => {
		grid.update_docfield_property(fn, "depends_on", 'eval:doc.origin != "Foreign"');
	});
}

function configure_permit_grid(frm) {
	const grid = frm.fields_dict.custom_task_permits?.grid;
	if (!grid) {
		return;
	}
	const seq = sea_task_sequence(frm);
	const hide_on_all = [
		"purchase_invoice",
		"payment_entry",
		"clearance_phase",
		"application_date",
		"approval_date",
		"issuing_body",
		"payment_date",
		"payment_reference",
	];
	hide_on_all.forEach((fn) => {
		grid.update_docfield_property(fn, "hidden", 1);
	});

	const invoices_sent = cint(frm.doc.custom_permit_invoices_submitted);
	const has_invoices = permit_rows_have_invoices(frm);
	const invoices_ready = invoices_sent || has_invoices;
	// Never lock the whole column — new rows (additional permits) must stay editable
	// even after earlier invoices were submitted / the task was completed.
	const can_upload_invoice = user_can_upload_invoice(frm);
	const can_upload_proof = can_upload_invoice || user_can_upload_certificate(frm);

	if (is_permit_application_step(frm, seq)) {
		frm.set_df_property("custom_task_permits", "read_only", 0);
		grid.cannot_add_rows = !can_upload_proof;
		grid.update_docfield_property("origin", "read_only", 0);
		grid.update_docfield_property(
			"payment_invoice",
			"read_only",
			can_upload_proof ? 0 : 1
		);
		grid.update_docfield_property(
			"invoice_amount",
			"read_only",
			can_upload_proof ? 0 : 1
		);
		// Declarant can see when Finance has verified; cannot tick it here.
		grid.update_docfield_property("invoice_verified", "hidden", !invoices_ready ? 1 : 0);
		grid.update_docfield_property("invoice_verified", "read_only", 1);
		grid.update_docfield_property("invoice_verified", "in_list_view", 1);
		grid.update_docfield_property("payment_receipt", "hidden", !invoices_ready ? 1 : 0);
		grid.update_docfield_property("payment_receipt", "read_only", 1);
		grid.update_docfield_property("permit_document", "hidden", 0);
		grid.update_docfield_property("permit_document", "read_only", can_upload_proof ? 0 : 1);
		grid.update_docfield_property("receipt_verified", "hidden", !invoices_ready ? 1 : 0);
		grid.update_docfield_property("receipt_verified", "read_only", 1);
		toggle_permit_invoice_fields_for_origin(grid);
	} else if (is_permit_finance_step(frm, seq)) {
		["payment_invoice", "purchase_invoice", "payment_entry", "permit_document"].forEach((fn) => {
			grid.update_docfield_property(fn, "read_only", 1);
		});
		grid.update_docfield_property("invoice_verified", "hidden", 0);
		grid.update_docfield_property("invoice_verified", "read_only", user_can_verify_invoice(frm) ? 0 : 1);
		grid.update_docfield_property("invoice_verified", "in_list_view", 1);
		grid.update_docfield_property("journal_entry", "hidden", 0);
		grid.update_docfield_property("journal_entry", "read_only", 1);
		grid.update_docfield_property("journal_entry", "in_list_view", 1);
		grid.update_docfield_property("payment_receipt", "hidden", 0);
		grid.update_docfield_property("payment_receipt", "read_only", user_can_upload_receipt(frm) ? 0 : 1);
		// Auto-stamped when Finance uploads the receipt — no separate verify step.
		grid.update_docfield_property("receipt_verified", "hidden", 1);
		grid.update_docfield_property("receipt_verified", "read_only", 1);
	}
	cgm_configure_permit_attach_grid(grid);
}

frappe.ui.form.on("Task Finance Line", {
	charge_item(frm, cdt, cdn) {
		if (frm.doctype !== "Task") {
			return;
		}
		const row = locals[cdt][cdn];
		if (!row.charge_item) {
			return;
		}
		frappe.db.get_value(
			"Clearance Charge Item",
			row.charge_item,
			["charge_name", "line_type", "payment_kind", "purchase_item"],
			(r) => {
				if (!r) {
					return;
				}
				frappe.model.set_value(cdt, cdn, "line_label", r.charge_name || row.charge_item);
				if (r.line_type) {
					frappe.model.set_value(cdt, cdn, "line_type", r.line_type);
				}
				if (r.payment_kind) {
					frappe.model.set_value(cdt, cdn, "payment_item", r.payment_kind);
				}
				if (r.purchase_item && row.line_type === "Invoice") {
					frappe.model.set_value(cdt, cdn, "item_code", r.purchase_item);
				}
			}
		);
	},
	form_render(frm, cdt, cdn) {
		if (frm.doctype !== "Task") {
			return;
		}
		const row = locals[cdt][cdn];
		const grid_row = frm.fields_dict.custom_task_finance_lines?.grid?.grid_rows_by_docname?.[cdn];
		if (!grid_row) {
			return;
		}
		const seq = sea_task_sequence(frm);
		const is_app =
			is_ucr_application_step(frm, seq) ||
			is_entry_application_step(frm, seq) ||
			is_shipping_line_application_step(frm, seq) ||
			is_kpa_application_step(frm, seq);
		const is_fin =
			is_ucr_finance_step(frm, seq) ||
			is_entry_finance_step(frm, seq) ||
			is_shipping_line_finance_step(frm, seq) ||
			is_kpa_finance_step(frm, seq);
		let attachment_editable = null;
		let verified_editable = null;
		if (is_app && (row.line_type === "Receipt" || row.line_type === "POP")) {
			if (is_shipping_line_application_step(frm, seq) && row.line_type === "Receipt") {
				attachment_editable = user_can_upload_receipt(frm);
				verified_editable = false;
			} else {
				attachment_editable = false;
				verified_editable = false;
			}
		}
		if (is_fin && row.line_type === "Invoice") {
			attachment_editable = false;
		}
		if (is_fin && row.line_type === "POP") {
			attachment_editable = user_can_upload_pop(frm);
			verified_editable = false;
		}
		if (is_fin && row.line_type === "Receipt") {
			attachment_editable = user_can_upload_receipt(frm);
		}
		// Skip no-op toggle_editable — it rebuilds Attach/Clear and flickers.
		const edit_key = `${row.line_type}|${attachment_editable}|${verified_editable}`;
		if (grid_row._cgm_finance_edit_key === edit_key) {
			return;
		}
		grid_row._cgm_finance_edit_key = edit_key;
		if (attachment_editable !== null) {
			grid_row.toggle_editable("attachment", attachment_editable);
		}
		if (verified_editable !== null) {
			grid_row.toggle_editable("verified", verified_editable);
		}
	},
	attachment(frm, cdt, cdn) {
		if (frm.doctype !== "Task") {
			return;
		}
		const row = locals[cdt][cdn];
		if ((row.line_type === "Receipt" || row.line_type === "POP") && (
			is_ucr_application_step(frm) ||
			is_entry_application_step(frm) ||
			is_shipping_line_application_step(frm) ||
			is_kpa_application_step(frm)
		)) {
			if (is_shipping_line_application_step(frm) && row.line_type === "Receipt") {
				// Documentation attaches receipt here after POP is mirrored from Finance.
			} else if (is_shipping_line_application_step(frm) && row.line_type === "POP") {
				frappe.show_alert({
					message: __(
						"POP is attached by Finance (or the client portal) and shown here automatically."
					),
					indicator: "orange",
				});
				return;
			} else {
				frappe.show_alert({
					message: is_shipping_line_application_step(frm)
						? __(
								"POP and receipt are attached on the finance payment task after payment."
							)
						: __(
								"Finance uploads payment receipts on the finance payment task after paying."
							),
					indicator: "orange",
				});
				return;
			}
		}
		const is_fin =
			is_ucr_finance_step(frm) ||
			is_entry_finance_step(frm) ||
			is_shipping_line_finance_step(frm) ||
			is_kpa_finance_step(frm);
		if (is_ucr_application_step(frm) && row.attachment) {
			if (row.line_type === "Invoice") {
				frappe.show_alert({
					message: __("UCR invoice saved - Finance will be notified when you save."),
					indicator: "green",
				});
			}
		}
		if (is_entry_application_step(frm) && row.attachment) {
			if (row.line_type === "Invoice") {
				frappe.show_alert({
					message: __("Entry Slip invoice saved - Finance will be notified when you save."),
					indicator: "green",
				});
			}
		}
		if (is_shipping_line_application_step(frm) && row.attachment) {
			if (row.line_type === "Invoice") {
				frappe.show_alert({
					message: __("Shipping Line invoice saved - Finance will be notified when you save."),
					indicator: "green",
				});
			}
		}
		if (is_kpa_application_step(frm) && row.attachment) {
			if (row.line_type === "Invoice") {
				frappe.show_alert({
					message: __("KPA invoice saved - Finance will be notified when you save."),
					indicator: "green",
				});
			}
		}
		if (is_fin && row.line_type === "POP" && row.attachment) {
			frappe.show_alert({
				message: __(
					"POP saved — Documentation can attach the Shipping Line Receipt using this proof."
				),
				indicator: "green",
			});
		}
		if (is_fin && row.line_type === "Receipt" && row.attachment) {
			frappe.show_alert({
				message: is_shipping_line_finance_step(frm)
					? __("Receipt saved — Finance must verify it to complete this task.")
					: __("Receipt saved — Declarant can view it on the application task."),
				indicator: "green",
			});
		}
		// Always save so Completed tasks can reopen Finance / sync receipts.
		// Skip while soft-sync is applying remote rows (avoids TimestampMismatchError).
		if (frm._cgm_skip_finance_line_autosave) {
			return;
		}
		if (!row.attachment) {
			return;
		}
		// Attach in child grids sometimes updates the control without dirtying the form.
		frm.dirty();
		// Refresh lock timestamp first — onload heal / POP mirror may have bumped it.
		frappe.db.get_value("Task", frm.doc.name, "modified").then((r) => {
			const latest = r?.message?.modified;
			if (latest) {
				frm.doc.modified = latest;
			}
			if (frm._cgm_skip_finance_line_autosave) {
				return;
			}
			if (!frm.is_dirty()) {
				frm.dirty();
			}
			frm.save().catch((e) => {
				const msg = (e && (e.message || e)) || "";
				if (String(msg).includes("modified after you have opened")) {
					frappe.show_alert({
						message: __("Document was updated elsewhere — refreshing…"),
						indicator: "orange",
					});
					frm.reload_doc();
				}
			});
		});
	},

	verified(frm, cdt, cdn) {
		if (frm.doctype !== "Task" || frm.doc.status === "Completed") {
			return;
		}
		const row = locals[cdt][cdn];
		if (is_ucr_application_step(frm)) {
			frappe.show_alert({
				message: __("Finance verifies the UCR invoice on the Finance pays UCR task."),
				indicator: "orange",
			});
			const inv = get_finance_line(frm, "Invoice");
			const verified = inv?.verified || frm.doc.custom_ucr_invoice_verified ? 1 : 0;
			if (cint(row.verified) !== verified) {
				frappe.model.set_value(cdt, cdn, "verified", verified);
			}
			return;
		}
		if (is_entry_application_step(frm)) {
			frappe.show_alert({
				message: __("Finance verifies the Entry Slip invoice on the Finance Pays Entry Slip task."),
				indicator: "orange",
			});
			const inv = get_finance_line(frm, "Invoice");
			if (cint(row.verified) !== cint(inv?.verified)) {
				frappe.model.set_value(cdt, cdn, "verified", inv?.verified ? 1 : 0);
			}
			return;
		}
		if (is_shipping_line_application_step(frm)) {
			frappe.show_alert({
				message: __(
					"Finance verifies the Shipping Line invoice on the Finance pays Shipping Line Charges task."
				),
				indicator: "orange",
			});
			const inv = get_finance_line(frm, "Invoice");
			if (cint(row.verified) !== cint(inv?.verified)) {
				frappe.model.set_value(cdt, cdn, "verified", inv?.verified ? 1 : 0);
			}
			return;
		}
		if (is_kpa_application_step(frm)) {
			frappe.show_alert({
				message: __(
					"Finance verifies the KPA invoice on the Finance pays KPA Invoice task."
				),
				indicator: "orange",
			});
			const inv = get_finance_line(frm, "Invoice");
			if (cint(row.verified) !== cint(inv?.verified)) {
				frappe.model.set_value(cdt, cdn, "verified", inv?.verified ? 1 : 0);
			}
			return;
		}
		if (row.verified) {
			frappe.model.set_value(cdt, cdn, "verified_by", frappe.session.user);
			frappe.model.set_value(cdt, cdn, "verified_on", frappe.datetime.now_datetime());
		}
		frm.save().then(() => {
			if (is_ucr_finance_step(frm)) {
				ensure_ucr_finance_task_completed_on_form(frm);
			}
			if (is_entry_finance_step(frm)) {
				ensure_entry_finance_task_completed_on_form(frm);
			}
			if (is_shipping_line_finance_step(frm)) {
				ensure_app_finance_task_completed_on_form(frm, "shipping_line");
			}
			if (is_kpa_finance_step(frm)) {
				ensure_app_finance_task_completed_on_form(frm, "kpa");
			}
		});
	},
});

frappe.ui.form.on("Permit Register", {
	form_render(frm, cdt, cdn) {
		if (frm.doctype !== "Task" || !is_permit_application_step(frm)) {
			return;
		}
		const row = locals[cdt][cdn];
		const grid_row = frm.fields_dict.custom_task_permits?.grid?.grid_rows_by_docname?.[cdn];
		if (!grid_row || !row) {
			return;
		}
		const can_upload =
			user_can_upload_invoice(frm) ||
			user_can_upload_certificate(frm) ||
			frm.doc.owner === frappe.session.user;
		// Lock invoice fields only on rows Finance has already verified or paid;
		// new additional permit rows stay editable (including on Completed tasks).
		// Client-pays still allows invoice upload until verified.
		const row_locked =
			Boolean(cint(row.invoice_verified)) ||
			Boolean(row.journal_entry) ||
			Boolean(row.payment_entry);
		const invoice_editable = can_upload && !row_locked;
		grid_row.toggle_editable("origin", !row_locked);
		grid_row.toggle_editable("payment_invoice", invoice_editable);
		grid_row.toggle_editable("invoice_amount", invoice_editable);
		grid_row.toggle_editable("permit_document", can_upload);
	},

	custom_task_permits_add(frm, cdt, cdn) {
		if (frm.doctype !== "Task") {
			return;
		}
		const seq = sea_task_sequence(frm);
		frappe.model.set_value(
			cdt,
			cdn,
			"stage",
			get_permit_stage_for_seq(frm, seq)
		);
		frappe.model.set_value(cdt, cdn, "status", "Applied");
		// A new row has no invoice yet, so the invoice columns must be editable
		// again even if earlier invoices were already submitted (the column-wide
		// read-only is otherwise only re-evaluated on form refresh).
		configure_permit_grid(frm);
	},

	custom_task_permits_remove(frm) {
		if (frm.doctype !== "Task") {
			return;
		}
		configure_permit_grid(frm);
	},

	origin(frm, cdt, cdn) {
		if (frm.doctype !== "Task") {
			return;
		}
		const row = locals[cdt][cdn];
		if ((row.origin || "Local") === "Foreign") {
			[
				"payment_invoice",
				"invoice_amount",
				"invoice_verified",
				"payment_receipt",
				"receipt_verified",
				"journal_entry",
				"payment_entry",
				"payment_date",
				"payment_reference",
			].forEach((fn) => {
				if (row[fn]) {
					frappe.model.set_value(
						cdt,
						cdn,
						fn,
						fn === "invoice_verified" || fn === "receipt_verified" ? 0 : ""
					);
				}
			});
			frappe.show_alert({
				message: __(
					"Foreign permit — upload the Permit Certificate only (no invoice or payment)."
				),
				indicator: "blue",
			});
		}
		configure_permit_grid(frm);
	},

	payment_invoice(frm, cdt, cdn) {
		if (frm.doctype !== "Task") {
			return;
		}
		const row = locals[cdt][cdn];
		if (row.payment_invoice) {
			frappe.model.set_value(cdt, cdn, "status", "Invoice Submitted");
		}
		if (is_permit_application_step_for_stage(frm) && row.payment_invoice) {
			frappe.show_alert({
				message: __(
					"Permit invoice saved - Finance will be notified when all invoices are attached and you save."
				),
				indicator: "green",
			});
		}
		// Save even when Completed so additional invoices reopen Finance.
		frm.save();
	},

	invoice_verified(frm, cdt, cdn) {
		if (frm.doctype !== "Task" || frm.doc.status === "Completed") {
			return;
		}
		const seq = sea_task_sequence(frm);
		if (!is_permit_finance_step(frm, seq)) {
			return;
		}
		if (!user_can_verify_invoice(frm)) {
			frappe.show_alert({
				message: __("Only the configured Verify Invoice role group can verify permit invoices."),
				indicator: "orange",
			});
			frappe.model.set_value(cdt, cdn, "invoice_verified", 0);
			return;
		}
		const row = locals[cdt][cdn];
		if (cint(row.invoice_verified) && !row.payment_invoice) {
			frappe.model.set_value(cdt, cdn, "invoice_verified", 0);
			frappe.msgprint(__("Attach a Permit Invoice before verifying."));
			return;
		}
		if (cint(row.invoice_verified)) {
			frappe.model.set_value(cdt, cdn, "status", "Invoice Verified");
			frappe.show_alert({
				message: __("{0} invoice verified — you can Make Payment for this permit.", [
					row.permit_type || __("Permit"),
				]),
				indicator: "green",
			});
		}
		frm.save();
	},

	payment_receipt(frm, cdt, cdn) {
		if (frm.doctype !== "Task") {
			return;
		}
		const seq = sea_task_sequence(frm);
		if (!is_permit_finance_step(frm, seq) && !is_permit_application_step_for_stage(frm, seq)) {
			return;
		}
		const row = locals[cdt][cdn];
		if (row.payment_receipt) {
			frappe.model.set_value(cdt, cdn, "status", "Receipt Submitted");
			if (is_permit_finance_step(frm, seq)) {
				frappe.model.set_value(cdt, cdn, "receipt_verified", 1);
			} else {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.workflow.notify_finance_verify_receipts",
					args: { task_name: frm.doc.name },
				});
			}
		}
		// Always save so receipts sync to the Declarant application task.
		frm.save();
	},

	permit_document(frm, cdt, cdn) {
		if (frm.doctype !== "Task" || !is_permit_application_step_for_stage(frm)) {
			return;
		}
		const row = locals[cdt][cdn];
		if (row.permit_document && frm.doc.status !== "Completed") {
			frm.save();
		}
	},

	receipt_verified(frm, cdt, cdn) {
		if (frm.doctype !== "Task" || !is_permit_finance_step(frm)) {
			return;
		}
		if (frm._cgm_verifying_permit_receipts || frm.doc.status === "Completed") {
			return;
		}
		frm.save().then(() => {
			ensure_finance_permit_task_completed_on_form(frm);
		});
	},
});

function ensure_ucr_finance_task_completed_on_form(frm) {
	if (frm._cgm_finance_complete_checking || frm._cgm_ucr_finance_ensure_done) {
		return;
	}
	if (frm.doc.status === "Completed" || frm.doc.status === "Cancelled") {
		return;
	}
	// All attached invoices must be verified + settled (not only the primary row).
	const invoices = get_invoice_finance_lines(frm).filter((r) => r.attachment);
	if (
		!invoices.length ||
		invoices.some((r) => !cint(r.verified) || !invoice_line_settled_on_form(r, frm))
	) {
		return;
	}
	const rec = get_finance_line(frm, "Receipt");
	if (!rec?.verified || !rec?.attachment) {
		return;
	}
	frm._cgm_finance_complete_checking = true;
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.workflow.ensure_ucr_finance_task_completed",
		args: { task_name: frm.doc.name },
		callback(r) {
			frm._cgm_finance_complete_checking = false;
			if (r.exc || !r.message) {
				return;
			}
			// Only toast when this call newly completed the task — never when the
			// server was already Completed / form was stale Open (reload loops).
			if (r.message.completed && r.message.status === "Completed") {
				frm._cgm_ucr_finance_ensure_done = true;
				frappe.show_alert({
					message: __("Finance pays UCR task completed"),
					indicator: "green",
				});
				if (frm.doc.status !== "Completed") {
					frm.reload_doc();
				}
				return;
			}
			// Remember no-op so refresh does not keep re-calling ensure.
			frm._cgm_ucr_finance_ensure_done = true;
		},
		error() {
			frm._cgm_finance_complete_checking = false;
		},
	});
}

function verify_ucr_finance_line(frm, line_type, finance_line_name) {
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.workflow.verify_ucr_finance_line",
		args: { task_name: frm.doc.name, line_type, finance_line_name },
		freeze: true,
		callback(r) {
			if (!r.exc) {
				frappe.show_alert({
					message: r.message?.message || __("Verified"),
					indicator: "green",
				});
				if (r.message?.completed && r.message?.task_status === "Completed") {
					frm._cgm_ucr_finance_ensure_done = true;
					frappe.show_alert({
						message: __("Finance pays UCR task completed"),
						indicator: "green",
					});
				} else {
					frm._cgm_ucr_finance_ensure_done = false;
				}
				frm.reload_doc();
			}
		},
	});
}

function ensure_entry_finance_lines_on_form(frm) {
	if (get_finance_line(frm, "Receipt") || frm._cgm_entry_finance_lines_ensuring) {
		return;
	}
	frm._cgm_entry_finance_lines_ensuring = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.ensure_application_finance_lines",
		args: { task_name: frm.doc.name, profile_key: "entry" },
		callback(r) {
			frm._cgm_entry_finance_lines_ensuring = false;
			if (!r.exc && r.message?.added) {
				frm.reload_doc();
			}
		},
		error() {
			frm._cgm_entry_finance_lines_ensuring = false;
		},
	});
}

function load_entry_declarant_workflow_status(frm) {
	if (frm._cgm_entry_declarant_status_loading || frm._cgm_entry_declarant_status_loaded) {
		return;
	}
	frm._cgm_entry_declarant_status_loading = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.get_application_declarant_workflow_status",
		args: { task_name: frm.doc.name, profile_key: "entry" },
		callback(r) {
			frm._cgm_entry_declarant_status_loading = false;
			if (r.exc || !r.message) {
				set_task_intro(
					frm,
					__(
						"Could not load Entry workflow status. Refresh the page or contact support if this persists."
					),
					"orange"
				);
				return;
			}
			frm._cgm_entry_declarant_status = r.message;
			frm._cgm_entry_declarant_status_loaded = true;
			if (r.message.task_status === "Completed" && frm.doc.status !== "Completed") {
				frappe.show_alert({
					message: __("Create Entry task completed"),
					indicator: "green",
				});
				frm.reload_doc();
				return;
			}
			apply_entry_application_intro(frm, r.message);
		},
		error() {
			frm._cgm_entry_declarant_status_loading = false;
			set_task_intro(
				frm,
				__(
					"Could not load Entry workflow status. Refresh the page or contact support if this persists."
				),
				"orange"
			);
		},
	});
}

function apply_entry_application_intro(frm, status) {
	if (!is_entry_application_step(frm) || !frm.doc.project) {
		return;
	}
	status = status || {};
	const invoiceLabel = status.invoice_label || __("Entry Slip Invoice");
	const receiptLabel = status.receipt_label || __("Entry Slip Receipt");
	let intro;
	if (status.task_status === "Completed" || frm.doc.status === "Completed") {
		intro = __("<b>All declarant documents are in place.</b> This task is <b>Completed</b>.");
	} else if (status.application_ready_to_complete) {
		intro = __("<b>Entry Slip invoice verified by Finance.</b> Completing this task…");
	} else if (status.client_paid_directly && status.invoice_verified) {
		intro = __(
			"<b>Finance verified the invoice</b> (client-pays path). Completing this task…"
		);
	} else if (status.client_paid_directly) {
		intro = __(
			"<b>Finance selected: Client will pay</b> (no company Journal Entry). " +
				"Waiting for Finance to verify the <b>{0}</b> — this task completes when they do.",
			[invoiceLabel]
		);
	} else if (status.invoice_verified) {
		intro = __(
			"<b>{0} verified by Finance.</b> Completing this task… Finance continues payment and " +
				"<b>{1}</b> on the finance task. You may still attach the ENTRY document under " +
				"<b>Clearance Documents</b> when issued.",
			[invoiceLabel, receiptLabel]
		);
	} else if (status.invoice_submitted) {
		intro = __(
			"<b>{0} submitted to Finance.</b> Waiting for Finance to verify — this task completes " +
				"when the invoice is approved.",
			[invoiceLabel]
		);
	} else {
		intro = __(
			"<b>Declarant:</b> Attach <b>{0}</b> and save on " +
				"<b>Invoices & Receipts</b> — Finance is notified automatically. " +
				"This task completes once Finance verifies the invoice. " +
				"ENTRY document under <b>Clearance Documents</b> remains optional when issued.",
			[invoiceLabel]
		);
	}
	set_task_intro(frm, intro);
}

function ensure_entry_finance_task_completed_on_form(frm) {
	if (frm._cgm_entry_finance_complete_checking || frm._cgm_entry_finance_ensure_done) {
		return;
	}
	if (frm.doc.status === "Completed" || frm.doc.status === "Cancelled") {
		return;
	}
	const invoices = get_invoice_finance_lines(frm).filter((r) => r.attachment);
	if (
		!invoices.length ||
		invoices.some((r) => !cint(r.verified) || !invoice_line_settled_on_form(r, frm))
	) {
		return;
	}
	frm._cgm_entry_finance_complete_checking = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.ensure_application_finance_task_completed",
		args: { task_name: frm.doc.name, profile_key: "entry" },
		callback(r) {
			frm._cgm_entry_finance_complete_checking = false;
			if (r.exc || !r.message) {
				return;
			}
			if (r.message.completed && r.message.status === "Completed") {
				frm._cgm_entry_finance_ensure_done = true;
				frappe.show_alert({
					message: __("Finance Pays Entry Slip task completed"),
					indicator: "green",
				});
				if (frm.doc.status !== "Completed") {
					frm.reload_doc();
				}
				return;
			}
			frm._cgm_entry_finance_ensure_done = true;
		},
		error() {
			frm._cgm_entry_finance_complete_checking = false;
		},
	});
}

function verify_entry_finance_line(frm, line_type, finance_line_name) {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.verify_application_finance_line",
		args: {
			task_name: frm.doc.name,
			profile_key: "entry",
			line_type,
			finance_line_name,
		},
		freeze: true,
		callback(r) {
			if (!r.exc) {
				frappe.show_alert({
					message: r.message?.message || __("Verified"),
					indicator: "green",
				});
				if (r.message?.task_status === "Completed" && frm.doc.status !== "Completed") {
					frappe.show_alert({
						message: __("Finance Pays Entry Slip task completed"),
						indicator: "green",
					});
				}
				frm.reload_doc();
			}
		},
	});
}

function sync_app_finance_receipt_on_form(frm, profileKey) {
	if (!is_app_finance_finance_step(frm, undefined, profileKey) || frm.doc.status === "Completed") {
		return;
	}
	if (get_finance_line(frm, "Receipt")?.attachment) {
		return;
	}
	const key = `_cgm_${profileKey}_receipt_syncing`;
	if (frm[key]) {
		return;
	}
	frm[key] = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.sync_application_receipt_for_finance_task",
		args: { task_name: frm.doc.name, profile_key: profileKey },
		callback(r) {
			frm[key] = false;
			if (!r.exc && r.message?.synced) {
				frm.reload_doc();
			}
		},
		error() {
			frm[key] = false;
		},
	});
}

function ensure_app_finance_lines_on_form(frm, profileKey) {
	const ensuringKey = `_cgm_${profileKey}_finance_lines_ensuring`;
	const ensuredKey = `_cgm_${profileKey}_finance_lines_ensured`;
	if (frm[ensuringKey] || frm[ensuredKey]) {
		return;
	}
	const hasReceipt = !!get_finance_line(frm, "Receipt");
	const needsPop =
		profileKey === "shipping_line" && !get_finance_line(frm, "POP");
	if (hasReceipt && !needsPop) {
		frm[ensuredKey] = true;
		return;
	}
	frm[ensuringKey] = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.ensure_application_finance_lines",
		args: { task_name: frm.doc.name, profile_key: profileKey },
		callback(r) {
			frm[ensuringKey] = false;
			frm[ensuredKey] = true;
			if (!r.exc && r.message?.added) {
				frm._cgm_toolbar_fingerprint = null;
				frm.reload_doc();
			}
		},
		error() {
			frm[ensuringKey] = false;
		},
	});
}

function load_app_finance_declarant_status(frm, profileKey) {
	const loadingKey = `_cgm_${profileKey}_declarant_status_loading`;
	const loadedKey = `_cgm_${profileKey}_declarant_status_loaded`;
	const statusKey = `_cgm_${profileKey}_declarant_status`;
	if (frm[loadingKey] || frm[loadedKey]) {
		return;
	}
	frm[loadingKey] = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.get_application_declarant_workflow_status",
		args: { task_name: frm.doc.name, profile_key: profileKey },
		callback(r) {
			frm[loadingKey] = false;
			if (r.exc || !r.message) {
				set_task_intro(
					frm,
					__(
						"Could not load workflow status. Refresh the page or contact support if this persists."
					),
					"orange"
				);
				return;
			}
			frm[statusKey] = r.message;
			frm[loadedKey] = true;
			// Never full-reload from a status poll — that fought onload heal and
			// flickered Open↔Completed / POP rows. Intro follows the form doc.
			apply_app_finance_application_intro(frm, r.message, profileKey);
		},
		error() {
			frm[loadingKey] = false;
			set_task_intro(
				frm,
				__(
					"Could not load workflow status. Refresh the page or contact support if this persists."
				),
				"orange"
			);
		},
	});
}

const CLIENT_PAID_FIELDS = [
	"custom_client_paid_directly",
	"custom_client_paid_confirmed_by",
	"custom_client_paid_confirmed_on",
];

function is_client_paid_application_step(frm) {
	const seq = sea_task_sequence(frm);
	return (
		is_ucr_application_step(frm, seq) ||
		is_entry_application_step(frm, seq) ||
		is_app_finance_application_step(frm, seq, "shipping_line") ||
		is_app_finance_application_step(frm, seq, "kpa") ||
		is_permit_application_step(frm, seq)
	);
}

function set_client_paid_fields_hidden(frm, hidden) {
	CLIENT_PAID_FIELDS.forEach((fieldname) => {
		if (!frm.fields_dict[fieldname]) {
			return;
		}
		const df = frm.get_docfield(fieldname);
		// Skip no-op writes — set_df_property refreshes the control and layout deps.
		if (df && cint(df.hidden) === cint(hidden)) {
			return;
		}
		frm.set_df_property(fieldname, "hidden", hidden ? 1 : 0);
	});
}

function configure_client_paid_field(frm, ui) {
	// App-finance (UCR / Entry / SL / KPA): Client will pay lives on each Invoice row.
	// Permit finance still uses the task-level checkbox (plus per-permit row flags).
	ui = ui || get_sea_task_ui(frm);
	if (is_app_finance_payment_step(frm, ui)) {
		set_client_paid_fields_hidden(frm, 1);
		return;
	}
	// Application tasks for those flows: hide task-level mirror (intros / status cover it).
	if (
		ui.is_ucr_application ||
		ui.is_entry_application ||
		ui.is_shipping_line_application ||
		ui.is_kpa_application
	) {
		set_client_paid_fields_hidden(frm, 1);
		return;
	}

	// Finance confirms this on the payment task; the paired application task
	// mirrors it read-only so the owner knows no invoice handoff is coming.
	//
	// Sea seq lists load async. Until they arrive, ui.show_payments is false for
	// every sea task (empty fallback). Do not hide against that — it blanks
	// already-confirmed fields. Once confirmed, keep them visible from the doc
	// alone (no extra server call).
	const confirmed = Boolean(frm.doc.custom_client_paid_directly);
	if (is_sea_clearance_task(frm) && !frm._cgm_sea_seq_config) {
		if (confirmed) {
			set_client_paid_fields_hidden(frm, 0);
			if (frm.fields_dict.custom_client_paid_directly) {
				frm.set_df_property("custom_client_paid_directly", "read_only", 1);
			}
		} else {
			// Not confirmed yet — keep hidden until seq config classifies this step.
			set_client_paid_fields_hidden(frm, 1);
		}
		return;
	}

	const finance_step = Boolean(ui.show_payments);
	const mirrored = is_client_paid_application_step(frm) && confirmed;
	const show = finance_step || mirrored;
	set_client_paid_fields_hidden(frm, show ? 0 : 1);
	if (show && frm.fields_dict.custom_client_paid_directly) {
		const editable =
			finance_step && user_can_confirm_client_paid(frm) && frm.doc.status !== "Completed";
		frm.set_df_property("custom_client_paid_directly", "read_only", editable ? 0 : 1);
		const receiptOptional = Boolean(ui.is_entry_finance || ui.is_entry_application);
		frm.set_df_property(
			"custom_client_paid_directly",
			"description",
			finance_step
				? receiptOptional
					? __(
							"Tick when the client settles this fee (no company Journal Entry). " +
								"Still verify the invoice. Entry Slip Receipt is optional."
						)
					: __(
							"Tick when the client settles this fee (no company Journal Entry). " +
								"Still verify the invoice, then attach and verify the receipt before completing."
						)
				: receiptOptional
					? __(
							"Finance selected the client-pays path (no company Journal Entry). " +
								"They will verify your invoice; Entry Slip Receipt is optional."
						)
					: __(
							"Finance selected the client-pays path (no company Journal Entry). " +
								"They will verify your invoice and the payment receipt."
						)
		);
	}
}

function configure_shipping_line_deposit_grid(frm) {
	const grid = frm.fields_dict.custom_container_updates?.grid;
	if (!grid) {
		return;
	}
	frm.toggle_display("custom_section_container_updates", true);
	frm.toggle_display("custom_container_updates", true);
	// Configure once per form open — grid.refresh() on every Task.refresh
	// re-renders rows, fires render_complete, and makes toolbar buttons flicker.
	if (frm._cgm_shipping_line_deposit_grid_ready) {
		return;
	}
	["has_deposit", "deposit_amount"].forEach((fn) => {
		grid.update_docfield_property(fn, "hidden", 0);
		grid.update_docfield_property(fn, "in_list_view", 1);
	});
	frm._cgm_shipping_line_deposit_grid_ready = true;
	if (grid.wrapper) {
		grid.refresh();
	}
}

function configure_entry_arrival_mirror_grid(frm) {
	/** Create Entry container grid mirrors Project port-arrival confirm (read-only). */
	const grid = frm.fields_dict.custom_container_updates?.grid;
	if (!grid) {
		return;
	}
	frm.toggle_display("custom_section_container_updates", true);
	frm.toggle_display("custom_container_updates", true);
	if (frm._cgm_entry_arrival_mirror_grid_ready) {
		return;
	}
	grid.update_docfield_property("discharging_date", "hidden", 0);
	grid.update_docfield_property("discharging_date", "in_list_view", 1);
	grid.update_docfield_property("discharging_date", "read_only", 1);
	["container_number", "cargo_size", "current_status"].forEach((fn) => {
		grid.update_docfield_property(fn, "read_only", 1);
	});
	frm._cgm_entry_arrival_mirror_grid_ready = true;
	if (grid.wrapper) {
		grid.refresh();
	}
}

function application_status_for_client_paid(frm, ui) {
	if (ui.is_kpa_application) {
		return frm._cgm_kpa_declarant_status;
	}
	if (ui.is_shipping_line_application) {
		return frm._cgm_shipping_line_declarant_status;
	}
	if (ui.is_entry_application) {
		return frm._cgm_entry_declarant_status;
	}
	if (ui.is_ucr_application) {
		return frm._cgm_declarant_status;
	}
	return null;
}

function client_paid_application_needs_mark_complete(frm, ui) {
	/** KPA (no certificate) needs an explicit Mark Completed after client-paid.
	 * Shipping Line waits for Finance receipt verify — no early Mark Completed.
	 */
	if (frm.doc.status === "Completed" || frm.doc.status === "Cancelled") {
		return false;
	}
	if (!ui.is_kpa_application) {
		return false;
	}
	const status = application_status_for_client_paid(frm, ui) || {};
	const clientPaid =
		Boolean(frm.doc.custom_client_paid_directly) || Boolean(status.client_paid_directly);
	if (!clientPaid) {
		return false;
	}
	// Profiles with a certificate auto-complete once it is attached.
	if (status.certificate_required) {
		return false;
	}
	return true;
}

async function mark_application_task_completed(frm) {
	await frm.set_value("completed_by", frappe.session.user);
	await frm.set_value("completed_on", frappe.datetime.now_datetime());
	await frm.set_value("status", "Completed");
	await frm.save();
}

function add_client_paid_application_mark_complete_button(frm, ui) {
	if (!client_paid_application_needs_mark_complete(frm, ui)) {
		return;
	}
	add_cgm_toolbar_button(frm, __("Mark Completed"), () => mark_application_task_completed(frm));
}

function apply_app_finance_application_intro(frm, status, profileKey) {
	if (!is_app_finance_application_step(frm, undefined, profileKey) || !frm.doc.project) {
		return;
	}
	status = status || {};
	const profile = CGM_APP_FINANCE_PROFILES[profileKey] || {};
	const invoiceLabel = status.invoice_label || __("Invoice");
	const receiptLabel = status.receipt_label || __("Receipt");
	const uploadRole = profile.upload_role || __("Operations");
	const isShippingLine = profileKey === "shipping_line";
	let intro;
	// Form doc status wins — stale status.task_status caused "Completed" banners on Open tasks.
	if (frm.doc.status === "Completed") {
		intro = __("<b>All documents are in place.</b> This task is <b>Completed</b>.");
	} else if (status.client_paid_directly && !status.certificate_required) {
		intro = isShippingLine
			? __(
					"<b>Finance selected: Client will pay</b> (no company Journal Entry). " +
						"After the client/Finance shares <b>POP</b>, attach the <b>{0}</b> here. " +
						"Finance verifies the receipt — then this task and Finance complete together.",
					[receiptLabel]
				)
			: __(
					"<b>Finance selected: Client will pay</b> (no company Journal Entry). " +
						"Attach/replace the invoice as usual; Finance verifies and uploads the client's receipt. " +
						"Click <b>Mark Completed</b> when this application step is finished."
				);
		// Remount toolbar so Mark Completed survives form.refresh clearing custom buttons.
		if (!isShippingLine) {
			schedule_cgm_task_toolbar_buttons(frm);
		}
	} else if (status.client_paid_directly && status.certificate_required) {
		intro = __(
			"<b>Finance selected: Client will pay</b> (no company Journal Entry). " +
				"Finance verifies the invoice and uploads the client's receipt. " +
				"Attach the required certificate under <b>Clearance Documents</b> to complete this task."
		);
	} else if (status.application_ready_to_complete) {
		intro = __("<b>All documents are in place.</b> Completing this task…");
	} else if (status.receipt_attached) {
		intro = isShippingLine
			? status.receipt_verified
				? __("<b>All documents are in place.</b> Completing this task…")
				: __(
						"<b>{0} attached.</b> Waiting for Finance to verify it — then both Shipping Line tasks complete.",
						[receiptLabel]
					)
			: __("<b>{0} receipt uploaded.</b> This task will complete automatically.", [
					invoiceLabel,
				]);
	} else if (status.pop_attached && isShippingLine) {
		intro = __(
			"<b>POP is available.</b> Attach the <b>{0}</b> on this task (using the POP). Finance will verify it.",
			[receiptLabel]
		);
	} else if (status.payment_made) {
		intro = isShippingLine
			? __(
					"<b>Finance has paid the {0}.</b> Waiting for bank <b>POP</b> to appear here, then attach the <b>{1}</b>.",
					[invoiceLabel, receiptLabel]
				)
			: __(
					"<b>Finance has paid the {0}.</b> Finance will upload the supplier <b>{1}</b> on the finance task.",
					[invoiceLabel, receiptLabel]
				);
	} else if (status.invoice_verified) {
		intro = isShippingLine
			? __(
					"<b>{0} verified by Finance.</b> Waiting for payment / client POP. " +
						"Then attach the <b>{1}</b> here for Finance to verify.",
					[invoiceLabel, receiptLabel]
				)
			: __(
					"<b>{0} verified by Finance.</b> Waiting for payment. After payment, Finance uploads the " +
						"<b>{1}</b> on the finance task.",
					[invoiceLabel, receiptLabel]
				);
	} else if (status.invoice_submitted) {
		intro = isShippingLine
			? __(
					"<b>{0} submitted to Finance.</b> Waiting for Finance to verify and pay. " +
						"After POP appears here, attach the supplier receipt for Finance to verify.",
					[invoiceLabel]
				)
			: __(
					"<b>{0} submitted to Finance.</b> Waiting for Finance to verify and pay. " +
						"After payment, Finance uploads the supplier receipt on the finance task.",
					[invoiceLabel]
				);
	} else {
		intro = isShippingLine
			? __(
					"<b>{0}:</b> Attach <b>{1}</b> and save on " +
						"<b>Invoices & Receipts</b> - Finance is notified automatically. After payment, " +
						"POP appears here; then attach the receipt for Finance to verify.",
					[uploadRole, invoiceLabel]
				)
			: __(
					"<b>{0}:</b> Attach <b>{1}</b> and save on " +
						"<b>Invoices & Receipts</b> - Finance is notified automatically. After payment, Finance uploads the " +
						"supplier receipt.",
					[uploadRole, invoiceLabel]
				);
		if (isShippingLine) {
			intro +=
				"<br><br>" +
				__(
					"<b>Container deposits:</b> On <b>Container Updates</b>, tick <b>Has Deposit</b> " +
						"and enter the amount for each container that has a deposit. Leave unticked " +
						"when there is no deposit. Payment status updates automatically after Shipping Line finance is completed."
				);
		}
	}
	set_task_intro(frm, intro);
}

function ensure_app_finance_task_completed_on_form(frm, profileKey) {
	const checkingKey = `_cgm_${profileKey}_finance_complete_checking`;
	const doneKey = `_cgm_${profileKey}_finance_ensure_done`;
	if (frm[checkingKey] || frm[doneKey]) {
		return;
	}
	if (!is_app_finance_finance_step(frm, undefined, profileKey) || frm.doc.status === "Completed") {
		return;
	}
	const invoices = get_invoice_finance_lines(frm).filter((r) => r.attachment);
	if (
		!invoices.length ||
		invoices.some((r) => !cint(r.verified) || !invoice_line_settled_on_form(r, frm))
	) {
		return;
	}
	if (profileKey === "shipping_line") {
		const pop = get_finance_line(frm, "POP");
		const rec = get_finance_line(frm, "Receipt");
		if (!pop?.attachment || !rec?.attachment || !rec?.verified) {
			return;
		}
	} else {
		const rec = get_finance_line(frm, "Receipt");
		// KPA: receipt required when present on the row; settlement is per invoice line.
		if (rec?.attachment && !cint(rec.verified)) {
			return;
		}
	}
	frm[checkingKey] = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.ensure_application_finance_task_completed",
		args: { task_name: frm.doc.name, profile_key: profileKey },
		callback(r) {
			frm[checkingKey] = false;
			if (r.exc || !r.message) {
				return;
			}
			if (r.message.completed && r.message.status === "Completed") {
				frm[doneKey] = true;
				frappe.show_alert({
					message: __("Finance task completed"),
					indicator: "green",
				});
				if (frm.doc.status !== "Completed") {
					frm.reload_doc();
				}
				return;
			}
			frm[doneKey] = true;
		},
		error() {
			frm[checkingKey] = false;
		},
	});
}

function verify_app_finance_line(frm, profileKey, lineType, finance_line_name) {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.verify_application_finance_line",
		args: {
			task_name: frm.doc.name,
			profile_key: profileKey,
			line_type: lineType,
			finance_line_name,
		},
		freeze: true,
		callback(r) {
			if (!r.exc) {
				frappe.show_alert({
					message: r.message?.message || __("Verified"),
					indicator: "green",
				});
				frm.reload_doc();
			}
		},
	});
}

function ensure_shipping_line_finance_lines_on_form(frm) {
	ensure_app_finance_lines_on_form(frm, "shipping_line");
}

function load_shipping_line_declarant_workflow_status(frm) {
	load_app_finance_declarant_status(frm, "shipping_line");
}

function apply_shipping_line_application_intro(frm, status) {
	apply_app_finance_application_intro(frm, status, "shipping_line");
}

function ensure_shipping_line_finance_task_completed_on_form(frm) {
	ensure_app_finance_task_completed_on_form(frm, "shipping_line");
}

function verify_shipping_line_finance_line(frm, lineType) {
	verify_app_finance_line(frm, "shipping_line", lineType);
}

function user_can_make_payment(frm) {
	const perms = frm ? get_cgm_permissions(frm) : null;
	if (perms) {
		return !!perms.can_make_payment;
	}
	return CGM_TASK_PERMISSIONS_FALLBACK.can_make_payment.some((role) =>
		(frappe.user_roles || []).includes(role)
	);
}

function user_can_upload_receipt(frm) {
	const perms = frm ? get_cgm_permissions(frm) : null;
	if (perms) {
		return !!perms.can_upload_receipt;
	}
	return CGM_TASK_PERMISSIONS_FALLBACK.can_upload_receipt.some((role) =>
		(frappe.user_roles || []).includes(role)
	);
}

function user_can_upload_pop(frm) {
	const perms = frm ? get_cgm_permissions(frm) : null;
	if (perms && perms.can_upload_pop !== undefined) {
		return !!perms.can_upload_pop;
	}
	return CGM_TASK_PERMISSIONS_FALLBACK.can_upload_pop.some((role) =>
		(frappe.user_roles || []).includes(role)
	);
}

function user_can_verify_invoice(frm) {
	const perms = frm ? get_cgm_permissions(frm) : null;
	if (perms && perms.can_verify_invoice !== undefined) {
		return !!perms.can_verify_invoice;
	}
	return user_can_make_payment(frm);
}

function user_can_upload_invoice(frm) {
	const perms = frm ? get_cgm_permissions(frm) : null;
	if (perms && perms.can_upload_invoice !== undefined) {
		return !!perms.can_upload_invoice;
	}
	return CGM_TASK_PERMISSIONS_FALLBACK.can_upload_invoice.some((role) =>
		(frappe.user_roles || []).includes(role)
	) || frm?.doc?.owner === frappe.session.user;
}

function user_can_upload_certificate(frm) {
	const perms = frm ? get_cgm_permissions(frm) : null;
	if (perms && perms.can_upload_certificate !== undefined) {
		return !!perms.can_upload_certificate;
	}
	return user_can_upload_invoice(frm);
}

function user_can_confirm_client_paid(frm) {
	const perms = frm ? get_cgm_permissions(frm) : null;
	if (perms && perms.can_confirm_client_paid !== undefined) {
		return !!perms.can_confirm_client_paid;
	}
	return user_can_make_payment(frm);
}

// ─── Make Payment → draft Journal Entry (Finance department) ──────────────────

function is_finance_department_task(frm) {
	const finance_dept = get_finance_department(frm);
	return Boolean(finance_dept && frm.doc.department && frm.doc.department === finance_dept);
}

function journal_account_filters(frm, bank_or_cash) {
	const filters = { is_group: 0 };
	if (frm.doc.company) {
		filters.company = frm.doc.company;
	}
	if (bank_or_cash) {
		filters.account_type = ["in", ["Bank", "Cash"]];
	}
	return filters;
}

function show_permit_finance_journal_entry_view_buttons(frm) {
	permit_finance_rows_on_form(frm).forEach((row) => {
		if (!row.journal_entry) {
			return;
		}
		const label = cint(row.is_amendment)
			? __("{0} (amendment)", [row.permit_type])
			: row.permit_type;
		add_cgm_toolbar_button(frm, __("View Journal Entry — {0}", [label]), () => {
			frappe.set_route("Form", "Journal Entry", row.journal_entry);
		});
	});
}

function setup_permit_finance_make_payment_buttons(frm) {
	permit_finance_rows_on_form(frm).forEach((row) => {
		if (row.journal_entry || cint(row.client_reported_paid) || cint(row.client_paid_directly)) {
			return;
		}
		if (row.payment_invoice && !cint(row.invoice_verified)) {
			return;
		}
		const label = cint(row.is_amendment)
			? __("{0} (amendment)", [row.permit_type])
			: row.permit_type;
		add_cgm_toolbar_button(frm, __("Make Payment — {0}", [label]), () =>
			open_journal_entry_payment_dialog(frm, {
				permit_row_name: row.name,
				default_amount: row.invoice_amount,
				title_suffix: label,
			})
		);
	});
}

function setup_app_finance_make_payment_buttons(frm, unpaid_lines) {
	(unpaid_lines || unpaid_verified_invoice_lines_on_form(frm)).forEach((row) => {
		const label = finance_line_display_label(row);
		add_cgm_toolbar_button(frm, __("Make Payment — {0}", [label]), () =>
			open_journal_entry_payment_dialog(frm, {
				finance_line_name: row.name,
				title_suffix: label,
			})
		);
	});
}

function setup_app_finance_client_will_pay_buttons(frm, unpaid_lines) {
	if (!user_can_confirm_client_paid(frm)) {
		return;
	}
	(unpaid_lines || unpaid_verified_invoice_lines_on_form(frm)).forEach((row) => {
		if (!row.name || cint(row.client_paid_directly)) {
			return;
		}
		const label = finance_line_display_label(row);
		add_cgm_toolbar_button(frm, __("Client will pay — {0}", [label]), () => {
			if (frm.is_dirty()) {
				frappe.msgprint({
					title: __("Save first"),
					message: __("Save the task, then mark Client will pay."),
					indicator: "orange",
				});
				return;
			}
			frappe.model.set_value(row.doctype, row.name, "client_paid_directly", 1);
			frm.save().then(() => {
				frappe.show_alert({
					message: __("{0}: Client will pay — no company Journal Entry.", [label]),
					indicator: "blue",
				});
			});
		});
	});
}

function add_amendment_invoice_from_form(frm) {
	if (frm.is_new()) {
		frappe.msgprint(__("Save the task first."));
		return;
	}
	if (frm.is_dirty()) {
		frappe.msgprint({
			title: __("Save first"),
			message: __("Save the task, then add an amendment invoice."),
			indicator: "orange",
		});
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Add amendment invoice"),
		fields: [
			{
				fieldname: "attachment",
				label: __("Amendment Invoice PDF"),
				fieldtype: "Attach",
				reqd: 1,
				description: __(
					"Attach the new invoice here. The first paid invoice stays as-is."
				),
			},
		],
		primary_action_label: __("Add amendment"),
		primary_action(values) {
			if (!values.attachment) {
				frappe.msgprint(__("Attach the amendment invoice PDF first."));
				return;
			}
			dialog.hide();
			frappe.call({
				method:
					"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.add_amendment_invoice_line",
				args: { task_name: frm.doc.name, attachment: values.attachment },
				freeze: true,
				freeze_message: __("Adding amendment invoice…"),
				callback(r) {
					if (r.exc || !r.message) {
						return;
					}
					frappe.show_alert({
						message: r.message.message || __("Amendment invoice line added."),
						indicator: "green",
					});
					frm.reload_doc();
				},
			});
		},
	});
	dialog.show();
}

function primary_invoice_charge_item(frm) {
	const primary = get_invoice_finance_lines(frm).find((r) => !cint(r.is_amendment));
	return (primary && primary.charge_item) || "";
}

function show_add_amendment_invoice_button(frm) {
	const charge_item = primary_invoice_charge_item(frm);
	const add_button = () => {
		add_cgm_toolbar_button(frm, __("Add amendment invoice"), () => {
			add_amendment_invoice_from_form(frm);
		});
	};
	if (!charge_item) {
		// No Clearance Charge Item linked yet — keep sea-clearance behaviour.
		add_button();
		return;
	}
	frappe.db.get_value("Clearance Charge Item", charge_item, "allows_amendment", (r) => {
		if (r && cint(r.allows_amendment)) {
			add_button();
		}
	});
}

function setup_permit_finance_payment_buttons(frm) {
	show_permit_finance_journal_entry_view_buttons(frm);
	setup_permit_finance_make_payment_buttons(frm);
}

function open_journal_entry_payment_dialog(frm, opts = {}) {
	const permit_row_name = opts.permit_row_name || null;
	const finance_line_name = opts.finance_line_name || null;
	const title_suffix = opts.title_suffix ? ` — ${opts.title_suffix}` : "";
	if (!frm.doc.name || frm.is_new()) {
		frappe.msgprint(__("Save the task before making a payment."));
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Make Payment - Journal Entry{0}", [title_suffix]),
		size: "large",
		fields: [
			{ fieldname: "posting_date", label: __("Posting Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
			{ fieldname: "amount", label: __("Amount"), fieldtype: "Currency", reqd: 1, default: opts.default_amount || undefined },
			{ fieldname: "cb1", fieldtype: "Column Break" },
			{ fieldname: "cheque_no", label: __("Reference No"), fieldtype: "Data" },
			{ fieldname: "cheque_date", label: __("Reference Date"), fieldtype: "Date" },
			{ fieldname: "sec_accounts", fieldtype: "Section Break", label: __("Accounts") },
			{
				fieldname: "pay_to_account",
				label: __("Pay To: Account (Debit)"),
				fieldtype: "Link",
				options: "Account",
				reqd: 1,
				get_query: () => ({ filters: journal_account_filters(frm, false) }),
			},
			{ fieldname: "cb2", fieldtype: "Column Break" },
			{
				fieldname: "pay_from_account",
				label: __("Pay From: Account (Credit)"),
				fieldtype: "Link",
				options: "Account",
				reqd: 1,
				get_query: () => ({ filters: journal_account_filters(frm, true) }),
			},
			{ fieldname: "sec_party", fieldtype: "Section Break", label: __("Party (only for Payable/Receivable accounts)"), collapsible: 1 },
			{ fieldname: "party_type", label: __("Party Type"), fieldtype: "Link", options: "Party Type" },
			{ fieldname: "party", label: __("Party"), fieldtype: "Dynamic Link", options: "party_type" },
			{ fieldname: "sec_remark", fieldtype: "Section Break" },
			{ fieldname: "user_remark", label: __("Remark"), fieldtype: "Small Text" },
		],
		primary_action_label: __("Create Journal Entry"),
		primary_action(values) {
			frappe.call({
				method: "cgm_shipping.cgm_worldwide_shipping.customizations.task.create_journal_payment_from_task",
				args: {
					task_name: frm.doc.name,
					amount: values.amount,
					pay_from_account: values.pay_from_account,
					pay_to_account: values.pay_to_account,
					posting_date: values.posting_date,
					party_type: values.party_type,
					party: values.party,
					cheque_no: values.cheque_no,
					cheque_date: values.cheque_date,
					user_remark: values.user_remark,
					permit_row_name,
					finance_line_name,
				},
				freeze: true,
				freeze_message: __("Creating Journal Entry…"),
				callback(r) {
					if (r.exc || !r.message) {
						return;
					}
					dialog.hide();
					frappe.show_alert({
						message: __("Draft Journal Entry {0} created", [r.message]),
						indicator: "green",
					});
					frm.reload_doc();
					frappe.set_route("Form", "Journal Entry", r.message);
				},
			});
		},
	});
	dialog.show();
}

function user_can_record_purchase_invoice(frm) {
	const perms = frm ? get_cgm_permissions(frm) : null;
	if (perms) {
		return !!perms.can_record_purchase_invoice;
	}
	return CGM_TASK_PERMISSIONS_FALLBACK.can_record_purchase_invoice.some((role) =>
		(frappe.user_roles || []).includes(role)
	);
}

function open_next_task_prompt(frm) {
	if (!frm.doc.project || !frm.doc.custom_task_flow_key || !frm.doc.custom_sequence_no) {
		frappe.show_alert({
			message: __("Task completed."),
			indicator: "green",
		});
		return;
	}

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Task",
			filters: {
				project: frm.doc.project,
				custom_task_flow_key: frm.doc.custom_task_flow_key,
			},
			fields: ["name", "subject", "custom_sequence_no", "status"],
			order_by: "custom_sequence_no asc",
			limit_page_length: 500,
		},
		callback(r) {
			const tasks = r.message || [];
			const current_seq = Number(frm.doc.custom_sequence_no || 0);
			const next = tasks.find(
				(t) =>
					Number(t.custom_sequence_no || 0) > current_seq &&
					t.status !== "Completed" &&
					t.status !== "Cancelled"
			);

			if (!next) {
				frappe.show_alert({
					message: __("Task completed. No further open tasks in this sequence."),
					indicator: "green",
				});
				return;
			}

			frappe.confirm(
				__("Open next task: <b>{0}</b>?", [next.subject || next.name]),
				() => frappe.set_route("Form", "Task", next.name)
			);
		},
	});
}

frappe.realtime.on("cgm_task_status_changed", (data) => {
	if (!data || !data.task) {
		return;
	}
	if (cur_list && cur_list.doctype === "Task") {
		cur_list.refresh();
	}
	if (cur_frm && cur_frm.doctype === "Task" && cur_frm.doc.name === data.task) {
		// Never interrupt an in-flight complete / payment action.
		if (cur_frm._cgm_task_action_busy || cur_frm._cgm_completing_permit_application) {
			return;
		}
		// Soft path: POP/receipt mirrors + quiet reopens — refresh fields only.
		// Full reload_doc here caused Open↔Completed / row flicker loops.
		if (data.soft_sync || data.pop_synced || data.receipt_synced || data.reopened) {
			clearTimeout(cur_frm._cgm_soft_sync_timer);
			cur_frm._cgm_soft_sync_timer = setTimeout(() => {
				if (
					!cur_frm ||
					cur_frm.doc.name !== data.task ||
					cur_frm._cgm_task_action_busy ||
					cur_frm._cgm_completing_permit_application
				) {
					return;
				}
				frappe.db.get_doc("Task", data.task).then((doc) => {
					if (!cur_frm || cur_frm.doc.name !== data.task || !doc) {
						return;
					}
					cur_frm._cgm_skip_finance_line_autosave = true;
					// Keep optimistic-lock timestamp in sync or Attach→save fails with
					// "modified after you opened it".
					if (doc.modified) {
						cur_frm.doc.modified = doc.modified;
					}
					if (doc.status && cur_frm.doc.status !== doc.status) {
						cur_frm.doc.status = doc.status;
						cur_frm.doc.completed_by = doc.completed_by || null;
						cur_frm.doc.completed_on = doc.completed_on || null;
						cur_frm.doc.progress = doc.progress;
						cur_frm.refresh_field("status");
						cgm_configure_task_status_fields(cur_frm);
					}
					cur_frm.doc.custom_task_finance_lines = doc.custom_task_finance_lines || [];
					cur_frm._cgm_toolbar_fingerprint = null;
					cur_frm._cgm_shipping_line_declarant_status_loaded = false;
					cur_frm.refresh_field("custom_task_finance_lines");
					const grid = cur_frm.fields_dict.custom_task_finance_lines?.grid;
					if (grid && cgm_shipping.status_field?.paint_grid) {
						cgm_shipping.status_field.paint_grid(
							grid,
							"verified",
							(value) => cgm_shipping.status_field.tone_for_verified(value)
						);
					}
					schedule_cgm_task_toolbar_buttons(cur_frm);
					if (is_app_finance_application_step(cur_frm, undefined, "shipping_line")) {
						load_app_finance_declarant_status(cur_frm, "shipping_line");
					}
					setTimeout(() => {
						if (cur_frm) {
							cur_frm._cgm_skip_finance_line_autosave = false;
						}
					}, 800);
				});
			}, 300);
			return;
		}
		clearTimeout(cur_frm._cgm_status_reload_timer);
		cur_frm._cgm_status_reload_timer = setTimeout(() => {
			if (
				!cur_frm ||
				cur_frm.doc.name !== data.task ||
				cur_frm._cgm_task_action_busy ||
				cur_frm._cgm_completing_permit_application
			) {
				return;
			}
			// Skip reload when status already matches the event (no visible change).
			if (data.status && cur_frm.doc.status === data.status) {
				return;
			}
			// Prefer soft field sync over full reload when only status flipped —
			// avoids TimestampMismatchError while an Attach save is in flight.
			if (data.status === "Completed" || data.status === "Open") {
				cur_frm._cgm_skip_finance_line_autosave = true;
				frappe.db.get_doc("Task", data.task).then((doc) => {
					if (!cur_frm || cur_frm.doc.name !== data.task || !doc) {
						return;
					}
					if (doc.modified) {
						cur_frm.doc.modified = doc.modified;
					}
					cur_frm.doc.status = doc.status;
					cur_frm.doc.completed_by = doc.completed_by || null;
					cur_frm.doc.completed_on = doc.completed_on || null;
					cur_frm.doc.progress = doc.progress;
					cur_frm.doc.custom_task_finance_lines = doc.custom_task_finance_lines || [];
					cur_frm.refresh_field("status");
					cur_frm.refresh_field("custom_task_finance_lines");
					cgm_configure_task_status_fields(cur_frm);
					cur_frm._cgm_toolbar_fingerprint = null;
					cur_frm._cgm_shipping_line_declarant_status_loaded = false;
					schedule_cgm_task_toolbar_buttons(cur_frm);
					if (is_app_finance_application_step(cur_frm, undefined, "shipping_line")) {
						load_app_finance_declarant_status(cur_frm, "shipping_line");
					}
					setTimeout(() => {
						if (cur_frm) {
							cur_frm._cgm_skip_finance_line_autosave = false;
						}
					}, 800);
				});
				return;
			}
			cur_frm._cgm_toolbar_fingerprint = null;
			cur_frm.reload_doc();
		}, 400);
	}
});
