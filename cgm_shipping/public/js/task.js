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
		frm._cgm_sea_seq_config = null;
		load_cgm_sea_ui_sequences(frm);
		frm._cgm_sea_layout_ready = false;
		frm._cgm_finance_grid_ready = false;
		frm._cgm_declarant_status = null;
		frm._cgm_declarant_status_loading = false;
		frm._cgm_declarant_status_loaded = false;
		frm._cgm_finance_lines_ensuring = false;
		frm.set_query("department", () => ({
			filters: { parent_department: ["like", "Operations%"] },
		}));
	},

	before_save(frm) {
		strip_legacy_invoice_clearance_rows(frm);
	},

	refresh(frm) {
		const ui = get_sea_task_ui(frm);

		// Layout + grid config once per form load (re-running on every refresh closes Action menus).
		if (!frm._cgm_sea_layout_ready) {
			apply_sea_task_form_layout(frm, ui);
			frm._cgm_sea_layout_ready = true;
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
					intro = __(
						"<b>1 Finance:</b> Create PI & <b>Make Payment</b> · " +
							"<b>2 Declarant:</b> Upload receipts on <b>Apply for Pre-Clearance Permits</b> · " +
							"<b>3 Finance:</b> Use <b>Actions → Verify All Receipts</b> - this task and the declarant task complete automatically."
					);
				} else if (frm.doc.custom_permit_invoices_submitted) {
					intro = __(
						"<b>After Finance pays:</b> Upload <b>Payment Receipt</b> and <b>Permit Certificate</b> on each row. " +
							"Finance verifies receipts on <b>Finance pays Pre-Clearance Permits</b>, then complete this task."
					);
				} else {
					intro = __(
						"<b>Declaration:</b> Attach <b>Permit Invoice (for Finance)</b> on each row, then click " +
							"<b>Notify Finance - invoices ready</b>."
					);
				}
			} else if (ui.is_ucr_application) {
				if (frm._cgm_declarant_status_loaded && frm._cgm_declarant_status) {
					apply_ucr_application_intro(frm, frm._cgm_declarant_status);
					intro_set = true;
				}
			} else if (ui.is_ucr_finance) {
				intro = __(
					"<b>1 Finance:</b> Verify <b>UCR Invoice</b> · " +
						"<b>2</b> <b>Actions → Create Purchase Invoice & Pay</b> · " +
						"<b>3 Declarant:</b> Upload <b>UCR Receipt</b> and IDF certificate on <b>Create UCR (IDF)</b> · " +
						"<b>4 Finance:</b> Verify receipt - this task completes automatically when the receipt is verified."
				);
				intro_set = true;
			} else if (ui.show_payments) {
				intro = __(
					"Attach the <b>Supplier Invoice</b> on Task Documents for Accounts, then <b>Create Purchase Invoice</b> and <b>Make Payment</b>."
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

		if (ui.is_ucr_finance && frm.doc.status !== "Completed") {
			ensure_ucr_finance_task_completed_on_form(frm);
		}

		if (ui.show_permits && is_permit_finance_step(frm) && frm.doc.project) {
			ensure_finance_permit_rows_on_form(frm);
		}

		if (
			ui.is_ucr_application &&
			frm.doc.status !== "Completed" &&
			!frm.doc.custom_ucr_invoice_submitted
		) {
			frm.add_custom_button(__("Submit UCR invoice to Finance"), () => {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow.submit_ucr_invoice_to_finance",
					args: { task_name: frm.doc.name },
					freeze: true,
					callback(r) {
						if (!r.exc) {
							showWorkflowNotifyResult(r, __("Finance notified"));
							const fin = r.message && r.message.finance_task;
							if (fin && fin !== frm.doc.name) {
								frappe.show_alert({
									message: __("Open Finance pays UCR: {0}", [fin]),
									indicator: "blue",
								});
							}
							frm.reload_doc();
						}
					},
				});
			});
		}

		if (ui.is_ucr_finance && frm.doc.status !== "Completed") {
			if (user_can_make_payment(frm)) {
				const inv = get_finance_line(frm, "Invoice");
				const rec = get_finance_line(frm, "Receipt");
				if (inv?.attachment && !inv?.verified) {
					add_cgm_toolbar_button(frm, __("Verify UCR Invoice"), () => {
						verify_ucr_finance_line(frm, "Invoice");
					}, { primary: true });
				}
				if (rec && rec.attachment && !rec.verified) {
					add_cgm_toolbar_button(frm, __("Verify UCR Receipt"), () => {
						verify_ucr_finance_line(frm, "Receipt");
					});
				}
			}
		}

		if (
			ui.show_permits &&
			is_pre_clearance_permit_application_step(frm) &&
			frm.doc.status !== "Completed" &&
			!frm.doc.custom_permit_invoices_submitted
		) {
			frm.add_custom_button(__("Notify Finance - invoices ready"), () => {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow.submit_permit_invoices_to_finance",
					args: { task_name: frm.doc.name },
					freeze: true,
					callback(r) {
						if (!r.exc) {
							showWorkflowNotifyResult(r, __("Finance notified"));
							const fin = r.message && r.message.finance_task;
							if (fin && fin !== frm.doc.name) {
								frappe.show_alert({
									message: __("Finance pays Pre-Clearance Permits: {0}", [fin]),
									indicator: "blue",
								});
							}
							frm.reload_doc();
						}
					},
				});
			});
		}

		if (
			frm.doc.docstatus === 0 &&
			frm.doc.status !== "Completed" &&
			frm.doc.status !== "Cancelled" &&
			!ui.hide_mark_complete &&
			!ui.show_payments &&
			!ui.show_permits
		) {
			frm.add_custom_button(__("Mark Completed"), async () => {
				await frm.set_value("completed_by", frappe.session.user);
				await frm.set_value("completed_on", frappe.datetime.now_datetime());
				await frm.set_value("status", "Completed");
				await frm.save();
			});
		}

		if (
			is_permit_finance_step(frm) &&
			frm.doc.status !== "Completed" &&
			frm.doc.custom_payment_entry &&
			user_can_make_payment(frm) &&
			permit_rows_pending_receipt_verification(frm).length
		) {
			add_cgm_toolbar_button(
				frm,
				__("Verify All Receipts"),
				() => verify_all_permit_receipts_from_form(frm),
				{ primary: true }
			);
		}

		if (
			is_pre_clearance_permit_application_step(frm) &&
			frm.doc.status !== "Completed" &&
			frm.doc.custom_permit_invoices_submitted &&
			user_can_upload_receipt(frm)
		) {
			frm.add_custom_button(__("Complete Pre-Clearance Permits Task"), async () => {
				await frm.set_value("completed_by", frappe.session.user);
				await frm.set_value("completed_on", frappe.datetime.now_datetime());
				await frm.set_value("status", "Completed");
				await frm.save();
			});
		}

		if (ui.show_permits && frm.doc.status === "Completed" && !permit_rows_have_invoices(frm)) {
			frm.add_custom_button(__("Re-open to attach invoices"), () => {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules.reopen_task_for_permit_attachments",
					args: { task_name: frm.doc.name },
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __("Task re-opened - attach Permit Invoice on each row, then save."),
								indicator: "orange",
							});
							frm.reload_doc();
						}
					},
				});
			});
		}

		if (ui.show_payments && frm.doc.status !== "Completed" && frm.doc.status !== "Cancelled") {
			if (!frm.doc.custom_purchase_invoice && user_can_record_purchase_invoice(frm)) {
				add_cgm_toolbar_button(frm, __("Create Purchase Invoice & Pay"), () => {
					open_purchase_invoice_from_task(frm);
				});
			}
			if (frm.doc.custom_purchase_invoice && !frm.doc.custom_payment_entry && user_can_make_payment(frm)) {
				add_cgm_toolbar_button(frm, __("Make Payment"), () => {
					open_payment_entry_from_task(frm);
				});
			}
			if (frm.doc.custom_purchase_invoice && frm.doc.project && user_can_record_purchase_invoice(frm)) {
				add_cgm_toolbar_button(frm, __("Sync PI Project"), () => sync_pi_project_from_task(frm));
			}
			if (
				!frm.doc.custom_purchase_invoice &&
				user_can_record_purchase_invoice(frm) &&
				frm.doc.status !== "Completed"
			) {
				add_cgm_toolbar_button(frm, __("Link Invoice & Payment"), () => {
					frappe.call({
						method: "cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link.sync_finance_links_from_documents",
						args: { task_name: frm.doc.name },
						freeze: true,
						callback(r) {
							if (!r.exc) {
								frappe.show_alert({
									message: r.message?.message || __("Finance documents linked"),
									indicator: "green",
								});
								frm.reload_doc();
							}
						},
					});
				});
			}
		}

		if (ui.is_sea_task && frm.doc.project) {
			frm.add_custom_button(__("Open Shipment Project"), () => {
				frappe.set_route("Form", "Project", frm.doc.project);
			});
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
});

