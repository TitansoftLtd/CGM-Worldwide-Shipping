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
		frm._cgm_checkpoint_seed_requested = false;
		frm.set_query("department", () => ({
			filters: { parent_department: ["like", "Operations%"] },
		}));
		if (frm._cgm_finance_department === undefined) {
			frm._cgm_finance_department = null;
			frappe.db
				.get_single_value("CGM Shipping Settings", "custom_finance_department")
				.then((dept) => {
					frm._cgm_finance_department = dept || null;
					if (dept) {
						frm.trigger("refresh");
					}
				});
		}
	},

	before_save(frm) {
		strip_legacy_invoice_clearance_rows(frm);
	},

	refresh(frm) {
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
		cgm_configure_document_status_grids(frm);
		cgm_configure_permit_status_grids(frm);
		if (ui.show_payments && frm.fields_dict.custom_journal_entry) {
			frm.set_df_property(
				"custom_journal_entry",
				"hidden",
				is_permit_finance_step(frm) ? 1 : 0
			);
		}
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
					const appLabel = permit_application_task_label(
						frm,
						get_paired_permit_application_seq(frm, seq)
					);
					intro = __(
						"<b>1 Finance:</b> Use <b>Make Payment</b> on each permit row (one Journal Entry per permit) · " +
							"<b>2 Declarant:</b> Upload receipts on <b>{0}</b> · " +
							"<b>3 Finance:</b> Use <b>Actions → Verify Receipt</b> — both tasks complete automatically.",
						[appLabel]
					);
				} else if (frm.doc.custom_permit_invoices_submitted) {
					const finLabel = permit_finance_task_label(
						frm,
						get_paired_permit_finance_seq(frm, seq)
					);
					intro = __(
						"<b>After Finance pays:</b> Upload <b>Payment Receipt</b> and <b>Permit Certificate</b> on each row. " +
							"Finance verifies receipts on <b>{0}</b>, then this task completes automatically.",
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
				intro = __(
					"<b>1 Finance:</b> Verify <b>UCR Invoice</b> · " +
						"<b>2</b> Use <b>Actions → Make Payment</b> to record the payment as a Journal Entry · " +
						"<b>3 Declarant:</b> Upload <b>UCR Receipt</b> and IDF certificate on <b>Create UCR (IDF)</b> · " +
						"<b>4 Finance:</b> Verify receipt - this task completes automatically when the receipt is verified."
				);
				intro_set = true;
			} else if (ui.is_entry_finance) {
				intro = __(
					"<b>1 Finance:</b> Verify <b>Entry Slip Invoice</b> · " +
						"<b>2</b> Use <b>Actions → Make Payment</b> to record the payment as a Journal Entry · " +
						"<b>3 Declarant:</b> Upload <b>Entry Slip Receipt</b> and ENTRY document on <b>Create Entry</b> · " +
						"<b>4 Finance:</b> Verify receipt - this task completes automatically when the receipt is verified."
				);
				intro_set = true;
			} else if (ui.is_shipping_line_finance) {
				intro = __(
					"<b>1 Finance:</b> Verify <b>Shipping Line Invoice</b> · " +
						"<b>2</b> Use <b>Actions → Make Payment</b> to record the payment as a Journal Entry · " +
						"<b>3 Operations:</b> Upload <b>Shipping Line Receipt</b> on <b>Attach Shipping Line Invoice</b> · " +
						"<b>4 Finance:</b> Verify receipt - this task completes automatically when the receipt is verified."
				);
				intro_set = true;
			} else if (ui.is_kpa_finance) {
				intro = __(
					"<b>1 Finance:</b> Verify <b>KPA Invoice</b> · " +
						"<b>2</b> Use <b>Actions → Make Payment</b> to record the payment as a Journal Entry · " +
						"<b>3 Supervisor:</b> Upload <b>KPA Receipt</b> on <b>Supervisor obtains KPA Invoice</b> · " +
						"<b>4 Finance:</b> Verify receipt - this task completes automatically when the receipt is verified."
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
					"Use <b>Make Payment</b> to record this payment as a Journal Entry (Finance department)."
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
			sync_app_finance_receipt_on_form(frm, "shipping_line");
			ensure_app_finance_task_completed_on_form(frm, "shipping_line");
		}

		if (ui.is_kpa_finance && frm.doc.status !== "Completed") {
			sync_app_finance_receipt_on_form(frm, "kpa");
			ensure_app_finance_task_completed_on_form(frm, "kpa");
		}

		if (ui.show_permits && is_permit_finance_step(frm) && frm.doc.project) {
			ensure_finance_permit_rows_on_form(frm);
		}

		if (ui.show_permits && is_permit_finance_step(frm) && frm.doc.status !== "Completed") {
			ensure_finance_permit_task_completed_on_form(frm);
		}

		if (ui.is_document_checkpoint && frm.doc.name && !frm.is_new()) {
			ensure_checkpoint_task_documents_on_form(frm);
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

		if (ui.is_entry_finance && frm.doc.status !== "Completed") {
			if (user_can_make_payment(frm)) {
				const inv = get_finance_line(frm, "Invoice");
				const rec = get_finance_line(frm, "Receipt");
				if (inv?.attachment && !inv?.verified) {
					add_cgm_toolbar_button(frm, __("Verify Entry Slip Invoice"), () => {
						verify_entry_finance_line(frm, "Invoice");
					}, { primary: true });
				}
				if (rec && rec.attachment && !rec.verified) {
					add_cgm_toolbar_button(frm, __("Verify Entry Slip Receipt"), () => {
						verify_entry_finance_line(frm, "Receipt");
					});
				}
			}
		}

		if (ui.is_shipping_line_finance && frm.doc.status !== "Completed") {
			if (user_can_make_payment(frm)) {
				const inv = get_finance_line(frm, "Invoice");
				const rec = get_finance_line(frm, "Receipt");
				if (inv?.attachment && !inv?.verified) {
					add_cgm_toolbar_button(frm, __("Verify Shipping Line Invoice"), () => {
						verify_app_finance_line(frm, "shipping_line", "Invoice");
					}, { primary: true });
				}
				if (rec && rec.attachment && !rec.verified) {
					add_cgm_toolbar_button(frm, __("Verify Shipping Line Receipt"), () => {
						verify_app_finance_line(frm, "shipping_line", "Receipt");
					});
				}
			}
		}

		if (ui.is_kpa_finance && frm.doc.status !== "Completed") {
			if (user_can_make_payment(frm)) {
				const inv = get_finance_line(frm, "Invoice");
				const rec = get_finance_line(frm, "Receipt");
				if (inv?.attachment && !inv?.verified) {
					add_cgm_toolbar_button(frm, __("Verify KPA Invoice"), () => {
						verify_app_finance_line(frm, "kpa", "Invoice");
					}, { primary: true });
				}
				if (rec && rec.attachment && !rec.verified) {
					add_cgm_toolbar_button(frm, __("Verify KPA Receipt"), () => {
						verify_app_finance_line(frm, "kpa", "Receipt");
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
			frm.add_custom_button(__("Mark Completed"), async () => {
				await frm.set_value("completed_by", frappe.session.user);
				await frm.set_value("completed_on", frappe.datetime.now_datetime());
				await frm.set_value("status", "Completed");
				await frm.save();
			}).addClass("btn-primary");
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
			}).addClass("btn-primary");
		}

		if (
			is_post_clearance_permit_application_step(frm) &&
			frm.doc.status !== "Completed" &&
			frm.doc.custom_permit_invoices_submitted &&
			user_can_upload_receipt(frm)
		) {
			frm.add_custom_button(__("Complete Post-Clearance Permits Task"), async () => {
				await frm.set_value("completed_by", frappe.session.user);
				await frm.set_value("completed_on", frappe.datetime.now_datetime());
				await frm.set_value("status", "Completed");
				await frm.save();
			}).addClass("btn-primary");
		}

		if (ui.show_permits && frm.doc.status === "Completed" && !permit_rows_have_invoices(frm)) {
			frm.add_custom_button(__("Re-open to attach invoices"), () => {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.task.reopen_task_for_permit_attachments",
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

		// Linked journal entries — always available for navigation.
		if (is_permit_payment_pattern(frm)) {
			show_permit_finance_journal_entry_view_buttons(frm);
		} else if (frm.doc.custom_journal_entry) {
			add_cgm_toolbar_button(frm, __("View Journal Entry"), () => {
				frappe.set_route("Form", "Journal Entry", frm.doc.custom_journal_entry);
			});
		}

		// Finance department: Make Payment via draft Journal Entry. Department-driven
		// (configured in CGM Shipping Settings), independent of the sea-flow sequence.
		if (
			is_finance_department_task(frm) &&
			user_can_make_payment(frm) &&
			frm.doc.status !== "Completed" &&
			frm.doc.status !== "Cancelled"
		) {
			if (is_permit_payment_pattern(frm)) {
				setup_permit_finance_make_payment_buttons(frm);
			} else if (!frm.doc.custom_journal_entry) {
				add_cgm_toolbar_button(
					frm,
					__("Make Payment"),
					() => open_journal_entry_payment_dialog(frm),
					{ primary: true }
				);
			}
		}

		setup_client_inspection_buttons(frm);

		if (
			is_permit_finance_step(frm) &&
			frm.doc.status !== "Completed" &&
			task_has_recorded_payment_on_form(frm) &&
			user_can_make_payment(frm) &&
			permit_rows_pending_receipt_verification(frm).length
		) {
			add_cgm_toolbar_button(
				frm,
				__("Verify Receipt"),
				() => verify_all_permit_receipts_from_form(frm),
				{ primary: true }
			);
		}

		if (ui.is_sea_task && frm.doc.project) {
			frm.add_custom_button(__("Open Shipment Project"), () => {
				frappe.set_route("Form", "Project", frm.doc.project);
			}).addClass("btn-primary");
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
			"cgm_shipping.cgm_worldwide_shipping.customizations.task.get_sea_task_ui_sequences",
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

function get_cgm_permissions(frm) {
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
		upload_role: __("Operations"),
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
	return (frm.doc.custom_task_permits || []).filter((r) => r.permit_type);
}

function permit_rows_all_have_journal_entry(frm) {
	const rows = permit_finance_rows_on_form(frm);
	return rows.length > 0 && rows.every((r) => r.journal_entry);
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

function permit_rows_pending_receipt_verification(frm) {
	return (frm.doc.custom_task_permits || []).filter(
		(r) => r.permit_type && r.payment_receipt && !r.receipt_verified
	);
}

function task_has_recorded_payment_on_form(frm) {
	if (is_permit_payment_pattern(frm)) {
		return permit_rows_all_have_journal_entry(frm);
	}
	return Boolean(frm.doc.custom_journal_entry || frm.doc.custom_payment_entry);
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
	if (
		!rows.length ||
		rows.some((r) => !r.journal_entry || !r.payment_receipt || !r.receipt_verified)
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
					"Permit receipts verified — Finance and declarant pre-clearance tasks completed."
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
	const seq = sea_task_sequence(frm);

	// Set docfield properties directly - avoid toggle_enable() which re-renders the grid
	// and can collapse the toolbar while the user clicks action buttons.
	const line_label_df = grid.get_docfield("line_label");
	const verified_df = grid.get_docfield("verified");
	if (line_label_df) {
		line_label_df.read_only = 1;
	}
	if (verified_df) {
		verified_df.read_only =
			is_ucr_application_step(frm, seq) ||
			is_entry_application_step(frm, seq) ||
			is_shipping_line_application_step(frm, seq) ||
			is_kpa_application_step(frm, seq)
				? 1
				: is_finance
					? 0
					: 1;
	}

	if (is_ucr_application_step(frm, seq)) {
		grid.update_docfield_property("attachment", "read_only", 0);
		grid.update_docfield_property("amount", "read_only", 0);
		grid.update_docfield_property("item_code", "read_only", 1);
		grid.update_docfield_property("item_code", "hidden", 0);
	} else if (is_entry_application_step(frm, seq)) {
		grid.update_docfield_property("attachment", "read_only", 0);
		grid.update_docfield_property("amount", "read_only", 0);
		grid.update_docfield_property("item_code", "read_only", 1);
		grid.update_docfield_property("item_code", "hidden", 0);
	} else if (is_shipping_line_application_step(frm, seq)) {
		grid.update_docfield_property("attachment", "read_only", 0);
		grid.update_docfield_property("amount", "read_only", 0);
		grid.update_docfield_property("item_code", "read_only", 1);
		grid.update_docfield_property("item_code", "hidden", 0);
	} else if (is_kpa_application_step(frm, seq)) {
		grid.update_docfield_property("attachment", "read_only", 0);
		grid.update_docfield_property("amount", "read_only", 0);
		grid.update_docfield_property("item_code", "read_only", 1);
		grid.update_docfield_property("item_code", "hidden", 0);
	} else if (is_ucr_finance_step(frm, seq)) {
		// Invoice and receipt are copied from Create UCR (IDF); Finance verifies only.
		grid.update_docfield_property("attachment", "read_only", 1);
		grid.update_docfield_property("amount", "read_only", 1);
		grid.update_docfield_property("item_code", "read_only", 1);
		grid.update_docfield_property("item_code", "hidden", 0);
	} else if (is_entry_finance_step(frm, seq)) {
		grid.update_docfield_property("attachment", "read_only", 1);
		grid.update_docfield_property("amount", "read_only", 1);
		grid.update_docfield_property("item_code", "read_only", 1);
		grid.update_docfield_property("item_code", "hidden", 0);
	} else if (is_shipping_line_finance_step(frm, seq)) {
		grid.update_docfield_property("attachment", "read_only", 1);
		grid.update_docfield_property("amount", "read_only", 1);
		grid.update_docfield_property("item_code", "read_only", 1);
		grid.update_docfield_property("item_code", "hidden", 0);
	} else if (is_kpa_finance_step(frm, seq)) {
		grid.update_docfield_property("attachment", "read_only", 1);
		grid.update_docfield_property("amount", "read_only", 1);
		grid.update_docfield_property("item_code", "read_only", 1);
		grid.update_docfield_property("item_code", "hidden", 0);
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

function add_cgm_toolbar_button(frm, label, fn, opts = {}) {
	const btn = frm.add_custom_button(label, fn, CGM_ACTION_GROUP);
	frm.page.set_inner_btn_group_as_primary(CGM_ACTION_GROUP);
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
			"<b>Declarant:</b> Attach <b>UCR Invoice</b>, enter the <b>Amount</b>, and save on " +
				"<b>Invoices & Receipts</b> - Finance is notified automatically. After payment, attach the " +
				"supplier <b>UCR Receipt</b> and the IDF/UCR certificate under <b>Clearance Documents</b> when issued."
		);
	}
	set_task_intro(frm, intro);
}

function toggle_permit_invoice_fields_for_origin(grid) {
	if (!grid) {
		return;
	}
	const invoice_fields = [
		"payment_invoice",
		"invoice_amount",
		"invoice_uploaded_on",
		"invoice_uploaded_by",
		"invoice_verified",
	];
	invoice_fields.forEach((fn) => {
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

	const invoices_sent = cint(frm.doc.custom_permit_invoices_submitted);
	const has_invoices = permit_rows_have_invoices(frm);
	const invoices_ready = invoices_sent || has_invoices;
	const lock_invoices = invoices_sent && has_invoices;
	const can_upload_proof =
		user_can_upload_receipt(frm) ||
		frm.doc.owner === frappe.session.user ||
		frappe.session.user === "Administrator";

	if (is_permit_application_step(frm, seq)) {
		grid.update_docfield_property("origin", "read_only", lock_invoices ? 1 : 0);
		grid.update_docfield_property("payment_invoice", "read_only", lock_invoices ? 1 : can_upload_proof ? 0 : 1);
		grid.update_docfield_property("invoice_amount", "read_only", lock_invoices ? 1 : can_upload_proof ? 0 : 1);
		grid.update_docfield_property("payment_receipt", "hidden", invoices_ready ? 0 : 1);
		grid.update_docfield_property("payment_receipt", "read_only", can_upload_proof ? 0 : 1);
		grid.update_docfield_property("permit_document", "hidden", 0);
		grid.update_docfield_property("permit_document", "read_only", can_upload_proof ? 0 : 1);
		grid.update_docfield_property("receipt_verified", "hidden", invoices_ready ? 0 : 1);
		grid.update_docfield_property("receipt_verified", "read_only", 1);
		toggle_permit_invoice_fields_for_origin(grid);
	} else if (is_permit_finance_step(frm, seq)) {
		["payment_invoice", "purchase_invoice", "payment_entry", "permit_document"].forEach((fn) => {
			grid.update_docfield_property(fn, "read_only", 1);
		});
		grid.update_docfield_property("journal_entry", "hidden", 0);
		grid.update_docfield_property("journal_entry", "read_only", 1);
		grid.update_docfield_property("journal_entry", "in_list_view", 1);
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
		if (is_ucr_application_step(frm) && row.attachment) {
			if (row.line_type === "Invoice") {
				frappe.show_alert({
					message: __("UCR invoice saved - Finance will be notified when you save."),
					indicator: "green",
				});
			} else if (row.line_type === "Receipt") {
				frappe.show_alert({
					message: __("UCR receipt saved - Finance will be notified to verify when you save."),
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
			} else if (row.line_type === "Receipt") {
				frappe.show_alert({
					message: __("Entry Slip receipt saved - Finance will be notified to verify when you save."),
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
			} else if (row.line_type === "Receipt") {
				frappe.show_alert({
					message: __(
						"Shipping Line receipt saved - Finance will be notified to verify when you save."
					),
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
			} else if (row.line_type === "Receipt") {
				frappe.show_alert({
					message: __("KPA receipt saved - Finance will be notified to verify when you save."),
					indicator: "green",
				});
			}
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
			["payment_invoice", "invoice_amount", "invoice_verified"].forEach((fn) => {
				if (row[fn]) {
					frappe.model.set_value(cdt, cdn, fn, fn === "invoice_verified" ? 0 : "");
				}
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
		if (frm.doc.status !== "Completed") {
			frm.save();
		}
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
			frappe.call({
				method: "cgm_shipping.cgm_worldwide_shipping.customizations.workflow.notify_finance_verify_receipts",
				args: { task_name: frm.doc.name },
			});
		}
		if (frm.doc.status !== "Completed") {
			frm.save();
		}
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
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.workflow.ensure_ucr_finance_task_completed",
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
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.workflow.verify_ucr_finance_line",
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
		intro = __("<b>All declarant documents are in place.</b> Completing this task…");
	} else if (status.receipt_attached && !status.certificate_attached) {
		intro = __(
			"<b>Attach the ENTRY customs document</b> under <b>Clearance Documents</b> to finish this task."
		);
	} else if (status.receipt_attached) {
		intro = __(
			"<b>Entry Slip receipt uploaded.</b> Attach the ENTRY customs document under <b>Clearance Documents</b> to complete this task."
		);
	} else if (status.payment_made) {
		intro = __(
			"<b>Finance has paid the Entry Slip invoice.</b> Attach the supplier <b>{0}</b> on " +
				"<b>Invoices &amp; Receipts</b> below. When the ENTRY document is issued, attach it under " +
				"<b>Clearance Documents</b>.",
			[receiptLabel]
		);
	} else if (status.invoice_verified) {
		intro = __(
			"<b>{0} verified by Finance.</b> Waiting for payment. After payment, attach the " +
				"<b>{1}</b> here and the ENTRY document under <b>Clearance Documents</b> when issued.",
			[invoiceLabel, receiptLabel]
		);
	} else if (status.invoice_submitted) {
		intro = __(
			"<b>{0} submitted to Finance.</b> Waiting for Finance to verify and pay. " +
				"After payment you will upload the supplier receipt here.",
			[invoiceLabel]
		);
	} else {
		intro = __(
			"<b>Declarant:</b> Attach <b>{0}</b>, enter the <b>Amount</b>, and save on " +
				"<b>Invoices & Receipts</b> - Finance is notified automatically. After payment, attach the " +
				"supplier <b>{1}</b> and the ENTRY document under <b>Clearance Documents</b> when issued.",
			[invoiceLabel, receiptLabel]
		);
	}
	set_task_intro(frm, intro);
}

function ensure_entry_finance_task_completed_on_form(frm) {
	if (frm._cgm_entry_finance_complete_checking) {
		return;
	}
	const inv = get_finance_line(frm, "Invoice");
	const rec = get_finance_line(frm, "Receipt");
	if (!inv?.verified || !rec?.verified || !rec?.attachment) {
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
			if (r.message.status === "Completed" && frm.doc.status !== "Completed") {
				frappe.show_alert({
					message: __("Finance Pays Entry Slip task completed"),
					indicator: "green",
				});
				frm.reload_doc();
			}
		},
		error() {
			frm._cgm_entry_finance_complete_checking = false;
		},
	});
}

function verify_entry_finance_line(frm, line_type) {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.verify_application_finance_line",
		args: { task_name: frm.doc.name, profile_key: "entry", line_type },
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
	if (get_finance_line(frm, "Receipt") || frm[ensuringKey]) {
		return;
	}
	frm[ensuringKey] = true;
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.ensure_application_finance_lines",
		args: { task_name: frm.doc.name, profile_key: profileKey },
		callback(r) {
			frm[ensuringKey] = false;
			if (!r.exc && r.message?.added) {
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
			if (r.message.task_status === "Completed" && frm.doc.status !== "Completed") {
				frappe.show_alert({
					message: __("Application task completed"),
					indicator: "green",
				});
				frm.reload_doc();
				return;
			}
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

function configure_shipping_line_deposit_grid(frm) {
	const grid = frm.fields_dict.custom_container_updates?.grid;
	if (!grid) {
		return;
	}
	frm.toggle_display("custom_section_container_updates", true);
	frm.toggle_display("custom_container_updates", true);
	["has_deposit", "deposit_amount"].forEach((fn) => {
		grid.update_docfield_property(fn, "hidden", 0);
		grid.update_docfield_property(fn, "in_list_view", 1);
	});
	if (grid.wrapper) {
		grid.refresh();
	}
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
	let intro;
	if (status.task_status === "Completed" || frm.doc.status === "Completed") {
		intro = __("<b>All documents are in place.</b> This task is <b>Completed</b>.");
	} else if (status.application_ready_to_complete) {
		intro = __("<b>All documents are in place.</b> Completing this task…");
	} else if (status.receipt_attached) {
		intro = __("<b>{0} receipt uploaded.</b> This task will complete automatically.", [
			invoiceLabel,
		]);
	} else if (status.payment_made) {
		intro = __(
			"<b>Finance has paid the {0}.</b> Attach the supplier <b>{1}</b> on " +
				"<b>Invoices &amp; Receipts</b> below.",
			[invoiceLabel, receiptLabel]
		);
	} else if (status.invoice_verified) {
		intro = __(
			"<b>{0} verified by Finance.</b> Waiting for payment. After payment, attach the " +
				"<b>{1}</b> here.",
			[invoiceLabel, receiptLabel]
		);
	} else if (status.invoice_submitted) {
		intro = __(
			"<b>{0} submitted to Finance.</b> Waiting for Finance to verify and pay. " +
				"After payment you will upload the supplier receipt here.",
			[invoiceLabel]
		);
	} else {
		intro = __(
			"<b>{0}:</b> Attach <b>{1}</b>, enter the <b>Amount</b>, and save on " +
				"<b>Invoices & Receipts</b> - Finance is notified automatically. After payment, attach the " +
				"supplier <b>{2}</b>.",
			[uploadRole, invoiceLabel, receiptLabel]
		);
		if (profileKey === "shipping_line") {
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
	if (frm[checkingKey]) {
		return;
	}
	if (!is_app_finance_finance_step(frm, undefined, profileKey) || frm.doc.status === "Completed") {
		return;
	}
	const inv = get_finance_line(frm, "Invoice");
	const rec = get_finance_line(frm, "Receipt");
	if (!inv?.verified || !rec?.verified || !rec?.attachment) {
		return;
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
			if (r.message.status === "Completed" && frm.doc.status !== "Completed") {
				frappe.show_alert({
					message: __("Finance task completed"),
					indicator: "green",
				});
				frm.reload_doc();
			}
		},
		error() {
			frm[checkingKey] = false;
		},
	});
}

function verify_app_finance_line(frm, profileKey, lineType) {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance.verify_application_finance_line",
		args: { task_name: frm.doc.name, profile_key: profileKey, line_type: lineType },
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

// ─── Make Payment → draft Journal Entry (Finance department) ──────────────────

function is_finance_department_task(frm) {
	const finance_dept =
		frm._cgm_finance_department || get_cgm_sea_seq_config(frm).finance_department;
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
		add_cgm_toolbar_button(frm, __("View Journal Entry — {0}", [row.permit_type]), () => {
			frappe.set_route("Form", "Journal Entry", row.journal_entry);
		});
	});
}

function setup_permit_finance_make_payment_buttons(frm) {
	permit_finance_rows_on_form(frm).forEach((row) => {
		if (row.journal_entry) {
			return;
		}
		add_cgm_toolbar_button(
			frm,
			__("Make Payment — {0}", [row.permit_type]),
			() =>
				open_journal_entry_payment_dialog(frm, {
					permit_row_name: row.name,
					default_amount: row.invoice_amount,
					title_suffix: row.permit_type,
				}),
			{ primary: true }
		);
	});
}

function setup_permit_finance_payment_buttons(frm) {
	show_permit_finance_journal_entry_view_buttons(frm);
	setup_permit_finance_make_payment_buttons(frm);
}

function open_journal_entry_payment_dialog(frm, opts = {}) {
	const permit_row_name = opts.permit_row_name || null;
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
		cur_frm.reload_doc();
	}
});