const SEA_FLOW_KEY = "SEA_IMPORT_E2E";

/** Empty shell until get_sea_task_ui_sequences returns (no hardcoded business rules). */
const CGM_SEA_UI_SEQUENCES_EMPTY = {
	payment_seqs: [],
	auto_complete_seqs: [],
	permit_application_seqs: [],
	light_proof_seqs: [],
	ucr_application_seqs: [],
	finance_document_seqs: [],
	permit_finance_seqs: [],
	ucr_finance_seqs: [],
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
		return "eval:doc.custom_task_flow_key=='SEA_IMPORT_E2E'";
	}
	return `eval:doc.custom_task_flow_key=='SEA_IMPORT_E2E' && [${seqs.join(",")}].includes(doc.custom_sequence_no)`;
}

const CGM_TASK_PERMISSIONS_FALLBACK = {
	can_make_payment: ["Finance Manager", "Finance User", "Accounts User", "Accounts Manager"],
	can_upload_receipt: [
		"Operations Manager",
		"Operations User",
		"Declaration User",
		"Declarant",
		"System Manager",
		"Finance Manager",
		"Finance User",
		"Accounts User",
		"Accounts Manager",
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

function load_cgm_sea_ui_sequences(frm) {
	if (!is_sea_clearance_task(frm) || frm._cgm_sea_seq_loading || frm._cgm_sea_seq_config) {
		return;
	}
	frm._cgm_sea_seq_loading = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements.service.get_sea_task_ui_sequences",
		callback(r) {
			frm._cgm_sea_seq_loading = false;
			frm._cgm_sea_seq_config = r.message || CGM_SEA_UI_SEQUENCES_EMPTY;
			frm.trigger("refresh");
		},
		error() {
			frm._cgm_sea_seq_loading = false;
			frm._cgm_sea_seq_config = CGM_SEA_UI_SEQUENCES_EMPTY;
			frappe.msgprint({
				title: __("CGM Settings"),
				message: __(
					"Sea task requirements could not be loaded. Configure CGM Shipping Settings → Sea clearance task requirements."
				),
				indicator: "red",
			});
		},
	});
}

function get_cgm_sea_seq_config(frm) {
	return frm._cgm_sea_seq_config || CGM_SEA_UI_SEQUENCES_EMPTY;
}

function get_cgm_task_permissions(frm) {
	const perms = get_cgm_sea_seq_config(frm).permissions;
	if (perms && Object.keys(perms).length) {
		return perms;
	}
	const roles = frappe.user_roles || [];
	return {
		can_make_payment: CGM_TASK_PERMISSIONS_FALLBACK.can_make_payment.some((r) =>
			roles.includes(r)
		),
		can_upload_receipt: CGM_TASK_PERMISSIONS_FALLBACK.can_upload_receipt.some((r) =>
			roles.includes(r)
		),
		can_record_purchase_invoice: CGM_TASK_PERMISSIONS_FALLBACK.can_record_purchase_invoice.some(
			(r) => roles.includes(r)
		),
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

function is_permit_application_step(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return seq_in_list(s, get_cgm_sea_seq_config(frm).permit_application_seqs);
}

function is_permit_finance_step(frm, seq) {
	const s = seq !== undefined ? seq : sea_task_sequence(frm);
	return seq_in_list(s, get_cgm_sea_seq_config(frm).permit_finance_seqs);
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
	return frm.doc.custom_task_flow_key === SEA_FLOW_KEY;
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
		return {
			is_sea_task: true,
			show_documents: true,
			documents_read_only: true,
			show_permits: false,
			show_payments: false,
			show_external_ref: false,
			show_description: true,
			auto_intake_intro: true,
			hide_mark_complete: true,
		};
	}
	if (seq_in_list(seq, cfg.ucr_application_seqs)) {
		return {
			is_sea_task: true,
			is_ucr_application: true,
			is_ucr_finance: false,
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
		return {
			is_sea_task: true,
			is_ucr_application: false,
			is_ucr_finance: ucr_finance,
			show_finance_lines: ucr_finance,
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
	configure_ucr_finance_fields(frm, ui);
	toggle("custom_external_ref_no", ui.show_external_ref);
	toggle("description", ui.show_description);
	toggle("sb_timeline", false);
	toggle("sb_costing", false);
	toggle("depends_on_tab", false);
}

function permit_rows_have_invoices(frm) {
	const rows = frm.doc.custom_task_permits || [];
	if (!rows.length) {
		return false;
	}
	return rows.every((r) => r.permit_type && r.payment_invoice);
}

function permit_rows_pending_receipt_verification(frm) {
	return (frm.doc.custom_task_permits || []).filter(
		(r) => r.permit_type && r.payment_receipt && !r.receipt_verified
	);
}

function verify_all_permit_receipts_from_form(frm) {
	if (frm._cgm_verifying_permit_receipts) {
		return;
	}
	if (frm.is_dirty()) {
		frappe.msgprint({
			title: __("Save first"),
			message: __("Save the task, then click Verify All Receipts again."),
			indicator: "orange",
		});
		return;
	}
	frm._cgm_verifying_permit_receipts = true;
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow.verify_all_permit_receipts",
		args: { task_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Verifying receipts…"),
		callback(r) {
			frm._cgm_verifying_permit_receipts = false;
			if (r.exc) {
				return;
			}
			const data = r.message || {};
			frappe.show_alert({
				message: data.message || __("Receipts verified"),
				indicator: data.auto_completed ? "green" : "blue",
			});
			frm.reload_doc();
		},
		error() {
			frm._cgm_verifying_permit_receipts = false;
		},
	});
}

function get_finance_line(frm, line_type) {
	return (frm.doc.custom_task_finance_lines || []).find((r) => r.line_type === line_type);
}

function ucr_finance_ready_on_form(frm) {
	const inv = get_finance_line(frm, "Invoice");
	const rec = get_finance_line(frm, "Receipt");
	return Boolean(inv && inv.verified && rec && rec.attachment && rec.verified);
}

function configure_finance_line_grid(frm, ui) {
	const grid = frm.fields_dict.custom_task_finance_lines?.grid;
	if (!grid || frm._cgm_finance_grid_ready) {
		return;
	}
	const is_finance = user_can_make_payment(frm);
	const can_receipt = user_can_upload_receipt(frm);
	const seq = sea_task_sequence(frm);

	// Set docfield properties directly - avoid toggle_enable() which re-renders the grid
	// and can collapse the toolbar while the user clicks action buttons.
	const line_label_df = grid.get_docfield("line_label");
	const verified_df = grid.get_docfield("verified");
	if (line_label_df) {
		line_label_df.read_only = 1;
	}
	if (verified_df) {
		verified_df.read_only = is_ucr_application_step(frm, seq) ? 1 : is_finance ? 0 : 1;
	}

	if (is_ucr_application_step(frm, seq)) {
		const attachment_df = grid.get_docfield("attachment");
		if (attachment_df) {
			attachment_df.read_only = 0;
		}
	} else if (is_ucr_finance_step(frm, seq)) {
		const attachment_df = grid.get_docfield("attachment");
		if (attachment_df) {
			// Invoice and receipt are copied from Create UCR (IDF); Finance verifies only.
			attachment_df.read_only = 1;
		}
	}

	frm._cgm_finance_grid_ready = true;
}

function add_cgm_toolbar_button(frm, label, fn, opts = {}) {
	const btn = frm.add_custom_button(label, fn, CGM_ACTION_GROUP);
	if (opts.primary) {
		frm.change_custom_button_type(label, CGM_ACTION_GROUP, "primary");
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
	if (ui.is_ucr_finance || ui.show_finance_lines) {
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
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow.ensure_finance_permit_rows",
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
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow.ensure_ucr_finance_lines",
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
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow.get_ucr_declarant_workflow_status",
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
	} else if (status.application_ready_to_complete) {
		intro = __("<b>All declarant documents are in place.</b> Completing this task…");
	} else if (status.receipt_attached && !status.idf_certificate_attached) {
		intro = __(
			"<b>Attach the IDF/UCR certificate</b> under <b>Clearance Documents</b> to finish this task."
		);
	} else if (status.receipt_attached) {
		intro = __(
			"<b>UCR receipt uploaded.</b> Attach the IDF/UCR certificate under <b>Clearance Documents</b> to complete this task."
		);
	} else if (status.payment_made) {
		intro = __(
			"<b>Finance has paid the UCR invoice.</b> Attach the supplier <b>UCR Receipt</b> on " +
				"<b>Invoices &amp; Receipts</b> below. When the certificate is issued, attach it under " +
				"<b>Clearance Documents</b>."
		);
	} else if (status.invoice_verified) {
		intro = __(
			"<b>UCR invoice verified by Finance.</b> Waiting for payment. After payment, attach the " +
				"<b>UCR Receipt</b> here and the certificate under <b>Clearance Documents</b> when issued."
		);
	} else if (status.invoice_submitted) {
		intro = __(
			"<b>UCR invoice submitted to Finance.</b> Waiting for Finance to verify and pay. " +
				"After payment you will upload the supplier receipt here."
		);
	} else {
		intro = __(
			"<b>Declarant:</b> Attach <b>UCR Invoice</b> on <b>Invoices & Receipts</b>, " +
				"<b>Submit UCR invoice to Finance</b>. After payment, attach the supplier <b>UCR Receipt</b> " +
				"and the IDF/UCR certificate under <b>Clearance Documents</b> when issued."
		);
	}
	set_task_intro(frm, intro);
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
		"invoice_verified",
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

	const invoices_sent = frm.doc.custom_permit_invoices_submitted;
	const can_upload_proof = user_can_upload_receipt(frm);

	if (is_permit_application_step(frm, seq)) {
		grid.update_docfield_property("payment_invoice", "read_only", invoices_sent ? 1 : 0);
		grid.update_docfield_property("payment_receipt", "hidden", invoices_sent ? 0 : 1);
		grid.update_docfield_property("payment_receipt", "read_only", can_upload_proof ? 0 : 1);
		grid.update_docfield_property("permit_document", "hidden", invoices_sent ? 0 : 1);
		grid.update_docfield_property("permit_document", "read_only", can_upload_proof ? 0 : 1);
		grid.update_docfield_property("receipt_verified", "hidden", invoices_sent ? 0 : 1);
		grid.update_docfield_property("receipt_verified", "read_only", 1);
	} else if (is_permit_finance_step(frm, seq)) {
		["payment_invoice", "purchase_invoice", "payment_entry", "permit_document"].forEach((fn) => {
			grid.update_docfield_property(fn, "read_only", 1);
		});
		grid.update_docfield_property("payment_receipt", "hidden", 0);
		grid.update_docfield_property("payment_receipt", "read_only", 1);
		grid.update_docfield_property("receipt_verified", "hidden", 0);
		grid.update_docfield_property("receipt_verified", "read_only", user_can_make_payment(frm) ? 0 : 1);
	}
}

frappe.ui.form.on("Task Finance Line", {
	attachment(frm, cdt, cdn) {
		if (frm.doctype !== "Task") {
			return;
		}
		const row = locals[cdt][cdn];
		if (is_ucr_application_step(frm) && row.line_type === "Receipt" && row.attachment) {
			frappe.show_alert({
				message: __("UCR receipt saved - Finance will be notified to verify."),
				indicator: "green",
			});
		}
		if (frm.doc.status !== "Completed") {
			frm.save();
		}
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
		if (row.verified) {
			frappe.model.set_value(cdt, cdn, "verified_by", frappe.session.user);
			frappe.model.set_value(cdt, cdn, "verified_on", frappe.datetime.now_datetime());
		}
		frm.save().then(() => {
			if (is_ucr_finance_step(frm)) {
				ensure_ucr_finance_task_completed_on_form(frm);
			}
		});
	},
});

frappe.ui.form.on("Permit Register", {
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
	},

	payment_invoice(frm, cdt, cdn) {
		if (frm.doctype !== "Task") {
			return;
		}
		const row = locals[cdt][cdn];
		if (row.payment_invoice) {
			frappe.model.set_value(cdt, cdn, "status", "Invoice Submitted");
		}
		if (frm.doc.status !== "Completed") {
			frm.save();
		}
	},

	payment_receipt(frm, cdt, cdn) {
		if (frm.doctype !== "Task") {
			return;
		}
		const seq = sea_task_sequence(frm);
		if (!is_permit_finance_step(frm, seq) && !is_pre_clearance_permit_application_step(frm, seq)) {
			return;
		}
		const row = locals[cdt][cdn];
		if (row.payment_receipt) {
			frappe.model.set_value(cdt, cdn, "status", "Receipt Submitted");
			frappe.call({
				method: "cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow.notify_finance_verify_receipts",
				args: { task_name: frm.doc.name },
			});
		}
		if (frm.doc.status !== "Completed") {
			frm.save();
		}
	},

	permit_document(frm, cdt, cdn) {
		if (frm.doctype !== "Task" || !is_pre_clearance_permit_application_step(frm)) {
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
		frm.save();
	},
});

function ensure_ucr_finance_task_completed_on_form(frm) {
	if (frm._cgm_finance_complete_checking) {
		return;
	}
	const inv = get_finance_line(frm, "Invoice");
	const rec = get_finance_line(frm, "Receipt");
	if (!inv?.verified || !rec?.verified || !rec?.attachment) {
		return;
	}
	frm._cgm_finance_complete_checking = true;
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow.ensure_ucr_finance_task_completed",
		args: { task_name: frm.doc.name },
		callback(r) {
			frm._cgm_finance_complete_checking = false;
			if (r.exc || !r.message) {
				return;
			}
			if (r.message.status === "Completed" && frm.doc.status !== "Completed") {
				frappe.show_alert({
					message: __("Finance pays UCR task completed"),
					indicator: "green",
				});
				frm.reload_doc();
			}
		},
		error() {
			frm._cgm_finance_complete_checking = false;
		},
	});
}

function verify_ucr_finance_line(frm, line_type) {
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow.verify_ucr_finance_line",
		args: { task_name: frm.doc.name, line_type },
		freeze: true,
		callback(r) {
			if (!r.exc) {
				frappe.show_alert({
					message: r.message?.message || __("Verified"),
					indicator: "green",
				});
				if (r.message?.task_status === "Completed" && frm.doc.status !== "Completed") {
					frappe.show_alert({
						message: __("Finance pays UCR task completed"),
						indicator: "green",
					});
				}
				frm.reload_doc();
			}
		},
	});
}

function user_can_make_payment(frm) {
	const perms = frm ? get_cgm_task_permissions(frm) : null;
	if (perms) {
		return !!perms.can_make_payment;
	}
	return CGM_TASK_PERMISSIONS_FALLBACK.can_make_payment.some((role) =>
		(frappe.user_roles || []).includes(role)
	);
}

function user_can_upload_receipt(frm) {
	const perms = frm ? get_cgm_task_permissions(frm) : null;
	if (perms) {
		return !!perms.can_upload_receipt;
	}
	return CGM_TASK_PERMISSIONS_FALLBACK.can_upload_receipt.some((role) =>
		(frappe.user_roles || []).includes(role)
	);
}

function open_purchase_invoice_from_task(frm) {
	if (!frm.doc.project) {
		frappe.msgprint(__("This task must be linked to a Project first."));
		return;
	}
	localStorage.setItem("cgm_return_task", frm.doc.name);
	localStorage.setItem("cgm_pi_for_task", "1");
	frappe.route_options = {
		custom_cgm_source_task: frm.doc.name,
		project: frm.doc.project,
	};
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link.get_task_finance_defaults",
		args: { task_name: frm.doc.name },
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			frappe.new_doc("Purchase Invoice");
		},
	});
}

function sync_pi_project_from_task(frm) {
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link.sync_finance_docs_from_task",
		args: { task_name: frm.doc.name },
		callback(r) {
			if (!r.exc) {
				frappe.show_alert({
					message: __("Purchase Invoice updated with Project {0}", [r.message.project]),
					indicator: "green",
				});
			}
		},
	});
}

function open_payment_entry_from_task(frm) {
	const pi = frm.doc.custom_purchase_invoice;
	if (!pi) {
		frappe.msgprint(__("Link a submitted Purchase Invoice on this task first."));
		return;
	}
	localStorage.setItem("cgm_return_task", frm.doc.name);
	localStorage.setItem("cgm_pe_for_task", "1");
	frappe.route_options = {
		custom_cgm_source_task: frm.doc.name,
		project: frm.doc.project,
	};
	frappe.call({
		method: "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
		args: {
			dt: "Purchase Invoice",
			dn: pi,
		},
		freeze: true,
		freeze_message: __("Building Payment Entry for {0}…", [pi]),
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			const doclist = frappe.model.sync(r.message);
			const pe = doclist[0];
			if (pe && frm.doc.project) {
				frappe.model.set_value(pe.doctype, pe.name, "project", frm.doc.project);
				frappe.model.set_value(
					pe.doctype,
					pe.name,
					"custom_cgm_source_task",
					frm.doc.name
				);
			}
			frappe.set_route("Form", pe.doctype, pe.name);
			frappe.show_alert({
				message: __("Payment Entry prefilled against {0}", [pi]),
				indicator: "blue",
			});
		},
	});
}

function user_can_record_purchase_invoice(frm) {
	const perms = frm ? get_cgm_task_permissions(frm) : null;
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
		cur_frm.reload_doc();
	}
});
